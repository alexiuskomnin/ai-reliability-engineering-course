"""Resume Flux reconciliation by setting `spec.suspend: false`."""

from __future__ import annotations

import yaml
from kubernetes.client.rest import ApiException
from mcp.types import ToolAnnotations

from core.audit import audit_scope
from core.flux_actions import (
    SUSPENDABLE_KINDS,
    FluxActionError,
    patch_suspend,
    resolve_gvk,
)
from core.scopes import check_scope, register_scope
from core.server import mcp

TOOL_NAME = "resume_flux_reconciliation"
register_scope(TOOL_NAME, read_only=False, in_cluster=True)


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Resume Flux reconciliation",
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=True,
    ),
)
def resume_flux_reconciliation(kind: str, name: str, namespace: str) -> str:
    """Resume Flux reconciliation for a resource by setting spec.suspend=false.

    Args:
        kind: One of GitRepository, OCIRepository, HelmRepository, Bucket,
            HelmChart, Kustomization, HelmRelease.
        name: Resource name.
        namespace: Resource namespace.
    """
    with audit_scope(TOOL_NAME, kind=kind, name=name, namespace=namespace) as audit:
        check_scope(TOOL_NAME)

        if kind not in SUSPENDABLE_KINDS:
            audit.fail(f"invalid kind {kind!r}")
            return yaml.safe_dump(
                {
                    "error": f"{kind!r} is not a suspendable Flux kind",
                    "validKinds": sorted(SUSPENDABLE_KINDS),
                }
            )

        try:
            api_version, _ = resolve_gvk(kind)
            patch_suspend(api_version, kind, name, namespace, suspend=False)
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

        return yaml.safe_dump(
            {
                "kind": kind,
                "name": name,
                "namespace": namespace,
                "suspend": False,
                "message": "reconciliation resumed",
            },
            sort_keys=False,
        )
