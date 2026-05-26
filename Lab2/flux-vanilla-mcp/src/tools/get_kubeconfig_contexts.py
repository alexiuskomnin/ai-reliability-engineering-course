"""List Kubernetes contexts available in the configured kubeconfig.

Read-only, local-only. Disabled in in-cluster mode (there's no kubeconfig
to read).
"""

from __future__ import annotations

import yaml
from mcp.types import ToolAnnotations

from core.config import get_config
from core.k8s_client import list_contexts
from core.scopes import check_scope, register_scope
from core.server import mcp

TOOL_NAME = "get_kubeconfig_contexts"
register_scope(TOOL_NAME, read_only=True, in_cluster=False)


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Get kubeconfig contexts",
        readOnlyHint=True,
    ),
)
def get_kubeconfig_contexts() -> str:
    """Return the list of Kubernetes contexts from the kubeconfig file,
    along with the currently active context.

    Returns:
        YAML document with `contexts` and `currentContext`. Honors the
        in-memory context override set via set_kubeconfig_context.
    """
    check_scope(TOOL_NAME)

    contexts, file_active = list_contexts()
    override = get_config().kube_context_override
    active = override or file_active

    payload = {
        "currentContext": active,
        "contexts": [
            {
                "name": c["name"],
                "cluster": c["context"].get("cluster"),
                "namespace": c["context"].get("namespace", "default"),
                "user": c["context"].get("user"),
            }
            for c in contexts
        ],
    }
    return yaml.safe_dump(payload, sort_keys=False)
