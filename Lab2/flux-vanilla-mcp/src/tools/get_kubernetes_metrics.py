"""Fetch Kubernetes resource metrics via metrics.k8s.io.

Queries the Metrics Server and returns CPU + memory usage for pods and/or
nodes.  Gracefully handles missing metrics.k8s.io (no Metrics Server).
"""

from __future__ import annotations

import math
from typing import Any

import yaml
from kubernetes import client
from kubernetes.client.rest import ApiException
from mcp.types import ToolAnnotations

from core.k8s_client import get_api_client
from core.scopes import check_scope, register_scope
from core.server import mcp

TOOL_NAME = "get_kubernetes_metrics"
register_scope(TOOL_NAME, read_only=True, in_cluster=True)

_METRICS_API_GROUP = "metrics.k8s.io"
_METRICS_API_VERSION = "v1beta1"


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Get Kubernetes metrics",
        readOnlyHint=True,
    ),
)
def get_kubernetes_metrics(
    pod_name: str | None = None,
    namespace: str = "default",
    all_namespaces: bool = False,
    node_name: str | None = None,
) -> str:
    """Retrieve CPU and memory metrics from the Kubernetes Metrics Server.

    Exactly one of ``pod_name`` or ``node_name`` must be provided.
    Omit both to list metrics for **all pods** across the cluster.

    Args:
        pod_name: Single pod name (requires ``namespace`` unless
            ``all_namespaces`` is true).
        namespace: Namespace for ``pod_name`` queries (default: ``default``).
        all_namespaces: Set to ``True`` to list pods in every namespace.
        node_name: Node name for node-level metrics.
    """
    check_scope(TOOL_NAME)
    csa = client.CustomObjectsApi(get_api_client())

    try:
        if pod_name and node_name:
            return "error: provide either pod_name or node_name, not both"

        if pod_name:
            resource = "pods"
            if all_namespaces:
                data = csa.list_cluster_custom_object(
                    group=_METRICS_API_GROUP,
                    version=_METRICS_API_VERSION,
                    plural=resource,
                )
            else:
                data = csa.list_namespaced_custom_object(
                    group=_METRICS_API_GROUP,
                    version=_METRICS_API_VERSION,
                    plural=resource,
                    namespace=namespace,
                )
            # list_*_custom_object returns every pod in scope; filter to the
            # requested name in both cluster-wide and single-namespace cases.
            items = [
                i for i in data.get("items", [])
                if i["metadata"]["name"] == pod_name
            ]
            metrics_list = [_format_pod_metrics(pod) for pod in items]
        elif node_name:
            data = csa.get_cluster_custom_object(
                group=_METRICS_API_GROUP,
                version=_METRICS_API_VERSION,
                plural="nodes",
                name=node_name,
            )
            metrics_list = [_format_node_metrics(data)]
        else:
            # List all pods (scoped namespace or all namespaces).
            resource = "pods"
            if all_namespaces:
                data = csa.list_cluster_custom_object(
                    group=_METRICS_API_GROUP,
                    version=_METRICS_API_VERSION,
                    plural=resource,
                )
            else:
                data = csa.list_namespaced_custom_object(
                    group=_METRICS_API_GROUP,
                    version=_METRICS_API_VERSION,
                    plural=resource,
                    namespace=namespace,
                )
            metrics_list = [
                _format_pod_metrics(item)
                for item in data.get("items", [])
            ]

        return _render(metrics_list)

    except ApiException as exc:
        return _api_error(exc)


# -------------------------------------------------------------------
# Formatting helpers
# -------------------------------------------------------------------

def _format_container(name: str, usage: dict[str, str]) -> dict[str, str]:
    return {
        "name": name,
        "cpu": _humanize_cpu(usage.get("cpu", "")),
        "memory": _humanize_memory(usage.get("memory", "")),
    }


def _format_pod_metrics(pod: dict[str, Any]) -> dict[str, Any]:
    meta = pod.get("metadata", {})
    containers = pod.get("containers", [])
    return {
        "type": "pod",
        "name": meta.get("name", "?"),
        "namespace": meta.get("namespace", "?"),
        "containers": [
            _format_container(c["name"], c["usage"]) for c in containers
        ],
    }


def _format_node_metrics(node: dict[str, Any]) -> dict[str, Any]:
    meta = node.get("metadata", {})
    usage = node.get("usage", {})
    return {
        "type": "node",
        "name": meta.get("name", "?"),
        "cpu": _humanize_cpu(usage.get("cpu", "")),
        "memory": _humanize_memory(usage.get("memory", "")),
    }


def _humanize_cpu(raw: str) -> str:
    """Render a Kubernetes CPU quantity as millicores (`<1c`) or cores (`>=1c`).

    metrics.k8s.io reports CPU in mixed units depending on cluster version:
      * nanocores e.g. `"12345678n"` (most common today)
      * microcores e.g. `"1234u"`
      * millicores e.g. `"250m"`
      * whole cores e.g. `"2"`
    """
    if not raw:
        return "N/A"
    try:
        if raw.endswith("n"):
            millicores = int(raw[:-1]) / 1_000_000
        elif raw.endswith("u"):
            millicores = int(raw[:-1]) / 1_000
        elif raw.endswith("m"):
            millicores = float(raw[:-1])
        else:
            millicores = float(raw) * 1000
    except (ValueError, TypeError):
        return raw

    if millicores >= 1000:
        return f"{millicores / 1000:.2f}"
    return f"{millicores:.0f}m"


def _humanize_memory(raw: str) -> str:
    """Convert byte string (e.g. '17179869184') to human readable."""
    if not raw:
        return "N/A"
    try:
        value = int(raw)
    except (ValueError, TypeError):
        return raw

    if value == 0:
        return "0B"

    units = ["B", "Ki", "Mi", "Gi", "Ti"]
    idx = int(math.log(value, 1024)) if value > 0 else 0
    # Clamp to available units.
    idx = min(idx, len(units) - 1)
    scaled = value / (1024**idx)
    return f"{scaled:.1f}{units[idx]}"


def _render(items: list[dict]) -> str:
    """Return a simple table-like text representation."""
    return yaml.safe_dump(items, sort_keys=False)


def _api_error(exc: ApiException) -> str:
    if exc.status == 404:
        return (
            "metrics.k8s.io is not available."
            " The Metrics Server may not be installed on this cluster."
        )
    if exc.status == 403:
        return (
            "forbidden: the service account lacks permission to read"
            " metrics.k8s.io. Check the ClusterRoleBinding in deploy/rbac.yaml."
        )
    body = getattr(exc, "body", None)
    return f"error: {exc.status} {exc.reason}" + (
        f"\nbody: {body}" if isinstance(body, str) else ""
    )
