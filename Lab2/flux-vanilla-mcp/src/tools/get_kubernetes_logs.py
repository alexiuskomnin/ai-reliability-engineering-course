"""Fetch Kubernetes pod logs.

Uses the CoreV1Api to stream pod logs with a ~1 MB output cap so the
MCP response stays bounded.  Supports tail, previous-container, and
timestamp options.
"""

from __future__ import annotations

import textwrap
from io import StringIO

from kubernetes import client
from kubernetes.client.rest import ApiException
from mcp.types import ToolAnnotations

from core.k8s_client import get_api_client
from core.scopes import check_scope, register_scope
from core.server import mcp

TOOL_NAME = "get_kubernetes_logs"
register_scope(TOOL_NAME, read_only=True, in_cluster=True)

# Rough 1 MB cap to avoid bloating MCP responses.
_MAX_LOG_BYTES = 1_000_000


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Get Kubernetes pod logs",
        readOnlyHint=True,
    ),
)
def get_kubernetes_logs(
    pod_name: str,
    namespace: str = "default",
    container: str | None = None,
    tail_lines: int | None = None,
    previous: bool = False,
    timestamps: bool = False,
) -> str:
    """Retrieve logs for a Kubernetes Pod.

    Args:
        pod_name: Name of the Pod.
        namespace: Namespace of the Pod (default: ``default``).
        container: Container name.  Omit for the sole container in a Pod.
        tail_lines: Number of lines from the end of the log stream.
        previous: If true, return terminated container logs.
        timestamps: Prefix each log line with its time.
    """
    check_scope(TOOL_NAME)
    api = client.CoreV1Api(get_api_client())

    try:
        log: str = api.read_namespaced_pod_log(
            name=pod_name,
            namespace=namespace,
            container=container,
            tail_lines=tail_lines,
            previous=previous,
            timestamps=timestamps,
        )
    except ApiException as exc:
        return _api_error(exc)

    # Enforce the soft cap so MCP responses stay reasonable.
    truncated = False
    if len(log.encode("utf-8")) > _MAX_LOG_BYTES:
        buf = StringIO()
        consumed = 0
        for line in log.splitlines():
            line_bytes = len(line.encode("utf-8"))
            if consumed + line_bytes > _MAX_LOG_BYTES:
                truncated = True
                break
            buf.write(line)
            buf.write("\n")
            consumed += line_bytes + 1
        log = buf.getvalue()

    return textwrap.dedent(
        f"""\
        --- logs for pod/{pod_name} in {namespace} ---
        {log}"""
    ) + (
        "\n... (truncated at ~1 MB limit)" if truncated else ""
    )


def _api_error(exc: ApiException) -> str:
    body = getattr(exc, "body", None)
    return f"error: {exc.status} {exc.reason}" + (
        f"\nbody: {body}" if isinstance(body, str) else ""
    )
