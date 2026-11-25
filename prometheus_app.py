import os
import streamlit as st
from dotenv import load_dotenv

from collectors.prometheus_collector import PrometheusCollector
from ai.agent import KubernetesOpsAgent

load_dotenv()

st.set_page_config(
    page_title="AI Kubernetes Operations Center",
    page_icon="🛠️",
    layout="wide",
)

st.title("🛠️ AI Kubernetes Operations Center")
st.caption("Ask questions about Prometheus metrics and investigate cluster health.")

PROM_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")


def format_cpu(value):
    if value is None:
        return "N/A"
    if abs(value) < 1:
        return f"{value * 1000:.1f} mCPU"
    return f"{value:.2f} cores"


def format_bytes(value):
    if value is None:
        return "N/A"
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    size = float(value)
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def format_percent(value):
    return "N/A" if value is None else f"{value:.1f}%"


def byte_chart_scale(values):
    largest = max((abs(value) for value in values if value is not None), default=0)
    if largest >= 1024**3:
        return 1024**3, "GiB"
    if largest >= 1024**2:
        return 1024**2, "MiB"
    if largest >= 1024:
        return 1024, "KiB"
    return 1, "B"


@st.cache_resource
def get_prometheus(url):
    return PrometheusCollector(url=url)


@st.cache_resource
def get_agent(url, model, host):
    return KubernetesOpsAgent(
        prometheus=get_prometheus(url),
        model=model,
        host=host,
    )


with st.sidebar:
    st.header("Connections")
    st.write(f"**Prometheus:** `{PROM_URL}`")
    st.write(f"**Ollama:** `{OLLAMA_HOST}`")
    st.write(f"**Model:** `{OLLAMA_MODEL}`")
    if st.button("Test connections", use_container_width=True):
        try:
            get_prometheus(PROM_URL).health()
            st.success("Prometheus API is responding.")
        except Exception as exc:
            st.error(f"Prometheus connection failed: {exc}")
        try:
            import ollama
            ollama.Client(host=OLLAMA_HOST).list()
            st.success("Ollama is responding.")
        except Exception as exc:
            st.error(f"Ollama connection failed: {exc}")
    st.divider()
    st.subheader("Example questions")
    examples = [
        "Show me the top 5 pods by CPU usage.",
        "Which pods are consuming the most memory in production?",
        "Which nodes have the highest CPU utilization?",
        "Which nodes have the highest memory utilization?",
        "Which nodes have the highest root disk usage?",
        "Show CPU, memory and restart metrics for pod my-api in namespace production.",
    ]
    for example in examples:
        if st.button(example, use_container_width=True):
            st.session_state.pending_prompt = example
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.chat_messages = []
        st.session_state.pending_prompt = ""
        st.rerun()

try:
    prometheus = get_prometheus(PROM_URL)
    agent = get_agent(PROM_URL, OLLAMA_MODEL, OLLAMA_HOST)
    with st.spinner("Checking Prometheus..."):
        prometheus.health()
    st.success("Prometheus connected", icon="🟢")
except Exception as exc:
    st.error(f"Unable to initialize the application: {exc}")
    st.info("Check that Prometheus port-forward is running and your .env settings are correct.")
    st.stop()

# Compact dashboard summary. Empty vectors are displayed as unavailable.
c1, c2, c3, c4 = st.columns(4)
try:
    ns = prometheus.list_namespaces()
    c1.metric("Namespaces discovered", len(ns))
except Exception:
    ns = []
    c1.metric("Namespaces discovered", "N/A")
try:
    cpu = prometheus.top_pods_cpu(limit=1)
    c2.metric("Highest pod CPU", format_cpu(cpu[0]["value"]) if cpu else "N/A")
except Exception:
    c2.metric("Highest pod CPU", "N/A")
try:
    mem = prometheus.top_pods_memory(limit=1)
    c3.metric("Highest pod memory", format_bytes(mem[0]["value"]) if mem else "N/A")
except Exception:
    c3.metric("Highest pod memory", "N/A")
try:
    disk = prometheus.top_nodes_disk(limit=1)
    c4.metric("Highest node root disk usage", format_percent(disk[0]["value"]) if disk else "N/A")
except Exception:
    c4.metric("Highest node root disk usage", "N/A")

st.divider()

tab_chat, tab_explorer, tab_help = st.tabs(["💬 AI Assistant", "📊 Metrics Explorer", "ℹ️ Setup & limitations"])

with tab_chat:
    st.subheader("Ask your Kubernetes observability assistant")
    st.caption("Follow-up questions retain the conversation context. Live metric questions can trigger Prometheus tools.")
    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []
    if "pending_prompt" not in st.session_state:
        st.session_state.pending_prompt = ""

    for item in st.session_state.chat_messages:
        with st.chat_message(item["role"]):
            st.markdown(item["content"])

    prompt = st.chat_input("Ask about pod CPU, memory, restarts, nodes...")
    if st.session_state.pending_prompt:
        prompt = st.session_state.pending_prompt
        st.session_state.pending_prompt = ""

    if prompt:
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant"):
            with st.spinner("Investigating metrics..."):
                try:
                    answer = agent.respond(st.session_state.chat_messages)
                except Exception as exc:
                    answer = (
                        f"**Agent error:** {exc}\n\n"
                        "Check that the Ollama service is running and the configured model is installed."
                    )
            st.markdown(answer)
        st.session_state.chat_messages.append({"role": "assistant", "content": answer})

