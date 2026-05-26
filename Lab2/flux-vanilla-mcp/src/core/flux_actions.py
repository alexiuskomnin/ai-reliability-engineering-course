"""Helpers for Flux annotation-patch operations.

Implements the same primitive the `flux` CLI uses: bump the
`reconcile.fluxcd.io/requestedAt` annotation (reconcile) or toggle
`spec.suspend` (suspend/resume). Polls `status.lastHandledReconcileAt`
for up to RuntimeConfig.timeout_seconds so the caller gets a real
outcome instead of fire-and-forget.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from kubernetes.client.rest import ApiException

from .config import get_config
from .flux_types import (
    HELMRELEASE_GVK,
    KUSTOMIZATION_GVK,
    RECONCILE_ANNOTATION,
    SOURCE_GVKS,
)
from .k8s_client import get_dynamic_client


class FluxActionError(RuntimeError):
    """Raised for input errors (unknown kind, etc.) before any cluster call."""


# kind -> apiVersion map covering every kind we patch.
_KIND_TO_API_VERSION: dict[str, str] = {
    KUSTOMIZATION_GVK[1]: KUSTOMIZATION_GVK[0],
    HELMRELEASE_GVK[1]: HELMRELEASE_GVK[0],
    **{kind: api_version for api_version, kind in SOURCE_GVKS},
}

SOURCE_KINDS = {kind for _, kind in SOURCE_GVKS}
SUSPENDABLE_KINDS = SOURCE_KINDS | {KUSTOMIZATION_GVK[1], HELMRELEASE_GVK[1]}


def resolve_gvk(kind: str) -> tuple[str, str]:
    """Return (apiVersion, kind) for a known Flux kind. Raises FluxActionError."""
    api_version = _KIND_TO_API_VERSION.get(kind)
    if api_version is None:
        raise FluxActionError(
            f"unknown Flux kind {kind!r} — known kinds: "
            + ", ".join(sorted(_KIND_TO_API_VERSION))
        )
    return api_version, kind


def now_rfc3339() -> str:
    """RFC3339 UTC timestamp with second precision (matches `flux` CLI)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def patch_reconcile_annotation(
    api_version: str, kind: str, name: str, namespace: str
) -> str:
    """Bump the reconcile annotation on `<kind>/<name>` in `<namespace>`.

    Returns the timestamp written so callers can poll for
    status.lastHandledReconcileAt to catch up.
    """
    ts = now_rfc3339()
    dyn = get_dynamic_client()
    resource = dyn.resources.get(api_version=api_version, kind=kind)
    body = {"metadata": {"annotations": {RECONCILE_ANNOTATION: ts}}}
    resource.patch(
        body=body,
        name=name,
        namespace=namespace,
        content_type="application/merge-patch+json",
    )
    return ts


def patch_suspend(
    api_version: str, kind: str, name: str, namespace: str, *, suspend: bool
) -> None:
    """Toggle `spec.suspend`."""
    dyn = get_dynamic_client()
    resource = dyn.resources.get(api_version=api_version, kind=kind)
    resource.patch(
        body={"spec": {"suspend": suspend}},
        name=name,
        namespace=namespace,
        content_type="application/merge-patch+json",
    )


def get_object(
    api_version: str, kind: str, name: str, namespace: str
) -> dict:
    """Read the object's current dict representation."""
    dyn = get_dynamic_client()
    resource = dyn.resources.get(api_version=api_version, kind=kind)
    return resource.get(name=name, namespace=namespace).to_dict()


def poll_reconciled(
    api_version: str,
    kind: str,
    name: str,
    namespace: str,
    since_ts: str,
    *,
    interval: float = 1.5,
) -> dict:
    """Poll until `status.lastHandledReconcileAt` >= since_ts or timeout.

    Returns a dict summarising the outcome — see `_summarize_status`.
    Never raises on transient API errors; surfaces them in the result.
    """
    deadline = time.monotonic() + get_config().timeout_seconds
    last: dict = {}
    while time.monotonic() < deadline:
        try:
            obj = get_object(api_version, kind, name, namespace)
        except ApiException as exc:
            return {
                "ok": False,
                "phase": "polling",
                "error": f"{exc.status} {exc.reason}",
            }
        last = _summarize_status(obj, since_ts)
        if last.get("handled"):
            return last
        time.sleep(interval)
    last["timedOut"] = True
    return last


def extract_kustomization_source(obj: dict) -> tuple[str, str, str] | None:
    """Return (kind, name, namespace) of a Kustomization's sourceRef, or None."""
    spec = obj.get("spec") or {}
    ref = spec.get("sourceRef") or {}
    kind = ref.get("kind")
    name = ref.get("name")
    if not (kind and name):
        return None
    ns = ref.get("namespace") or (obj.get("metadata") or {}).get("namespace")
    return kind, name, ns


def extract_helmrelease_source(obj: dict) -> tuple[str, str, str] | None:
    """Return the underlying source (kind, name, namespace) for a HelmRelease.

    Prefers v2's `spec.chartRef` (direct OCI/HelmChart ref). Falls back to
    the legacy template style `spec.chart.spec.sourceRef`.
    """
    spec = obj.get("spec") or {}
    self_ns = (obj.get("metadata") or {}).get("namespace")

    chart_ref = spec.get("chartRef") or {}
    if chart_ref.get("kind") and chart_ref.get("name"):
        ns = chart_ref.get("namespace") or self_ns
        return chart_ref["kind"], chart_ref["name"], ns

    chart = spec.get("chart") or {}
    chart_spec = chart.get("spec") or {}
    source_ref = chart_spec.get("sourceRef") or {}
    if source_ref.get("kind") and source_ref.get("name"):
        return (
            source_ref["kind"],
            source_ref["name"],
            source_ref.get("namespace") or self_ns,
        )
    return None


def _summarize_status(obj: dict, since_ts: str) -> dict:
    status = obj.get("status") or {}
    handled_at = status.get("lastHandledReconcileAt")
    ready: bool | None = None
    message: str | None = None
    for cond in status.get("conditions") or []:
        if cond.get("type") == "Ready":
            ready = cond.get("status") == "True"
            message = cond.get("message")
            break
    handled = bool(handled_at) and handled_at >= since_ts
    return {
        "ok": ready is True,
        "ready": ready,
        "message": message,
        "lastHandledReconcileAt": handled_at,
        "requestedAt": since_ts,
        "handled": handled,
        "observedGeneration": status.get("observedGeneration"),
    }
