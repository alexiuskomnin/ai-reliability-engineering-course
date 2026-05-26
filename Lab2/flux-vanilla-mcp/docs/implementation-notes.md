# Implementation Notes — flux-vanilla-mcp build-out

A step-by-step record of the work that closed out `docs/SPEC.md` and the
polish slice. Each section explains *what* was built and *why* the design
choice was made, so the next person (you, three months from now) can
reverse-engineer the intent without re-deriving it from the diff.

The work was sequenced as five "tool" steps plus seven polish items.
Steps 1–5 finished the catalog in `docs/SPEC.md` §5–§6 (tools + prompts).
Polish items 1–2 (this document covers them) deliver the cross-cutting
features in §7–§8. The remaining polish items are listed at the bottom.

Status at the time of writing:

- **Tools:** 15 of 15 implemented (16 modules, including the `echo` example)
- **Prompts:** 2 of 2 implemented
- **Cross-cutting:** scopes, secret masking, dynamic loader, `/healthz`,
  audit log all done. Impersonation, basic unit tests, and RBAC split
  still open.

Conventions followed throughout:

- **One tool per file.** Filename = `TOOL_NAME` constant = decorated
  function name. The dynamic loader at `src/core/server.py` assumes this.
- **Scope registration at import time.** Every tool calls
  `register_scope(TOOL_NAME, read_only=..., in_cluster=...)` at module
  load, then `check_scope(TOOL_NAME)` as the first statement of the
  handler. A tool that skips this silently bypasses read-only mode and
  the `--enabled-tools` allowlist — review carefully.
- **`kagent-example.yaml` updated in lockstep.** Every new tool was
  reflected in the `toolNames:` block (or commented out for writes, with
  a note explaining how to enable). Memory says kagent's `mcpServer`
  block exposes zero tools when `toolNames:` is omitted, so this is a
  correctness check, not optional documentation.
- **`docs/currentstate.md` ticked off** as each tool / cross-cutting
  feature landed.

---

## Step 1 — Finish the read-only discovery surface

**Goal.** Close §5.1 of the spec so the assistant has a complete
read-only cluster-introspection toolkit before any writes get added.

**Tools landed:**

| Tool                          | Scope                                |
| ----------------------------- | ------------------------------------ |
| `get_kubernetes_api_versions` | `read_only=True`, `in_cluster=True`  |
| `set_kubeconfig_context`      | `read_only=True`, `in_cluster=False` |

### `get_kubernetes_api_versions`

**Why this tool first.** The assistant already knows the built-in API
versions (`v1`, `apps/v1`). The interesting cases are CRDs, where the
group is custom and the storage version drifts as operators upgrade.
Without this tool, the assistant either has to guess
`source.toolkit.fluxcd.io/v1` vs `/v1beta2` or call
`get_kubernetes_resources` with trial-and-error apiVersions and read 404
responses to figure out what's installed.

**Implementation choice — list CRDs only, not built-in groups.** The
spec says "all CRDs with preferred apiVersion per kind." We hit
`ApiextensionsV1Api(...).list_custom_resource_definition()` once and
pick the preferred version per CRD with this rule:

1. Filter `versions` to those with `served=true`.
2. Among served versions, prefer the one marked `storage=true`.
3. If none is marked storage, return the first served entry.

This mirrors how `kubectl explain` resolves the canonical version. The
return is sorted `(apiVersion, kind)` so the assistant gets a stable
ordering — important when the same prompt may be re-run later.

**Trade-off accepted.** Built-in groups (`apps`, `batch`, `networking.k8s.io`)
are not enumerated. The assistant is expected to know those, and we
don't pay the round-trip cost of listing `/apis`.

### `set_kubeconfig_context`

**Why this is `in_cluster=False`.** Inside a Pod there's no kubeconfig
to switch — the service account token is mounted at a fixed path and
`load_incluster_config()` is the only entry point. Letting this tool
run in-cluster would be either confusing (it would silently succeed)
or wrong (it would mutate state that no other tool reads).

**Why `read_only=True` despite the word "set".** The tool is named for
its effect on the *server process*, not the cluster. It changes
`RuntimeConfig.kube_context_override` via `set_context_override()` —
nothing leaves the process. Marking it write-scoped would lock it out
of read-only deployments unnecessarily. The convention used here is:
*scope tracks effects on the cluster, not the server's in-memory
state*.

