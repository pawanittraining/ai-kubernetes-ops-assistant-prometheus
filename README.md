# AI Kubernetes Operations Center

A read-only Streamlit assistant that uses Ollama tool calling to answer natural-language questions about Prometheus metrics.

## 1. Prerequisites

- Python 3.10+
- Prometheus reachable at `http://localhost:9090`
- Ollama running locally
- A model pulled into Ollama (example: `qwen3:4b`)
- Prometheus metrics from kube-state-metrics, cAdvisor/kubelet and Node Exporter as applicable

## 2. Install

```bash
cd ai-kubernetes-ops-assistant
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` if your endpoints or model differ.

## 3. Start Ollama and download model

```bash
ollama serve
ollama pull qwen3:4b
ollama list
```

If Ollama is already running as a macOS app, you usually do not need to run `ollama serve` again.

## 4. Expose Prometheus from Kind

In another terminal:

```bash
kubectl get pods -n monitoring
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090
```

Keep the port-forward terminal open. The service name can differ; check with:

```bash
kubectl get svc -n monitoring | grep prometheus
```

Test:

```bash
curl -G http://localhost:9090/api/v1/query --data-urlencode 'query=up'
```

## 5. Launch

```bash
streamlit run prometheus_app.py
```

## 6. Try these questions

- Show me the top 5 pods by CPU usage.
- Which pods are consuming the most memory in production?
- Which nodes have the highest CPU utilization?
- Which nodes have the highest memory utilization?
- Which nodes have the highest root disk usage?
- Show CPU, memory and restart metrics for pod `my-api` in namespace `production`.
- Why might this pod be restarting?

For the final question, the assistant should be careful: metrics alone may not establish the root cause. Logs and Kubernetes events will be added in the next phase.

## Troubleshooting

### Prometheus returns empty results
Check that the required exporters are installed and targets are healthy in Prometheus **Status → Targets**. Run the metric name directly in the Prometheus expression browser.

### Node queries return no data
Node CPU and memory metrics require Node Exporter. Check whether `node_cpu_seconds_total` and `node_memory_MemAvailable_bytes` exist. Root disk usage also requires `node_filesystem_avail_bytes` and `node_filesystem_size_bytes` with a `/` mountpoint.

### Pod CPU/memory returns no data
Check `container_cpu_usage_seconds_total` and `container_memory_working_set_bytes`. Some environments use different labels or scrape configuration.

The Metrics Explorer formats CPU in cores or millicores, memory in readable
byte units, and node CPU, memory, and root disk utilization as percentages.

### Ollama connection/model errors
```bash
ollama list
curl http://localhost:11434/api/tags
```
Ensure `.env` model name exactly matches an installed model.

### Tool calling is not happening
Use a model that supports tool calling in the installed Ollama version. Upgrade the Python package with `pip install -U ollama` if necessary.
