"""Report on Flux CD installation state.

Returns:
  * cluster Kubernetes version
  * controllers running in the flux-system namespace
  * installed Flux CRDs (group, kind, preferred version, scope)
  * counts of Kustomizations and HelmReleases (total / ready / failing)
"""

from __future__ import annotations

import yaml
from kubernetes import client
from kubernetes.client.rest import ApiException
from mcp.types import ToolAnnotations

from core.flux_types import (
    FLUX_GROUP_SUFFIX,
    FLUX_SYSTEM_NAMESPACE,
    HELMRELEASE_GVK,
    KUSTOMIZATION_GVK,
)
from core.k8s_client import get_api_client, get_dynamic_client
from core.scopes import check_scope, register_scope
from core.server import mcp

TOOL_NAME = "get_flux_status"
register_scope(TOOL_NAME, read_only=True, in_cluster=True)


def _cluster_version(api: client.ApiClient) -> str:
    try:
        v = client.VersionApi(api).get_code()
        return v.git_version or f"{v.major}.{v.minor}"
    except ApiException as e:
        return f"error: {e.reason}"


def _controllers(api: client.ApiClient) -> list[dict] | dict:
    apps = client.AppsV1Api(api)
    try:
        deps = apps.list_namespaced_deployment(
            namespace=FLUX_SYSTEM_NAMESPACE,
            label_selector="app.kubernetes.io/part-of=flux",
        )
    except ApiException as e:
        if e.status == 404:
            return {"error": f"namespace {FLUX_SYSTEM_NAMESPACE!r} not found"}
        return {"error": f"{e.status} {e.reason}"}

    if not deps.items:
        # Fall back to namespace listing without the label (older installs).
        deps = apps.list_namespaced_deployment(namespace=FLUX_SYSTEM_NAMESPACE)

    out = []
    for d in deps.items:
        containers = (d.spec.template.spec.containers or []) if d.spec else []
        out.append(
            {
                "name": d.metadata.name,
                "image": containers[0].image if containers else None,
                "replicas": d.status.replicas or 0,
                "ready": d.status.ready_replicas or 0,
                "available": (d.status.available_replicas or 0)
                == (d.status.replicas or 0)
                and (d.status.replicas or 0) > 0,
            }
        )
    return out


def _flux_crds(api: client.ApiClient) -> list[dict]:
    apiext = client.ApiextensionsV1Api(api)
    out: list[dict] = []
    try:
        crds = apiext.list_custom_resource_definition()
    except ApiException as e:
        return [{"error": f"{e.status} {e.reason}"}]

    for crd in crds.items:
        group = crd.spec.group
        if not group.endswith(FLUX_GROUP_SUFFIX):
            continue
        preferred = None
        for v in crd.spec.versions:
            if not v.served:
                continue
            preferred = v.name
            if v.storage:
                break
        out.append(
            {
                "group": group,
                "kind": crd.spec.names.kind,
                "preferredVersion": preferred,
                "scope": crd.spec.scope,
            }
        )
    out.sort(key=lambda x: (x["group"], x["kind"]))
    return out


def _is_ready(item: dict) -> bool | None:
    """Look at status.conditions[type=Ready].status."""
    status = item.get("status") or {}
    for cond in status.get("conditions") or []:
        if cond.get("type") == "Ready":
            return cond.get("status") == "True"
    return None


def _summary(dyn, gvk: tuple[str, str]) -> dict:
    api_version, kind = gvk
    try:
        resource = dyn.resources.get(api_version=api_version, kind=kind)
    except Exception as e:
        return {"error": f"discovery failed: {e}"}

    try:
        items = resource.get().items
    except ApiException as e:
        return {"error": f"{e.status} {e.reason}"}

    total = len(items)
    ready = sum(1 for i in items if _is_ready(i.to_dict()) is True)
    failing = sum(1 for i in items if _is_ready(i.to_dict()) is False)
    return {"total": total, "ready": ready, "failing": failing}


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Get Flux status",
        readOnlyHint=True,
    ),
)
def get_flux_status() -> str:
    """Report on the Flux CD installation: controllers, CRDs, and resource health.

    Returns YAML with `cluster`, `controllers`, `crds`, and `summary` sections.
    """
    check_scope(TOOL_NAME)
    api = get_api_client()
    dyn = get_dynamic_client()

    payload = {
        "cluster": {"version": _cluster_version(api)},
        "controllers": _controllers(api),
        "crds": _flux_crds(api),
        "summary": {
            "kustomizations": _summary(dyn, KUSTOMIZATION_GVK),
            "helmReleases": _summary(dyn, HELMRELEASE_GVK),
        },
    }
    return yaml.safe_dump(payload, sort_keys=False)