with tab_explorer:
    st.subheader("Metrics Explorer")
    st.caption("This tab uses Prometheus directly; it does not ask the LLM to interpret the result.")
    metric_choice = st.selectbox(
        "Metric",
        [
            "Top pods by CPU",
            "Top pods by memory",
            "Top nodes by CPU",
            "Top nodes by memory",
            "Top nodes by root disk usage",
        ],
    )
    pod_metric = metric_choice.startswith("Top pods")
    if pod_metric:
        namespace_filter = st.selectbox("Namespace filter", ["All namespaces"] + ns)
    else:
        namespace_filter = "All namespaces"
        st.caption("Node metrics are cluster-wide and are not filtered by namespace.")
    limit = st.slider("Number of results", 1, 20, 5)
    if st.button("Run metrics query", type="primary"):
        try:
            namespace_arg = None if namespace_filter == "All namespaces" else namespace_filter
            if metric_choice == "Top pods by CPU":
                rows = prometheus.top_pods_cpu(namespace_arg, limit)
            elif metric_choice == "Top pods by memory":
                rows = prometheus.top_pods_memory(namespace_arg, limit)
            elif metric_choice == "Top nodes by CPU":
                rows = prometheus.top_nodes_cpu(limit)
            elif metric_choice == "Top nodes by memory":
                rows = prometheus.top_nodes_memory(limit)
            else:
                rows = prometheus.top_nodes_disk(limit)

            if not rows:
                st.warning("Prometheus returned no matching series. Check exporters, scrape targets and metric labels.")
            else:
                import pandas as pd
                raw_values = [row["value"] for row in rows]
                byte_scale, byte_unit = byte_chart_scale(raw_values)

                if metric_choice == "Top pods by CPU":
                    value_label = "CPU"
                    chart_label = "CPU (cores)"
                    formatter = format_cpu
                    chart_scale = 1
                elif metric_choice == "Top pods by memory":
                    value_label = "Memory"
                    chart_label = f"Memory ({byte_unit})"
                    formatter = format_bytes
                    chart_scale = byte_scale
                elif metric_choice == "Top nodes by CPU":
                    value_label = "CPU usage"
                    chart_label = "CPU usage (%)"
                    formatter = format_percent
                    chart_scale = 1
                elif metric_choice == "Top nodes by memory":
                    value_label = "Memory usage"
                    chart_label = "Memory usage (%)"
                    formatter = format_percent
                    chart_scale = 1
                else:
                    value_label = "Root disk usage"
                    chart_label = "Root disk usage (%)"
                    formatter = format_percent
                    chart_scale = 1

                display_rows = []
                chart_rows = []
                for row in rows:
                    labels = row["labels"]
                    resource = (
                        f'{labels["namespace"]}/{labels["pod"]}'
                        if "namespace" in labels and "pod" in labels
                        else labels.get("instance", labels.get("pod", "Unknown"))
                    )
                    display_rows.append({
                        "Resource": resource,
                        value_label: formatter(row["value"]),
                    })
                    if row["value"] is not None:
                        chart_rows.append({
                            "Resource": resource,
                            chart_label: row["value"] / chart_scale,
                        })

                st.dataframe(
                    pd.DataFrame(display_rows),
                    use_container_width=True,
                    hide_index=True,
                )
                if chart_rows:
                    chart = pd.DataFrame(chart_rows).set_index("Resource")
                    st.bar_chart(chart, y_label=chart_label)
        except Exception as exc:
            st.error(f"Query failed: {exc}")

with tab_help:
    st.markdown("""
### What this first build supports
- Natural-language questions about pod CPU and memory rankings.
- Node CPU and memory utilization, if Node Exporter metrics are scraped.
- Root filesystem usage by node, if Node Exporter filesystem metrics are scraped.
- Pod-level CPU, memory, restart-increase and readiness metrics.
- Multi-turn follow-up questions using the current chat history.
- A direct metrics explorer for quick comparisons.

### Not included yet
- Pod logs and Kubernetes events (next integration).
- Host-level node logs such as kubelet/journald logs (requires a log pipeline such as Fluent Bit + Loki).
- Mutating actions such as deleting pods, scaling deployments or restarting workloads.
- Historical charts in the chat agent (the collector has a range-query foundation, but this first UI focuses on instant queries).

### Metric prerequisites
- `kube_pod_info` and `kube_pod_container_status_*` generally come from kube-state-metrics.
- `container_cpu_usage_seconds_total` and `container_memory_working_set_bytes` generally come from kubelet/cAdvisor.
- `node_cpu_seconds_total` and `node_memory_*` generally come from Node Exporter.
- `node_filesystem_avail_bytes` and `node_filesystem_size_bytes` generally come from Node Exporter; root disk usage is shown for mountpoint `/`.
- Metric names and labels vary by installation. Verify queries in the Prometheus UI if a result is empty.

**Safety:** This version exposes read-only Prometheus queries through an allow-list. It does not execute kubectl commands or modify your cluster.
""")
