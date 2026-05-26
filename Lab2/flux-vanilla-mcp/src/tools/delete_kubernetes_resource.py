"""Delete a Kubernetes resource by GVK + name.

Refuses cluster-blast operations (`Namespace`, `CustomResourceDefinition`,
and anything inside `kube-system`) unless the server was launched with
`--allow-destructive`.
"""

from __future__ import annotations

import yaml
from kubernetes.client.rest import ApiException
from mcp.types import ToolAnnotations

from core.audit import audit_scope
from core.config import get_config
from core.k8s_client import get_dynamic_client
from core.scopes import check_scope, register_scope
from core.server import mcp

TOOL_NAME = "delete_kubernetes_resource"
register_scope(TOOL_NAME, read_only=False, in_cluster=True)

PROTECTED_KINDS = {"Namespace", "CustomResourceDefinition"}
PROTECTED_NAMESPACES = {"kube-system"}


@mcp.tool(
    name=TOOL_NAME,
    annotations=ToolAnnotations(
        title="Delete Kubernetes resource",
        readOnlyHint=False,
        destructiveHint=True,
        idempotentHint=False,
    ),
)
def delete_kubernetes_resource(
    apiVersion: str,  # noqa: N803
    kind: str,
    name: str,
    namespace: str | None = None,
) -> str:
    """Delete a single Kubernetes resource.

    Args:
        apiVersion: e.g. "v1", "apps/v1", "kustomize.toolkit.fluxcd.io/v1".
        kind: PascalCase kind.
        name: Resource name.
        namespace: Required for namespaced resources.
    """
    with audit_scope(TOOL_NAME, kind=kind, name=name, namespace=namespace) as audit:
        check_scope(TOOL_NAME)
        cfg = get_config()

        if not cfg.allow_destructive:
            if kind in PROTECTED_KINDS:
                audit.fail(f"protected kind {kind!r}", outcome="denied")
                return yaml.safe_dump(
                    {
                        "error": (
                            f"refusing to delete {kind} — start the server with "
                            f"--allow-destructive to permit cluster-scoped deletes"
                        )
                    }
                )
            if namespace in PROTECTED_NAMESPACES:
                audit.fail(
                    f"protected namespace {namespace!r}", outcome="denied"
                )
                return yaml.safe_dump(
                    {
                        "error": (
                            f"refusing to delete resources in {namespace!r} — "
                            f"start the server with --allow-destructive to override"
                        )
                    }
                )

        dyn = get_dynamic_client()
        try:
            resource = dyn.resources.get(api_version=apiVersion, kind=kind)
        except Exception as exc:
            audit.fail(f"discovery failed: {exc}")
            return yaml.safe_dump(
                {"error": f"discovery failed for {apiVersion}/{kind}: {exc}"}
            )

        try:
            resource.delete(name=name, namespace=namespace)
        except ApiException as exc:
            if exc.status == 404:
                # 404 on delete is benign — record as ok with a note.
                return yaml.safe_dump(
                    {
                        "apiVersion": apiVersion,
                        "kind": kind,
                        "name": name,
                        "namespace": namespace,
                        "message": "resource not found (already deleted?)",
                    }
                )
            audit.fail(f"{exc.status} {exc.reason}")
            return yaml.safe_dump(
                {
                    "apiVersion": apiVersion,
                    "kind": kind,
                    "name": name,
                    "namespace": namespace,
                    "error": f"{exc.status} {exc.reason}",
                    "body": getattr(exc, "body", None),
                }
            )

        return yaml.safe_dump(
            {
                "apiVersion": apiVersion,
                "kind": kind,
                "name": name,
                "namespace": namespace,
                "deleted": True,
            },
            sort_keys=False,
        )
