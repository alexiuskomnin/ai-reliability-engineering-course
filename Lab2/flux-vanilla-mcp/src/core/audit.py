"""Audit logging for write tools.

Emits one JSON line on stderr per write call. Schema (per docs/SPEC.md §7.4):

    {
      "ts":         RFC3339 UTC timestamp,
      "tool":       tool name,
      "user":       SA path in-cluster, or kubeconfig user locally,
      "context":    "in-cluster" / kubeconfig context name,
      "kind":       resource kind (may be null for set_kubeconfig_context, etc.),
      "name":       resource name (may be null),
      "namespace":  resource namespace (may be null for cluster-scoped),
      "durationMs": elapsed time in ms,
      "outcome":    "ok" | "error" | "denied",
      "error":      reason string when outcome != "ok"
    }

The line is unconditional — write tools must call this so the operator
keeps a forensic trail even when --mask-secrets hides the YAML payload.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import get_config
from .scopes import ScopeError

_IN_CLUSTER_NS_FILE = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")


@dataclass
class _RecordState:
    outcome: str = "ok"
    error: str | None = None

    def fail(self, reason: str, *, outcome: str = "error") -> None:
        self.outcome = outcome
        self.error = reason


def _now_rfc3339() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _identity() -> tuple[str, str]:
    """Return (user, context) for the current runtime.

    Best-effort: in-cluster we infer the SA path from the projected
    namespace file; locally we read the active kubeconfig context.
    """
    cfg = get_config()
    if cfg.in_cluster:
        try:
            ns = _IN_CLUSTER_NS_FILE.read_text().strip() or "default"
        except OSError:
            ns = "default"
        # The pod's SA name isn't exposed inside the container without parsing
        # the JWT, so the operator pins it via env if they want it accurate.
        # Default to the deployment SA name configured in deploy/rbac.yaml.
        from os import getenv

        sa = getenv("POD_SERVICE_ACCOUNT", "flux-vanilla-mcp")
        return f"system:serviceaccount:{ns}:{sa}", "in-cluster"

    # Local: derive from kubeconfig.
    try:
        from kubernetes import config as kubeconfig

        contexts, active = kubeconfig.list_kube_config_contexts(
            config_file=cfg.kubeconfig_path
        )
    except Exception:
        return "unknown", "unknown"

    ctx_name = cfg.kube_context_override or (active or {}).get("name") or "unknown"
    user = "unknown"
    for c in contexts:
        if c.get("name") == ctx_name:
            user = c.get("context", {}).get("user") or "unknown"
            break
    return user, ctx_name


def emit(
    tool: str,
    *,
    duration_ms: int,
    outcome: str,
    kind: str | None = None,
    name: str | None = None,
    namespace: str | None = None,
    error: str | None = None,
) -> None:
    """Write one audit JSON line to stderr."""
    user, context = _identity()
    record = {
        "ts": _now_rfc3339(),
        "tool": tool,
        "user": user,
        "context": context,
        "kind": kind,
        "name": name,
        "namespace": namespace,
        "durationMs": duration_ms,
        "outcome": outcome,
    }
    if error is not None:
        record["error"] = error
    print(json.dumps(record, separators=(",", ":")), file=sys.stderr, flush=True)


@contextmanager
def audit_scope(
    tool: str,
    *,
    kind: str | None = None,
    name: str | None = None,
    namespace: str | None = None,
) -> Iterator[_RecordState]:
    """Wrap a write handler; emit one audit line on exit.

    Usage:
        with audit_scope(TOOL_NAME, kind=kind, name=name, namespace=ns) as audit:
            check_scope(TOOL_NAME)   # ScopeError -> outcome=denied
            ...
            audit.fail("404 NotFound")  # marks outcome=error, still emits
            return yaml.safe_dump(...)
    """
    state = _RecordState()
    started = time.monotonic()
    try:
        yield state
    except ScopeError as exc:
        state.fail(str(exc), outcome="denied")
        raise
    except Exception as exc:
        state.fail(repr(exc), outcome="error")
        raise
    finally:
        emit(
            tool,
            duration_ms=int((time.monotonic() - started) * 1000),
            outcome=state.outcome,
            kind=kind,
            name=name,
            namespace=namespace,
            error=state.error,
        )