**Validation choice — reject unknown context names.** Rather than
let `kubernetes.config.load_kube_config()` fail downstream on the next
tool call (which would give a misleading error to the LLM), we read
`list_kube_config_contexts()` first and return a structured error with
the list of available context names. The assistant can then re-prompt
the user with the valid choices.

### Step 1 — considerations to revisit

- `get_kubernetes_api_versions` does not currently filter out the
  Flux-specific CRDs that already appear in `get_flux_status`. The
  overlap is intentional — the assistant may use either tool depending
  on intent — but if response size becomes an issue, an
  `excludeFluxCrds` flag would be cheap.
- `set_kubeconfig_context` does not persist to disk. If the server
  restarts, the override is lost. This is deliberate: persisting would
  silently rewrite the user's `~/.kube/config`.

---

## Step 2 — Flux reconcile / suspend / resume (annotation-patch family)

**Goal.** Implement the five write tools in spec §5.3. They all share
the same primitive — bump an annotation, or toggle `spec.suspend` —
plus an optional "wait for the controller to handle it" poll.

**Tools landed:** `reconcile_flux_source`,
`reconcile_flux_kustomization`, `reconcile_flux_helmrelease`,
`suspend_flux_reconciliation`, `resume_flux_reconciliation`. All
registered with `read_only=False`, `in_cluster=True`.

### Why a shared helper module — `src/core/flux_actions.py`

Three reasons:

1. **Avoid copy-paste between five files.** The patch body
   `{"metadata": {"annotations": {"reconcile.fluxcd.io/requestedAt": ts}}}`
   appears in three reconcile tools. Sharing means one place to change
   the annotation key if Flux ever renames it.
2. **Centralise GVK resolution.** Suspend/resume accept any
   reconcilable Flux kind by name. Mapping `"Kustomization"` →
   `("kustomize.toolkit.fluxcd.io/v1", "Kustomization")` lives once in
   `_KIND_TO_API_VERSION`. The exported sets `SOURCE_KINDS` and
   `SUSPENDABLE_KINDS` are reused as input validators by the tools.
3. **Polling logic is non-trivial.** `poll_reconciled()` watches
   `status.lastHandledReconcileAt` and `status.conditions[type=Ready]`
   until either both are satisfied or `RuntimeConfig.timeout_seconds`
   elapses. Sticking that into each tool would have invited drift.

### Why patch via JSON merge, not strategic merge

Strategic-merge patch requires server-side schema knowledge that
exists for built-in resources but not for arbitrary CRDs. JSON merge
(`application/merge-patch+json`) is universally supported and
behaviourally correct for the two changes we make: adding a single
annotation key, or setting one boolean field. No semantic ambiguity.

### Why we poll, not fire-and-forget

The `flux reconcile` CLI blocks until the controller picks up the new
`requestedAt`. Mimicking that gives the assistant a real outcome to
report ("reconciled in 4s" vs "not handled within 60s") rather than
"I asked, you check." For the LLM caller this matters more than for a
human — humans can `kubectl get -w`; an LLM in a turn-based loop
cannot easily.

Polling cadence is 1.5s, bounded by `RuntimeConfig.timeout_seconds`
(default 60). Worst case is a 60s blocked MCP handler — acceptable for
an interactive session.

### `withSource` for workload reconciles

Both `reconcile_flux_kustomization` and `reconcile_flux_helmrelease`
accept `withSource: bool = False`. When true, the tool first fetches
the workload, extracts its source ref, reconciles that source, then
reconciles the workload.

Helpers `extract_kustomization_source()` and
`extract_helmrelease_source()` handle the differences:

- Kustomization always uses `spec.sourceRef`.
- HelmRelease may use either `spec.chartRef` (the v2 modern style) or
  `spec.chart.spec.sourceRef` (the legacy template). The extractor
  tries `chartRef` first and falls back.

This mirrors `flux reconcile kustomization --with-source` and
`flux reconcile helmrelease --with-source` and gives the assistant
parity with how a human operator would unstick a stale chain.

### `withSource` kept in camelCase

Spec §5.3 declares the field as `withSource?: bool`. FastMCP exposes
the Python parameter name as the JSON schema property, so we have to
match the spec literally. The codebase already uses camelCase for
`apiVersion` and `labelSelector` (`get_kubernetes_resources`); ruff's
N803 is silenced with a per-arg `# noqa: N803`. Convention going
forward: tool inputs match the spec's casing exactly, even when ruff
complains.

