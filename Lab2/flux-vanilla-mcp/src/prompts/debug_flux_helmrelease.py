"""MCP prompt: walk a failing Flux HelmRelease to root cause.

Returns a single user message scripting the diagnostic chain:
HelmRelease → chart source (chartRef or chart.spec.sourceRef) → HelmChart →
events → helm-controller logs.
"""

from __future__ import annotations

from core.server import mcp


@mcp.prompt(
    name="debug_flux_helmrelease",
    title="Debug Flux HelmRelease",
    description=(
        "Walk a HelmRelease through its chart source and recent install/"
        "upgrade history to find the first failing step."
    ),
)
def debug_flux_helmrelease(name: str, namespace: str) -> str:
    """Return the diagnostic checklist as a single user message.

    Args:
        name: HelmRelease name.
        namespace: HelmRelease namespace.
    """
    return (
        f"Diagnose HelmRelease `{name}` in namespace `{namespace}` and "
        f"surface the root cause. Walk this chain in order — stop at the "
        f"first failure.\n\n"
        f"1. **Fetch the HelmRelease itself.**\n"
        f"   - Call `get_kubernetes_resources` with "
        f"`apiVersion=helm.toolkit.fluxcd.io/v2`, `kind=HelmRelease`, "
        f"`name={name}`, `namespace={namespace}`.\n"
        f"   - Inspect `status.conditions` (`Ready`, `Released`, `Remediated`, "
        f"`TestSuccess`), `status.lastAppliedRevision`, `status.history`, "
        f"`status.failures`, `status.installFailures`, "
        f"`status.upgradeFailures`.\n"
        f"   - Note `spec.chartRef` *or* `spec.chart.spec.sourceRef` (one of "
        f"these is set; modern installs use `chartRef`).\n\n"
        f"2. **Fetch the chart source.**\n"
        f"   - If `spec.chartRef` is set: fetch that `HelmChart` or "
        f"`OCIRepository`. Inspect its `status.conditions[type=Ready]` and "
        f"`status.artifact.revision`.\n"
        f"   - If `spec.chart.spec.sourceRef` is set: fetch the named "
        f"`HelmRepository` / `GitRepository` / `Bucket`, then fetch the "
        f"auto-generated `HelmChart` (named `<namespace>-{name}` in "
        f"`flux-system` by default) and inspect both.\n"
        f"   - A failing chart source explains a stuck HelmRelease.\n\n"
        f"3. **Inspect last release.**\n"
        f"   - Look at `status.history[0]` for the most recent release. "
        f"`status=failed` with `digest` and `chartVersion` set tells you which "
        f"version was attempted.\n"
        f"   - Helm itself stores release state in a Secret named "
        f"`sh.helm.release.v1.{name}.<revision>` in `{namespace}`. Fetch the "
        f"most recent one with `get_kubernetes_resources` "
        f"(`apiVersion=v1`, `kind=Secret`) and read `data.release` as a hint, "
        f"though it's base64+gzip — the HelmRelease status is usually "
        f"clearer.\n\n"
        f"4. **Events.**\n"
        f"   - List `Event` resources in `{namespace}` and filter "
        f"`involvedObject.name={name}` `involvedObject.kind=HelmRelease`. "
        f"Reasons to watch for: `InstallFailed`, `UpgradeFailed`, "
        f"`TestFailed`, `RollbackFailed`, `ChartNotReady`.\n\n"
        f"5. **Tail helm-controller logs.**\n"
        f"   - Find the helm-controller Pod in `flux-system` and call "
        f"`get_kubernetes_logs` with `tail_lines=300`. Look for log lines "
        f"mentioning `{name}` or the chart revision from step 3.\n"
        f"   - If `status.failures` is non-zero and `status.upgradeFailures` "
        f"exceeds `spec.upgrade.remediation.retries` (default 0), the release "
        f"will be suspended — flag that.\n\n"
        f"6. **If the chart applied but workloads are broken**, fetch the "
        f"Deployments/StatefulSets/etc. that the chart produced (they carry "
        f"`helm.toolkit.fluxcd.io/name={name}` and "
        f"`helm.toolkit.fluxcd.io/namespace={namespace}` labels) and "
        f"diagnose them directly.\n\n"
        f"Report findings as: (a) the first failing step, (b) the actionable "
        f"fix, (c) suggest `reconcile_flux_helmrelease` only if a fresh "
        f"reconciliation would clearly help — do not run it without explicit "
        f"user approval."
    )
