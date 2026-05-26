"""Switch the active kubeconfig context in-memory.

Does NOT rewrite the kubeconfig file. Subsequent tool calls in this
process will build their Kubernetes client against the new context.

Disabled in in-cluster mode (no kubeconfig file is loaded).
"""

from __future__ import annotations

import yaml
from mcp.types import ToolAnnotations

from core.config import set_context_override
from core.k8s_client import list_contexts
from core.scopes import check_scope, register_scope
from core.server import mcp

TOOL_NAME = "set_kubeconfig_context"
# Read-only with respect to the cluster — never touches resources. Marked
# read_only=True so it remains available under --read-only mode.
register_scope(TOOL_NAME, read_only=True, in_cluster=False)


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Set kubeconfig context",
        readOnlyHint=True,
    ),
)
def set_kubeconfig_context(name: str) -> str:
    """Switch the active kubeconfig context for subsequent tool calls.

    The change is in-memory only — the kubeconfig file on disk is not
    modified. Use ``get_kubeconfig_contexts`` to see the available
    context names.

    Args:
        name: Name of a context defined in the loaded kubeconfig file.
    """
    check_scope(TOOL_NAME)

    contexts, _ = list_contexts()
    available = [c["name"] for c in contexts]
    if name not in available:
        return yaml.safe_dump(
            {
                "error": f"context {name!r} not found in kubeconfig",
                "available": available,
            }
        )

    set_context_override(name)
    return yaml.safe_dump(
        {"currentContext": name, "message": f"context switched to {name!r}"},
        sort_keys=False,
    )
