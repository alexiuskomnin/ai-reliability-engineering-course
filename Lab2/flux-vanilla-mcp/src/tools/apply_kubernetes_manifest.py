"""Server-side apply a Kubernetes manifest.

Accepts a single document or a multi-doc YAML string. Each document is
applied via the dynamic client with content-type
`application/apply-patch+yaml` and fieldManager=`flux-vanilla-mcp`, so
the assistant can iteratively reshape the same resource without
trampling foreign fields.
"""

from __future__ import annotations

import time

import yaml
from kubernetes.client.rest import ApiException
from mcp.types import ToolAnnotations

from core.audit import emit as audit_emit
from core.k8s_client import get_dynamic_client
from core.scopes import ScopeError, check_scope, register_scope
from core.server import mcp

TOOL_NAME = "apply_kubernetes_manifest"
register_scope(TOOL_NAME, read_only=False, in_cluster=True)

FIELD_MANAGER = "flux-vanilla-mcp"


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Apply Kubernetes manifest",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
    ),
)
def apply_kubernetes_manifest(manifest: str, force: bool = False) -> str:
    """Server-side apply a YAML manifest (single or multi-doc).

    Args:
        manifest: YAML text. Multi-doc with `---` separators is supported.
        force: Pass through as force-conflicts to take ownership of fields
            owned by another fieldManager.

    Returns:
        YAML doc with a per-resource list of applied objects (or errors).
    """
    try:
        check_scope(TOOL_NAME)
    except ScopeError as exc:
        audit_emit(
            TOOL_NAME,
            duration_ms=0,
            outcome="denied",
            error=str(exc),
        )
        raise

    try:
        docs = [d for d in yaml.safe_load_all(manifest) if d]
    except yaml.YAMLError as exc:
        return yaml.safe_dump({"error": f"invalid YAML: {exc}"})

    if not docs:
        return yaml.safe_dump({"error": "manifest contained no documents"})

    dyn = get_dynamic_client()
    results: list[dict] = []
    for doc in docs:
        results.append(_apply_one(dyn, doc, force=force))

    return yaml.safe_dump({"applied": results}, sort_keys=False)


def _apply_one(dyn, doc: dict, *, force: bool) -> dict:
    api_version = doc.get("apiVersion")
    kind = doc.get("kind")
    meta = doc.get("metadata") or {}
    name = meta.get("name")
    namespace = meta.get("namespace")
    started = time.monotonic()

    def _ms() -> int:
        return int((time.monotonic() - started) * 1000)

    if not (api_version and kind and name):
        audit_emit(
            TOOL_NAME,
            duration_ms=_ms(),
            outcome="error",
            kind=kind,
            name=name,
            namespace=namespace,
            error="manifest missing apiVersion/kind/metadata.name",
        )
        return {
            "error": "manifest missing apiVersion/kind/metadata.name",
            "apiVersion": api_version,
            "kind": kind,
            "name": name,
        }

    try:
        resource = dyn.resources.get(api_version=api_version, kind=kind)
    except Exception as exc:
        audit_emit(
            TOOL_NAME,
            duration_ms=_ms(),
            outcome="error",
            kind=kind,
            name=name,
            namespace=namespace,
            error=f"discovery failed: {exc}",
        )
        return {
            "apiVersion": api_version,
            "kind": kind,
            "name": name,
            "namespace": namespace,
            "error": f"discovery failed: {exc}",
        }

    try:
        applied = dyn.server_side_apply(
            resource,
            body=doc,
            name=name,
            namespace=namespace,
            force_conflicts=force,
            field_manager=FIELD_MANAGER,
        )
    except ApiException as exc:
        audit_emit(
            TOOL_NAME,
            duration_ms=_ms(),
            outcome="error",
            kind=kind,
            name=name,
            namespace=namespace,
            error=f"{exc.status} {exc.reason}",
        )
        return {
            "apiVersion": api_version,
            "kind": kind,
            "name": name,
            "namespace": namespace,
            "error": f"{exc.status} {exc.reason}",
            "body": getattr(exc, "body", None),
        }

    out = applied.to_dict() if hasattr(applied, "to_dict") else applied
    rv = None
    if isinstance(out, dict):
        rv = (out.get("metadata") or {}).get("resourceVersion")
    audit_emit(
        TOOL_NAME,
        duration_ms=_ms(),
        outcome="ok",
        kind=kind,
        name=name,
        namespace=namespace,
    )
    return {
        "apiVersion": api_version,
        "kind": kind,
        "name": name,
        "namespace": namespace,
        "resourceVersion": rv,
        "ok": True,
    }
