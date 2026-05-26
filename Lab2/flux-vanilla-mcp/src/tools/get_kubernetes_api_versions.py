"""List Kubernetes CRDs with their preferred apiVersion per kind.

Useful as a precursor to `get_kubernetes_resources` so the assistant can
discover what custom kinds are available on the cluster and which
apiVersion string to pass.
"""

from __future__ import annotations

import yaml
from kubernetes import client
from kubernetes.client.rest import ApiException
from mcp.types import ToolAnnotations

from core.k8s_client import get_api_client
from core.scopes import check_scope, register_scope
from core.server import mcp

TOOL_NAME = "get_kubernetes_api_versions"
register_scope(TOOL_NAME, read_only=True, in_cluster=True)


def _preferred_version(crd) -> str | None:
    """Pick the storage version if served, else the first served version."""
    served = [v for v in crd.spec.versions if v.served]
    if not served:
        return None
    for v in served:
        if v.storage:
            return v.name
    return served[0].name


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Get Kubernetes API versions",
        readOnlyHint=True,
    ),
)
def get_kubernetes_api_versions() -> str:
    """List all CustomResourceDefinitions installed on the cluster with their
    preferred (storage, served) apiVersion, kind, plural, and scope.

    Returns:
        YAML document with a `crds` list. Each entry has
        `apiVersion` (group/version), `kind`, `plural`, and `scope`.
    """
    check_scope(TOOL_NAME)
    apiext = client.ApiextensionsV1Api(get_api_client())

    try:
        crds = apiext.list_custom_resource_definition()
    except ApiException as exc:
        return yaml.safe_dump(
            {"error": f"{exc.status} {exc.reason}", "body": getattr(exc, "body", None)}
        )

    entries: list[dict] = []
    for crd in crds.items:
        version = _preferred_version(crd)
        if version is None:
            continue
        entries.append(
            {
                "apiVersion": f"{crd.spec.group}/{version}",
                "kind": crd.spec.names.kind,
                "plural": crd.spec.names.plural,
                "scope": crd.spec.scope,
            }
        )
    entries.sort(key=lambda e: (e["apiVersion"], e["kind"]))

    return yaml.safe_dump({"crds": entries}, sort_keys=False)
