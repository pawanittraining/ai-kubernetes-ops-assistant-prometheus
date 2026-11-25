import os
import requests
from dotenv import load_dotenv

load_dotenv()


class PrometheusCollector:
    """Small read-only client for the Prometheus HTTP API."""

    def __init__(self, url=None, timeout=None):
        self.url = (url or os.getenv(
            "PROMETHEUS_URL", "http://localhost:9090"
        )).rstrip("/")
        self.timeout = int(timeout or os.getenv("PROMETHEUS_TIMEOUT", "15"))
        self.session = requests.Session()

    def query(self, promql):
        response = self.session.get(
            f"{self.url}/api/v1/query",
            params={"query": promql},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            raise RuntimeError(payload.get("error", "Prometheus query failed"))
        return payload.get("data", {}).get("result", [])

    def query_range(self, promql, start, end, step="60s"):
        response = self.session.get(
            f"{self.url}/api/v1/query_range",
            params={
                "query": promql,
                "start": start,
                "end": end,
                "step": step,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            raise RuntimeError(payload.get("error", "Prometheus range query failed"))
        return payload.get("data", {}).get("result", [])

    def health(self):
        return self.query("up")

    @staticmethod
    def _escape_label(value):
        # PromQL string-literal escaping for label values.
        value = str(value)
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    def _selector(self, **labels):
        return ",".join(
            f'{key}="{self._escape_label(value)}"'
            for key, value in labels.items() if value is not None
        )

    @staticmethod
    def _instant_values(result):
        rows = []
        for item in result:
            metric = item.get("metric", {})
            sample = item.get("value", [None, None])
            try:
                value = float(sample[1])
            except (TypeError, ValueError, IndexError):
                value = None
            rows.append({"labels": metric, "value": value})
        return rows

    def list_namespaces(self):
        result = self.query("count by (namespace) (kube_pod_info)")
        return sorted({
            row.get("metric", {}).get("namespace")
            for row in result if row.get("metric", {}).get("namespace")
        })

    def list_pods(self, namespace):
        selector = self._selector(namespace=namespace)
        result = self.query(f"count by (pod) (kube_pod_info{{{selector}}})")
        return sorted({
            row.get("metric", {}).get("pod")
            for row in result if row.get("metric", {}).get("pod")
        })

    def top_pods_cpu(self, namespace=None, limit=5):
        limit = max(1, min(int(limit), 20))
        selector = self._selector(namespace=namespace)
        promql = (
            f"topk({limit}, sum by (namespace,pod) "
            f"(rate(container_cpu_usage_seconds_total"
            f'{{{selector + "," if selector else ""}container!="",image!=""}}[5m])))'
        )
        return self._instant_values(self.query(promql))

    def top_pods_memory(self, namespace=None, limit=5):
        limit = max(1, min(int(limit), 20))
        selector = self._selector(namespace=namespace)
        promql = (
            f"topk({limit}, sum by (namespace,pod) "
            f"(container_memory_working_set_bytes"
            f'{{{selector + "," if selector else ""}container!="",image!=""}}))'
        )
        return self._instant_values(self.query(promql))

    def top_nodes_cpu(self, limit=5):
        limit = max(1, min(int(limit), 20))
        promql = (
            f"topk({limit}, 100 * (1 - avg by (instance) "
            f"(rate(node_cpu_seconds_total{{mode='idle'}}[5m]))))"
        )
        return self._instant_values(self.query(promql))

    def top_nodes_memory(self, limit=5):
        limit = max(1, min(int(limit), 20))
        promql = (
            f"topk({limit}, 100 * (1 - "
            f"(node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)))"
        )
        return self._instant_values(self.query(promql))

    def top_nodes_disk(self, limit=5):
        limit = max(1, min(int(limit), 20))
        filesystem = (
            'mountpoint="/",fstype!~"tmpfs|overlay|rootfs"'
        )
        promql = (
            f"topk({limit}, 100 * (1 - "
            f"(node_filesystem_avail_bytes{{{filesystem}}} / "
            f"node_filesystem_size_bytes{{{filesystem}}})))"
        )
        return self._instant_values(self.query(promql))

    def pod_metrics(self, namespace, pod):
        selector = self._selector(namespace=namespace, pod=pod)
        return {
            "cpu_cores_5m": self._instant_values(self.query(
                f"sum by (namespace,pod) "
                f"(rate(container_cpu_usage_seconds_total"
                f'{{{selector},container!="",image!=""}}[5m]))'
            )),
            "memory_working_set_bytes": self._instant_values(self.query(
                f"sum by (namespace,pod) "
                f"(container_memory_working_set_bytes"
                f'{{{selector},container!="",image!=""}})'
            )),
            "restarts_increase_1h": self._instant_values(self.query(
                f"sum by (namespace,pod) "
                f"(increase(kube_pod_container_status_restarts_total"
                f"{{{selector}}}[1h]))"
            )),
            "ready_containers": self._instant_values(self.query(
                f"sum by (namespace,pod) "
                f"(kube_pod_container_status_ready{{{selector}}})"
            )),
        }

    def metric_range(self, metric, namespace=None, pod=None, hours=1, step="60s"):
        # Deliberately allow-list metric names. This prevents arbitrary PromQL
        # from being generated by the model through this tool.
        allowed = {
            "pod_cpu": "sum by (namespace,pod) (rate(container_cpu_usage_seconds_total{container!='',image!=''}[5m]))",
            "pod_memory": "sum by (namespace,pod) (container_memory_working_set_bytes{container!='',image!=''})",
            "node_cpu": "100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode='idle'}[5m])))",
            "node_memory": "100 * (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes))",
        }
        if metric not in allowed:
            raise ValueError(f"Unsupported metric. Choose one of: {', '.join(allowed)}")
        expr = allowed[metric]
        matchers = []
        if namespace:
            matchers.append(f'namespace="{self._escape_label(namespace)}"')
        if pod:
            matchers.append(f'pod="{self._escape_label(pod)}"')
        if matchers and metric.startswith("pod_"):
            # Add filters to the inner vector selector.
            expr = expr.replace("{", "{" + ",".join(matchers) + ",", 1)
        import time
        end = int(time.time())
        start = end - max(1, min(int(hours), 24)) * 3600
        return self.query_range(expr, start, end, step)