### Step 2 — considerations to revisit

- Polling is synchronous (`time.sleep`). On a busy MCP server, a slow
  reconcile blocks one worker. If concurrency becomes a concern, the
  poll loop should move to `asyncio.sleep` and the handlers should be
  declared `async`.
- A reconcile that times out is still recorded as `outcome=error` in
  the audit log (added in polish step 2) — useful for spotting stuck
  controllers in cluster-wide forensics.

---

## Step 3 — Generic apply + delete

**Goal.** Round out §5.2 of the spec with the two general-purpose
write tools. Together they let the assistant cover any GVK the cluster
exposes, not just Flux objects.

### `apply_kubernetes_manifest`

**Why server-side apply (SSA), not `create` + `replace`.** SSA records
field ownership per manager. We set `fieldManager=flux-vanilla-mcp` so
the assistant's edits don't trample fields owned by the actual
controllers (kustomize-controller, helm-controller, anyone else).
SSA is also the only sane multi-step iteration model — the assistant
can re-apply a slightly-different manifest without manually computing
the diff.

**Why multi-doc YAML.** Real Kubernetes manifests are usually
multi-doc (Deployment + Service + ConfigMap). Splitting on `---` and
applying each doc separately matches `kubectl apply -f file.yaml`
semantics, including the response shape: a list of per-resource
results instead of one global yes/no.

**Why `dyn.server_side_apply(resource, ...)`, not
`resource.server_side_apply(...)`.** The Python dynamic client has the
method on the `DynamicClient` itself, not on the `Resource` proxy.
Verified by `inspect.signature`. Calling through the proxy fails
silently in some versions.

**The `force` flag.** Mirrors `kubectl apply --force-conflicts`. Off
by default. Set true only when you intentionally want to take over a
field owned by another fieldManager. Most assistant interactions
should leave it off — a conflict is signal, not noise.

### `delete_kubernetes_resource`

**Why the destructive guard, given RBAC already allows everything.**
Defence-in-depth at the application layer. The current
`flux-vanilla-mcp:write` ClusterRole grants `delete` on `*/*`, so the
SA *can* delete a Namespace or CRD. The application-layer guard catches
the cases where a hallucinated LLM call accidentally targets
cluster-scoped objects. It's the cheap belt that the RBAC suspenders
don't currently provide. Tightening RBAC would be a separate (better)
fix tracked in the polish list.

**Why these three guards.**

- `Namespace` deletes cascade to everything inside — high blast
  radius, high regret value.
- `CustomResourceDefinition` deletes orphan every CR of that kind —
  same logic.
- `kube-system` is where the control plane lives; nothing the
  assistant does there is ever the right answer in a homelab.

The guard is bypassed by a single env var
(`FLUX_MCP_ALLOW_DESTRUCTIVE=true`) or CLI flag
(`--allow-destructive`) — chosen so it's deliberate when needed but
not invisible. Both surface in `RuntimeConfig.allow_destructive`.

**Why 404 is treated as success.** A deleted-not-found is benign — the
desired state is reached. The tool returns a message field rather than
an error so the assistant doesn't retry needlessly. Audit log (added
in polish 2) records this as `outcome=ok` too.

### Step 3 — considerations to revisit

- The write ClusterRole is much broader than the application-layer
  guards. Listed in the polish punch-list as item 3.
- No dry-run mode. Useful for both apply and delete; cheap to add via
  `dry_run=["All"]` query param. Not implemented yet to keep the
  surface narrow.

---

## Step 4 — MCP prompts (workflow glue)

