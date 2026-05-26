"""Fetch Kubernetes resources by GVK.

Supports any GVK (built-in or CRD). Uses the dynamic client for discovery
so the LLM can pass `apiVersion` + `kind` as a string pair and we resolve
the REST path automatically.

Output: a YAML document (or multi-doc list) with managedFields stripped
and Secret data masked when --mask-secrets is on.
"""

from __future__ import annotations

import yaml
from kubernetes.client.rest import ApiException
from mcp.types import ToolAnnotations

from core.config import get_config
from core.k8s_client import get_dynamic_client
from core.scopes import check_scope, register_scope
from core.secrets import mask
from core.server import mcp

TOOL_NAME = "get_kubernetes_resources"
register_scope(TOOL_NAME, read_only=True, in_cluster=True)

MAX_LIMIT = 200


def _strip_noise(obj: dict) -> dict:
    md = obj.get("metadata")
    if isinstance(md, dict):
        md.pop("managedFields", None)
        # These are server-set and rarely interesting for the LLM.
        md.pop("generation", None)
        md.pop("resourceVersion", None)
        md.pop("uid", None)
        md.pop("selfLink", None)
    return obj


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Get Kubernetes resources",
        readOnlyHint=True,
    ),
)
def get_kubernetes_resources(
    apiVersion: str,
    kind: str,
    name: str | None = None,
    namespace: str | None = None,
    labelSelector: str | None = None,
    limit: int = 50,
) -> str:
    """Get or list Kubernetes resources of any kind, including CRDs.

    Args:
        apiVersion: e.g. "v1", "apps/v1", "kustomize.toolkit.fluxcd.io/v1".
        kind: PascalCase kind, e.g. "Pod", "Deployment", "Kustomization".
        name: If set, fetch a single resource. Otherwise list.
        namespace: Required for namespaced resources when fetching by name.
        labelSelector: Standard label selector string (list mode only).
        limit: Max items in list mode (capped at 200).
    """
    check_scope(TOOL_NAME)
    cfg = get_config()
    dyn = get_dynamic_client()

    try:
        resource = dyn.resources.get(api_version=apiVersion, kind=kind)
    except Exception as e:
        return yaml.safe_dump(
            {"error": f"discovery failed for {apiVersion}/{kind}: {e}"}
        )

    try:
        if name:
            obj = resource.get(name=name, namespace=namespace).to_dict()
            cleaned = _strip_noise(obj)
            if cfg.mask_secrets:
                cleaned = mask(cleaned)
            return yaml.safe_dump(cleaned, sort_keys=False)

        capped = min(limit, MAX_LIMIT)
        result = resource.get(
            namespace=namespace,
            label_selector=labelSelector,
            limit=capped,
        )
        items = [_strip_noise(i.to_dict()) for i in result.items]
        if cfg.mask_secrets:
            items = [mask(i) for i in items]

        if not items:
            return yaml.safe_dump(
                {
                    "items": [],
                    "message": (
                        f"no {kind} found"
                        + (f" in namespace {namespace!r}" if namespace else "")
                    ),
                }
            )
        return yaml.safe_dump_all(items, sort_keys=False)
    except ApiException as e:
        return yaml.safe_dump(
            {
                "error": f"{e.status} {e.reason}",
                "body": getattr(e, "body", None),
            }
        )
