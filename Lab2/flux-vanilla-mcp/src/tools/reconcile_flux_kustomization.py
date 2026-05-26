"""Trigger reconciliation of a Flux Kustomization.

Optionally reconciles the upstream source (GitRepository / OCIRepository /
Bucket) first so the Kustomization sees the freshest revision.
"""

from __future__ import annotations

import yaml
from kubernetes.client.rest import ApiException
from mcp.types import ToolAnnotations

from core.audit import audit_scope
from core.flux_actions import (
    FluxActionError,
    extract_kustomization_source,
    get_object,
    patch_reconcile_annotation,
    poll_reconciled,
    resolve_gvk,
)
from core.flux_types import KUSTOMIZATION_GVK
from core.scopes import check_scope, register_scope
from core.server import mcp

TOOL_NAME = "reconcile_flux_kustomization"
register_scope(TOOL_NAME, read_only=False, in_cluster=True)


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Reconcile Flux Kustomization",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
    ),
)
def reconcile_flux_kustomization(
    name: str, namespace: str, withSource: bool = False  # noqa: N803
) -> str:
    """Bump the reconcile annotation on a Kustomization, polling until handled.

    Args:
        name: Kustomization name.
        namespace: Kustomization namespace.
        withSource: If true, reconcile the upstream sourceRef first.
    """
    api_version, kind = KUSTOMIZATION_GVK
    with audit_scope(TOOL_NAME, kind=kind, name=name, namespace=namespace) as audit:
        check_scope(TOOL_NAME)
        payload: dict = {"kind": kind, "name": name, "namespace": namespace}

        try:
            if withSource:
                obj = get_object(api_version, kind, name, namespace)
                ref = extract_kustomization_source(obj)
                if ref is None:
                    payload["source"] = {
                        "error": "no spec.sourceRef on this Kustomization"
                    }
                else:
                    src_kind, src_name, src_ns = ref
                    src_api_version, _ = resolve_gvk(src_kind)
                    src_ts = patch_reconcile_annotation(
                        src_api_version, src_kind, src_name, src_ns
                    )
                    src_result = poll_reconciled(
                        src_api_version, src_kind, src_name, src_ns, src_ts
                    )
                    payload["source"] = {
                        "kind": src_kind,
                        "name": src_name,
                        "namespace": src_ns,
                        **src_result,
                    }

            ts = patch_reconcile_annotation(api_version, kind, name, namespace)
        except FluxActionError as exc:
            audit.fail(str(exc))
            return yaml.safe_dump({"error": str(exc), **payload})
        except ApiException as exc:
            audit.fail(f"{exc.status} {exc.reason}")
            return yaml.safe_dump(
                {
                    "error": f"{exc.status} {exc.reason}",
                    "body": getattr(exc, "body", None),
                    **payload,
                }
            )

        result = poll_reconciled(api_version, kind, name, namespace, ts)
        if not result.get("ok"):
            audit.fail(result.get("message") or "reconcile not ready")
        payload.update(result)
        return yaml.safe_dump(payload, sort_keys=False)
