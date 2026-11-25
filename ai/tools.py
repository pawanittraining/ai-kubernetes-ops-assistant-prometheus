import json


class OpsTools:
    """The allow-listed, read-only tools exposed to the LLM."""

    def __init__(self, prometheus):
        self.prom = prometheus

    def definitions(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_top_pods_cpu",
                    "description": "Get pods ranked by CPU usage over the last five minutes. Returns CPU cores.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "namespace": {"type": ["string", "null"], "description": "Optional Kubernetes namespace filter."},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_top_pods_memory",
                    "description": "Get pods ranked by current memory working set. Returns bytes.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "namespace": {"type": ["string", "null"]},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}
                        },
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_top_nodes_cpu",
                    "description": "Get nodes ranked by CPU utilization percentage. Requires node-exporter metrics.",
                    "parameters": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_top_nodes_memory",
                    "description": "Get nodes ranked by memory utilization percentage. Requires node-exporter metrics.",
                    "parameters": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_top_nodes_disk",
                    "description": "Get nodes ranked by root filesystem usage percentage. Requires node-exporter filesystem metrics.",
                    "parameters": {
                        "type": "object",
                        "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_pod_metrics",
                    "description": "Get CPU, memory, restart increase and ready-container metrics for a specific pod.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "namespace": {"type": "string"},
                            "pod": {"type": "string"}
                        },
                        "required": ["namespace", "pod"]
                    }
                }
            }
        ]

    def execute(self, name, arguments):
        args = arguments or {}
        functions = {
            "get_top_pods_cpu": self.prom.top_pods_cpu,
            "get_top_pods_memory": self.prom.top_pods_memory,
            "get_top_nodes_cpu": self.prom.top_nodes_cpu,
            "get_top_nodes_memory": self.prom.top_nodes_memory,
            "get_top_nodes_disk": self.prom.top_nodes_disk,
            "get_pod_metrics": self.prom.pod_metrics,
        }
        if name not in functions:
            raise ValueError(f"Tool is not allowed: {name}")
        return functions[name](**args)


def json_for_model(value):
    return json.dumps(value, ensure_ascii=False, default=str)