**Goal.** Translate the diagnostic muscle-memory ("walk
Kustomization → source → events → controller logs") into MCP prompts
that the assistant can invoke on demand.

**Prompts landed:** `debug_flux_kustomization`,
`debug_flux_helmrelease`.

### Why prompts instead of more tools

A prompt is a templated user message — pure text. It's the right
shape when the work is *coordinating other tools*, not *adding a new
capability*. The debug walk needs no new API surface; it needs the
assistant to call `get_kubernetes_resources`, `get_kubernetes_logs`,
etc. in the right order.

Prompts also live in the MCP protocol as first-class objects, so a
human user or an Agent system prompt can reference them by name
(`/prompts/debug_flux_kustomization`).

### The loader extension

The existing dynamic loader in `src/core/server.py` only scanned
`src/tools/`, and fail-fast'd any module that registered zero tools.
A prompt module registers zero tools, so dropping prompt files into
`src/tools/` would have broken startup.

The fix: add a `prompts_dir` parameter (default `src/prompts`) and a
second scan after tools. The semantics mirror tool loading exactly —
import each `.py` file, count prompts before/after, fail-fast if a
file registers zero prompts. Sharing the import helper
(`_import_tool_module`, despite the name) keeps the error-handling
identical.

### Prompt content design

Both prompts share a structure:

1. Number the diagnostic steps explicitly. "1. Fetch the Kustomization
   itself…" → "6. If healthy but managed objects aren't, recurse."
2. Specify the exact tool call with apiVersion/kind/name — no
   guessing.
3. End with a write-tool firewall: "suggest `reconcile_*` but do not
   run without explicit user approval." This matters because the
   prompt is text the LLM follows literally; without the line the
   assistant might call a write tool autonomously to "fix" the issue.

The HelmRelease prompt is the longer one because it has to handle two
chart-source layouts (`chartRef` vs `chart.spec.sourceRef`), the
Helm-managed Secret state, and `status.history` — all of which differ
from the Kustomization flow.

### Step 4 — considerations to revisit

- No tests for prompts. Their value is the text; the registration is
  covered by the dynamic loader's count check. If prompts grow to
  reference fields that have since renamed, that breakage will surface
  in actual diagnostic runs rather than CI.
- The HelmRelease Secret lookup mentioned in step 3 of the prompt
  works, but the assistant has to manually base64+gzip-decode the
  `data.release` field. Could be a dedicated tool if it becomes a
  pattern, but is deferred.

---

## Step 5 — `search_flux_docs`

**Goal.** Close §5.4 of the spec. The assistant should be able to
answer "what does the `spec.upgrade.remediation.retries` field do?"
without forcing the user to alt-tab to fluxcd.io.

### Why GitHub code search as the default backend

Alternatives considered:

- **Algolia DocSearch (what fluxcd.io uses for site search).** The
  public app ID + search-only API key are embedded in fluxcd.io's
  client-side JS. Functional, but undocumented and could rotate
  without notice — fragile.
- **Hugo `/index.json`.** Hugo emits a JSON index when configured.
  Verifying that fluxcd.io publishes one and stays publishing it is
  ongoing work I didn't want to take on.
- **Scraping fluxcd.io's `/search/?q=` page.** JavaScript-rendered;
  no clean JSON contract.
- **GitHub code search against `fluxcd/website`.** Documented public
  API, returns text snippets, returns deterministic file paths we can
  rewrite to fluxcd.io URLs. The catch: GitHub disabled
  unauthenticated code search in 2022. Auth requires a token.

I picked GitHub code search because it's the only option with a
documented, stable contract. The 401 case is handled with an
actionable error message naming the env var to set.

### Why the URL template is configurable

`RuntimeConfig.flux_docs_search_url` accepts a string with a `{query}`
placeholder. The CLI flag `--flux-docs-search-url` and env var
`FLUX_MCP_DOCS_SEARCH_URL` both override it. Reasons:

1. Operators in restrictive networks may want to point at an internal
   docs mirror.
2. If GitHub deprecates code-search auth again or someone publishes a
   public JSON index for fluxcd.io, swapping the default doesn't
   require a code change.
3. `_format_results()` falls back gracefully to "return raw items if
   it doesn't look like the GitHub schema" so a different backend
   doesn't crash the tool.

### Result-shape decisions

For each match, the tool returns:

- `title` — file path with `content/en/` and `.md`/`/_index.md`
  stripped. Reads like a doc navigation breadcrumb.
- `url` — rewritten to `https://fluxcd.io/<path>/` so the LLM cites a
  link a human can click rather than the raw GitHub blob URL.
- `repoPath` — kept for completeness in case the LLM wants to fetch
  the source.
- `snippets` — up to two text-match fragments, truncated to 240 chars.
  GitHub returns these via the `application/vnd.github.text-match+json`
  Accept header.

Capped at 5 results. The assistant rarely needs more, and an MCP
response over a few KB starts costing real tokens.

### Step 5 — considerations to revisit

- No caching. Repeated queries cost GitHub API calls each time.
  Acceptable for a homelab MCP; for higher traffic, an LRU cache keyed
  on `(query, url_template)` would be easy.
- URL substitution uses `quote_plus` to URL-encode `{query}`. Safe
  against injection into the URL path component, but if the URL
  template ever started using `{query}` in a body (not a path), this
  encoding would be wrong.

---

## Polish 1 — `GET /healthz`

**Goal.** Give kmcp / kagent a cheap liveness signal. Previously the
only way to know the server was up was to fire an MCP `tools/list`
JSON-RPC call — too heavy for a kubelet probe.

### Why we used FastMCP's `custom_route`

FastMCP wraps Starlette under the hood. The `@mcp.custom_route()`
decorator is the documented hook for "add an arbitrary HTTP endpoint
outside the MCP protocol" — its docstring literally lists health
checks as an example. Anything more clever (writing a separate
Starlette app, adding a sidecar) costs more and reads worse.

### Why the endpoint reports tool/prompt counts

```json
{"status":"ok","server":"flux-vanilla-mcp","tools":16,"prompts":2}
```

`status: ok` answers "is the process alive." The counts answer "did
the dynamic loader actually populate the registry." Both can be
true individually but only the conjunction is meaningful — a fail-fast
process restart will surface in the counts before MCP traffic notices.

### Why we don't call the Kubernetes API in the probe

Two reasons:

1. **Liveness ≠ dependency health.** If the API server hiccups for
   30s, the kubelet shouldn't restart this Pod — the MCP server is
   still functioning; it just can't serve cluster reads right now.
   Coupling liveness to API connectivity creates spurious restarts.
2. **Cost.** A `kubectl version` call hits the API server. Multiply by
   the kubelet's probe frequency and you've added measurable load with
   no clinical benefit.

If you want a stricter "ready to serve cluster reads" check, add a
separate `/readyz` that does call the API. Not implemented because
nothing currently uses it.

### Wiring

The endpoint is registered only when `transport_mode == "http"`.
On stdio (local AI assistant integration), there's no HTTP server to
hang the route off — registering it would be a silent no-op or, in
some FastMCP versions, a startup warning.

Smoke test target added to the Makefile:

```bash
make smoke-health
```

Bound to whatever `$(PORT)` resolves to (default 8080).

### Polish 1 — considerations to revisit

- No kubernetes `readinessProbe` actually points at this URL yet.
  `kmcp deploy` doesn't seem to set probes by default. Tracked in the
  polish list as item 6.
- Authentication is none — the endpoint is publicly readable inside
  the cluster. That's fine for an in-cluster ClusterIP Service but
  worth noting if the Service is ever exposed externally.

---

## Polish 2 — Audit log on write tools

**Goal.** Spec §7.4: emit one JSON line on stderr per write
invocation, with enough identity and outcome data to investigate "who
mutated what, when, with what result?"

Schema:

```json
{
  "ts": "2026-05-26T01:23:45Z",
  "tool": "reconcile_flux_kustomization",
  "user": "system:serviceaccount:default:flux-vanilla-mcp",
  "context": "in-cluster",
  "kind": "Kustomization",
  "name": "podinfo",
  "namespace": "default",
  "durationMs": 1842,
  "outcome": "ok",
  "error": null
}
```

### Why a context manager + a direct emit function

Most write tools target a single resource and follow the same shape:
`check_scope` → patch → maybe poll → return. For those, a
`with audit_scope(TOOL_NAME, kind=, name=, namespace=) as audit:`
wrapper is the cleanest pattern — it captures start time, classifies
exceptions (`ScopeError` → `denied`, anything else → `error`), and
emits exactly once on exit. The tool can override the default `ok` by
calling `audit.fail("reason")` when it returns a structured error YAML
instead of raising.

`apply_kubernetes_manifest` is different — it can apply N documents
per call. One audit line per call wouldn't capture which docs failed.
For that tool, `_apply_one()` calls `audit_emit(...)` directly per
document. A scope rejection at the top of the handler emits a single
`outcome=denied` record before re-raising, so denied calls aren't
silent.

### Why exceptions still propagate

The audit context manager re-raises after recording. FastMCP catches
the exception and serialises it into an MCP JSON-RPC error. If we
swallowed exceptions in audit_scope, the assistant would get a
"successful" response containing nothing — much worse than a clean
error.

### Identity resolution (`user` + `context`)

Two modes:

- **In-cluster:** read namespace from
  `/var/run/secrets/kubernetes.io/serviceaccount/namespace`. The SA
  *name* is not exposed inside the Pod without parsing the JWT, so we
  read it from `POD_SERVICE_ACCOUNT` (set by the operator via downward
  API or directly in the Pod spec) and fall back to
  `flux-vanilla-mcp`. `context` is the literal `"in-cluster"`.
- **Local:** read from kubeconfig — current context name and its
  `.user` field. The kubeconfig context can be overridden in-process
  by `set_kubeconfig_context`, so we honour that.

If the kubeconfig is unreadable (e.g. unit tests pass `/dev/null`),
both fall back to `"unknown"`. Better than crashing the audit emit.

### Why outcomes are `ok | error | denied`

Three states is enough to drive an alert / a forensic query:

- `ok` — the tool did what was asked.
- `denied` — `check_scope` (or the destructive guard) refused.
  Distinguishable from `error` so it doesn't pollute "real failure"
  metrics.
- `error` — the tool tried, the cluster pushed back, or something
  unexpected happened. The `error` field carries the
  reason (`"403 Forbidden"`, `KubeClientError(...)`, etc.).

`outcome=error` includes the case where a reconcile polled to timeout
without `Ready=True` — the patch succeeded but the controller didn't
catch up in time. From an audit perspective, that's a failed
reconcile attempt and worth investigating, even though no HTTP error
was returned.

### Why stderr, why one line

- **stderr, not stdout.** Stdout is reserved for MCP protocol traffic
  in stdio mode. Mixing audit lines into it would corrupt the
  JSON-RPC stream.
- **One JSON line per record.** Kubernetes container logs are
  line-delimited. `kubectl logs deploy/flux-vanilla-mcp | jq .` works
  out of the box. Multi-line records would require a log-shipper to
  re-merge.
- **`flush=True`.** Writes are infrequent (human-paced assistant
  interactions) and we want forensics to survive an abrupt pod
  termination.

### Smoke-tested live

```text
{"ts":"...","tool":"suspend_flux_reconciliation","outcome":"denied",
 "error":"...is a write operation but the server is in read-only mode"}

{"ts":"...","tool":"resume_flux_reconciliation","outcome":"error",
 "error":"KubeClientError('failed to load kubeconfig ...')"}
```

Both paths produce one line, correct outcome, populated error field.

### Polish 2 — considerations to revisit

- No log rotation. The container runtime handles it.
- No correlation ID. If the assistant fires multiple writes in quick
  succession, they're correlated by `ts` order and operator memory.
  An MCP request-ID field could be added if the audit trail starts
  feeding an alerting system.
- The audit log is unconditional — there's no `--audit-log=false`
  flag. Cheap to add a `RuntimeConfig.audit_enabled` toggle later if
  some deployment wants it off.

---

## What's still open

From the most recent polish punch-list in `docs/currentstate.md`:

1. **Impersonation flags.** `--kube-as`, `--kube-as-group`,
   `--kube-as-uid` would wire through to the K8s client and surface as
   the `user` field in audit lines, replacing the SA path.
2. **Per-tool unit tests.** Cover the scope-rejection paths and the
   not-found / forbidden code paths with a mocked dynamic client.
3. **RBAC split.** `deploy/rbac-read.yaml` + `deploy/rbac-write.yaml`
   with separate Makefile targets, so a read-only deployment isn't
   silently granted write rights at the RBAC layer.
4. **Confirm SA wiring.** `kubectl describe deployment flux-vanilla-mcp`
   to verify the running Pod uses the `flux-vanilla-mcp` SA, not
   `default`. If it uses default, all of `deploy/rbac.yaml` is moot.
5. **`kmcp.yaml` `runtime.args` block.** Lift the deploy args out of
   `Makefile`'s `--args` string into the project descriptor where they
   belong.
6. **`readinessProbe` wiring.** Point the kubelet at the `/healthz`
   endpoint we shipped in polish 1.
7. **`POD_SERVICE_ACCOUNT` env var.** Set on the deployed Pod so the
   audit log records the real SA name instead of the
   `flux-vanilla-mcp` default fallback.

Each is small. Whichever order makes sense for your forensic /
operational need is fine; impersonation is the natural pair with the
audit log (they share the `user` field).
