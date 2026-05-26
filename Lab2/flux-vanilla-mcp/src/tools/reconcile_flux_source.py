"""Trigger reconciliation of a Flux source object.

Bumps the `reconcile.fluxcd.io/requestedAt` annotation, then polls
`status.lastHandledReconcileAt` until the source controller picks it up
(or the configured timeout expires).
"""

from __future__ import annotations

import yaml
from kubernetes.client.rest import ApiException
from mcp.types import ToolAnnotations

from core.audit import audit_scope
from core.flux_actions import (
    SOURCE_KINDS,
    FluxActionError,
    patch_reconcile_annotation,
    poll_reconciled,
    resolve_gvk,
)
from core.scopes import check_scope, register_scope
from core.server import mcp

TOOL_NAME = "reconcile_flux_source"
register_scope(TOOL_NAME, read_only=False, in_cluster=True)


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Reconcile Flux source",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
    ),
)
def reconcile_flux_source(kind: str, name: str, namespace: str) -> str:
    """Trigger a Flux source reconciliation by patching its reconcile annotation.

    Args:
        kind: One of GitRepository, OCIRepository, HelmRepository, Bucket, HelmChart.
        name: Resource name.
        namespace: Resource namespace.
    """
    with audit_scope(TOOL_NAME, kind=kind, name=name, namespace=namespace) as audit:
        check_scope(TOOL_NAME)

        if kind not in SOURCE_KINDS:
            audit.fail(f"invalid kind {kind!r}")
            return yaml.safe_dump(
                {
                    "error": f"{kind!r} is not a Flux source kind",
                    "validKinds": sorted(SOURCE_KINDS),
                }
            )

        try:
            api_version, _ = resolve_gvk(kind)
            ts = patch_reconcile_annotation(api_version, kind, name, namespace)
        except FluxActionError as exc:
            audit.fail(str(exc))
            return yaml.safe_dump({"error": str(exc)})
        except ApiException as exc:
            audit.fail(f"{exc.status} {exc.reason}")
            return yaml.safe_dump(
                {
                    "error": f"{exc.status} {exc.reason}",
                    "body": getattr(exc, "body", None),
                }
            )

        result = poll_reconciled(api_version, kind, name, namespace, ts)
        if not result.get("ok"):
            audit.fail(result.get("message") or "reconcile not ready")
        return yaml.safe_dump(
            {"kind": kind, "name": name, "namespace": namespace, **result},
            sort_keys=False,
        )
