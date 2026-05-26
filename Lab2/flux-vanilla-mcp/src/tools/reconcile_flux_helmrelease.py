"""Trigger reconciliation of a Flux HelmRelease.

Optionally reconciles the upstream source first. Handles both v2 styles:
modern `spec.chartRef` (HelmChart/OCIRepository) and legacy
`spec.chart.spec.sourceRef` (template that produces a HelmChart).
"""

from __future__ import annotations

import yaml
from kubernetes.client.rest import ApiException
from mcp.types import ToolAnnotations

from core.audit import audit_scope
from core.flux_actions import (
    FluxActionError,
    extract_helmrelease_source,
    get_object,
    patch_reconcile_annotation,
    poll_reconciled,
    resolve_gvk,
)
from core.flux_types import HELMRELEASE_GVK
from core.scopes import check_scope, register_scope
from core.server import mcp

TOOL_NAME = "reconcile_flux_helmrelease"
register_scope(TOOL_NAME, read_only=False, in_cluster=True)


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Reconcile Flux HelmRelease",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
    ),
)
def reconcile_flux_helmrelease(
    name: str, namespace: str, withSource: bool = False  # noqa: N803
) -> str:
    """Bump the reconcile annotation on a HelmRelease, polling until handled.

    Args:
        name: HelmRelease name.
        namespace: HelmRelease namespace.
        withSource: If true, reconcile the underlying chart source first.
    """
    api_version, kind = HELMRELEASE_GVK
    with audit_scope(TOOL_NAME, kind=kind, name=name, namespace=namespace) as audit:
        check_scope(TOOL_NAME)
        payload: dict = {"kind": kind, "name": name, "namespace": namespace}

        try:
            if withSource:
                obj = get_object(api_version, kind, name, namespace)
                ref = extract_helmrelease_source(obj)
                if ref is None:
                    payload["source"] = {
                        "error": "no chart source on this HelmRelease"
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
