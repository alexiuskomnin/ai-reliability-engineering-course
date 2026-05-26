"""MCP prompt: walk a failing Flux Kustomization to root cause.

Returns a single user message scripting the diagnostic chain:
Kustomization → sourceRef → events → kustomize-controller logs.
"""

from __future__ import annotations

from core.server import mcp


@mcp.prompt(
    name="debug_flux_kustomization",
    title="Debug Flux Kustomization",
    description=(
        "Walk a Kustomization through its dependency chain to find the "
        "first failing step (sourceRef, events, controller logs)."
    ),
)
def debug_flux_kustomization(name: str, namespace: str) -> str:
    """Return the diagnostic checklist as a single user message.

    Args:
        name: Kustomization name.
        namespace: Kustomization namespace.
    """
    return (
        f"Diagnose Kustomization `{name}` in namespace `{namespace}` and "
        f"surface the root cause. Walk the chain in this exact order — stop "
        f"as soon as you find the first failure.\n\n"
        f"1. **Fetch the Kustomization itself.**\n"
        f"   - Call `get_kubernetes_resources` with "
        f"`apiVersion=kustomize.toolkit.fluxcd.io/v1`, `kind=Kustomization`, "
        f"`name={name}`, `namespace={namespace}`.\n"
        f"   - Inspect `status.conditions[type=Ready].status`, "
        f"`status.lastAppliedRevision`, `status.inventory`.\n"
        f"   - Note `spec.sourceRef`, `spec.path`, `spec.dependsOn`.\n\n"
        f"2. **Verify each `spec.dependsOn` entry.**\n"
        f"   - For each one, fetch the referenced Kustomization and confirm it "
        f"is Ready=True. If not, recurse this entire prompt against the "
        f"dependency before continuing.\n\n"
        f"3. **Fetch the upstream source** (from `spec.sourceRef`).\n"
        f"   - Resolve its kind/apiVersion (GitRepository, OCIRepository, "
        f"Bucket — use `get_kubernetes_api_versions` if unsure).\n"
        f"   - Inspect `status.conditions[type=Ready]` and "
        f"`status.artifact.revision`.\n"
        f"   - If the source is failing, the Kustomization can't apply — stop "
        f"and report the source error.\n\n"
        f"4. **List recent Events in `{namespace}`** scoped to the "
        f"Kustomization.\n"
        f"   - Call `get_kubernetes_resources` with `apiVersion=v1`, "
        f"`kind=Event`, `namespace={namespace}`. Filter on "
        f"`involvedObject.name={name}` and `involvedObject.kind=Kustomization`.\n"
        f"   - Pay attention to `reason` (`HealthCheckFailed`, "
        f"`ReconciliationFailed`, `BuildFailed`).\n\n"
        f"5. **Tail kustomize-controller logs.**\n"
        f"   - Call `get_kubernetes_logs` for the kustomize-controller pod in "
        f"`flux-system` (list pods first if you don't know the name). Use "
        f"`tail_lines=200`, no `previous`.\n"
        f"   - Grep mentally for `{name}` and `{namespace}` to find the "
        f"relevant reconciliation attempt.\n\n"
        f"6. **If the Kustomization is healthy but its managed objects are "
        f"not**, fetch each object listed in `status.inventory` and re-diagnose "
        f"that object directly.\n\n"
        f"Report findings as: (a) the first failing step, (b) the actionable "
        f"fix, (c) any second-order suspects worth watching. If a "
        f"`reconcile_flux_kustomization` (or `reconcile_flux_source`) call "
        f"would unblock things, suggest it but do not run it without explicit "
        f"user approval."
    )
