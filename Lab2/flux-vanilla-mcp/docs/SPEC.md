# Flux MCP Server — Vanilla Specification

A Model Context Protocol server that exposes **Flux CD** to AI assistants
**without** depending on the `flux-operator` (no `FluxInstance` /
`FluxReport` CRDs). Inspired by
[`controlplaneio-fluxcd/flux-operator/cmd/mcp`](https://github.com/controlplaneio-fluxcd/flux-operator/tree/main/cmd/mcp)
but rewritten on top of upstream Flux v2 CRDs only.

Target dual-use:

1. **Local** — run with `uv run python src/main.py` and consume from
   Claude / Cursor / Copilot over stdio.
2. **In-cluster** — package and ship via `kmcp build` + `kmcp deploy`, then
   reference the resulting `MCPServer` from a `kagent` `Agent`.

---

## 1. Scope diff against the upstream operator MCP

| Upstream concept                                | Vanilla equivalent                                                |
| ----------------------------------------------- | ----------------------------------------------------------------- |
| `FluxInstance` + `FluxReport` CRDs              | Detect upstream `flux-system` Deployments + CRD inventory         |
| `install_flux_instance` tool                    | **Removed** — user installs Flux via `flux install` / Helm        |
| `get_flux_instance` tool                        | Replaced by `get_flux_status` (controllers + versions + CRDs)     |
| `reconcile_flux_resourceset` tool               | **Removed** — `ResourceSet` is an operator CRD                    |
| Kustomization / HelmRelease / source operations | Kept, implemented via annotation patches on upstream CRs          |
| Logs / metrics / resources / apply / delete     | Kept                                                              |
| Docs search                                     | Kept                                                              |

## 2. Architecture

```
src/
├── main.py                          # FastMCP entrypoint
├── core/
│   ├── server.py                    # dynamic tool loader (existing)
│   ├── utils.py                     # existing helpers
│   ├── config.py                    # runtime config singleton
│   ├── flux_types.py                # GVK constants for upstream Flux CRDs
│   ├── k8s_client.py                # kubeconfig + dynamic K8s client
│   ├── scopes.py                    # read-only / in-cluster gating
│   └── secrets.py                   # Secret masking helpers
├── tools/                           # one tool per file
│   ├── get_flux_status.py
│   ├── get_kubernetes_resources.py
│   ├── get_kubernetes_logs.py
│   ├── get_kubernetes_metrics.py
│   ├── get_kubernetes_api_versions.py
│   ├── apply_kubernetes_manifest.py
│   ├── delete_kubernetes_resource.py
│   ├── reconcile_flux_source.py
│   ├── reconcile_flux_kustomization.py
│   ├── reconcile_flux_helmrelease.py
│   ├── suspend_flux_reconciliation.py
│   ├── resume_flux_reconciliation.py
│   ├── get_kubeconfig_contexts.py
│   ├── set_kubeconfig_context.py
│   └── search_flux_docs.py
└── prompts/
    ├── debug_kustomization.py
    └── debug_helmrelease.py
deploy/
├── rbac.yaml                        # ServiceAccount + ClusterRole/Binding
└── kagent-example.yaml              # Sample kagent Agent referencing the MCPServer
```

**Runtime deps:** `fastmcp`, `pydantic`, `pyyaml`, `python-dotenv` (existing) +
`kubernetes>=30`, `httpx`.

## 3. Runtime configuration

| Flag / Env                        | Default       | Purpose                                                            |
| --------------------------------- | ------------- | ------------------------------------------------------------------ |
| `--transport`                     | `stdio`       | `stdio` \| `http`                                                  |
| `--host` / `--port`               | `localhost:3000` | HTTP only                                                       |
| `--read-only`                     | `false`       | Disables `apply_*`, `delete_*`, `reconcile_*`, suspend/resume      |
| `--mask-secrets`                  | `true`        | Redacts `Secret.data` / `stringData` in outputs                    |
| `--timeout`                       | `60s`         | Per-tool context timeout                                           |
| `--kubeconfig` / `$KUBECONFIG`    | `~/.kube/config` | Path; supports `:`-separated list                               |
| `--kube-context`                  | current       | Overridable at runtime via `set_kubeconfig_context`                |
| `--enabled-tools`                 | all           | Comma-separated allowlist                                          |
| `KUBERNETES_SERVICE_HOST` present | —             | **In-cluster mode**: forbid kubeconfig-mutating tools, load SA     |

## 4. Upstream Flux GVKs (the only API surface)

```python
# src/core/flux_types.py
SOURCE_GVKS = [
    ("source.toolkit.fluxcd.io/v1",      "GitRepository"),
    ("source.toolkit.fluxcd.io/v1beta2", "OCIRepository"),
    ("source.toolkit.fluxcd.io/v1",      "HelmRepository"),
    ("source.toolkit.fluxcd.io/v1",      "Bucket"),
    ("source.toolkit.fluxcd.io/v1beta2", "HelmChart"),
]
KUSTOMIZATION_GVK = ("kustomize.toolkit.fluxcd.io/v1", "Kustomization")
HELMRELEASE_GVK   = ("helm.toolkit.fluxcd.io/v2",      "HelmRelease")
NOTIFICATION_GVKS = [
    ("notification.toolkit.fluxcd.io/v1beta3", "Alert"),
    ("notification.toolkit.fluxcd.io/v1beta3", "Provider"),
    ("notification.toolkit.fluxcd.io/v1",      "Receiver"),
]
IMAGE_GVKS = [
    ("image.toolkit.fluxcd.io/v1beta2", "ImageRepository"),
    ("image.toolkit.fluxcd.io/v1beta2", "ImagePolicy"),
    ("image.toolkit.fluxcd.io/v1beta2", "ImageUpdateAutomation"),
]
```

Detect Flux: list CRDs with group ending in `.toolkit.fluxcd.io` and
Deployments in `flux-system` labelled `app.kubernetes.io/part-of=flux`.

## 5. Tool catalog

All inputs are Pydantic models; outputs are text blocks (YAML / plain).

### 5.1 Cluster discovery

| Tool                          | Read-only | In-cluster | Description                                                              |
| ----------------------------- | --------- | ---------- | ------------------------------------------------------------------------ |
| `get_flux_status`             | ✓         | ✓          | Controller deployments + installed Flux CRDs + cluster version + counts. |
| `get_kubernetes_api_versions` | ✓         | ✓          | All CRDs with preferred apiVersion per kind.                             |
| `get_kubeconfig_contexts`     | ✓         | ✗          | Contexts from kubeconfig.                                                |
| `set_kubeconfig_context`      | ✓         | ✗          | In-memory context switch (does not rewrite the file).                    |

### 5.2 Resource I/O

| Tool                           | Read-only | In-cluster | Description                                                              |
| ------------------------------ | --------- | ---------- | ------------------------------------------------------------------------ |
| `get_kubernetes_resources`     | ✓         | ✓          | Get/list any GVK; managed fields stripped; secret data masked.           |
| `get_kubernetes_logs`          | ✓         | ✓          | Pod logs; ~1 MB cap.                                                     |
| `get_kubernetes_metrics`       | ✓         | ✓          | `metrics.k8s.io` CPU/mem; graceful error if missing.                     |
| `apply_kubernetes_manifest`    | ✗         | ✓          | Server-side apply, fieldManager=`flux-vanilla-mcp`.                              |
| `delete_kubernetes_resource`   | ✗         | ✓          | Refuses `Namespace`/`CRD`/`kube-system` unless `--allow-destructive`.    |

### 5.3 Flux operations (annotation patches — no operator calls)

Mirror `flux reconcile / suspend / resume`. Each tool patches the standard
`reconcile.fluxcd.io/requestedAt` annotation or `spec.suspend` field and
polls status up to `--timeout`.

| Tool                            | Input                                                                       |
| ------------------------------- | --------------------------------------------------------------------------- |
| `reconcile_flux_source`         | `{kind: GitRepository\|OCIRepository\|HelmRepository\|Bucket, name, namespace}` |
| `reconcile_flux_kustomization`  | `{name, namespace, withSource?: bool}`                                      |
| `reconcile_flux_helmrelease`    | `{name, namespace, withSource?: bool}`                                      |
| `suspend_flux_reconciliation`   | `{kind, name, namespace}`                                                   |
| `resume_flux_reconciliation`    | `{kind, name, namespace}`                                                   |

### 5.4 Documentation

| Tool                | Description                                                                 |
| ------------------- | --------------------------------------------------------------------------- |
| `search_flux_docs`  | HTTPS GET against fluxcd.io search or a prebuilt JSON index URL in config.  |

## 6. MCP Prompts

- `debug_flux_kustomization {name, namespace}` — instructs the assistant to
  walk Kustomization → sourceRef → events → kustomize-controller logs.
- `debug_flux_helmrelease {name, namespace}` — same flow for HelmRelease +
  HelmChart + helm-controller logs.

## 7. Security model

1. **Permission tiers** — `core/scopes.py` decorates handlers with
   `(read_only, in_cluster)` and refuses execution when the runtime
   config disallows the operation.
2. **Secret masking** — mandatory when `--mask-secrets`. Applies to
   `v1/Secret.{data,stringData}` and any field whose path ends in
   `password|token|key|cert`. Replace with `"***"`.
3. **Impersonation** — pass through `--kube-as`, `--kube-as-group`,
   `--kube-as-uid`.
4. **Audit log** — every write tool emits a single JSON line on stderr:
   `{ts, tool, user, context, namespace, kind, name, durationMs, outcome}`.

## 8. Transport

- **stdio**: default, used by local AI assistant integrations.
- **http**: streamable HTTP at `POST /mcp` plus `GET /healthz`. Required
  for in-cluster deployment so kagent can reach the server.
- **No SSE** — upstream marks it legacy; skip.

## 9. Local usage

```bash
uv sync
uv run python src/main.py                                # stdio
uv run python src/main.py --transport http --port 8080   # http
```

Local MCP client config (e.g. Claude Code, `~/.claude/mcp.json`):

```json
{
  "mcpServers": {
    "flux-vanilla-mcp": {
      "command": "uv",
      "args": ["run", "python", "src/main.py"],
      "env": { "KUBECONFIG": "/Users/me/.kube/config" }
    }
  }
}
```

## 10. Deployment with kmcp + kagent

### 10.1 Build & deploy via kmcp

`kmcp.yaml` already exists. The build/deploy flow:

```bash
# Build the container (uses the Dockerfile in the project root)
kmcp build

# Deploy to the current kube-context; emits an MCPServer CR
kmcp deploy --namespace default
```

The MCPServer is configured to run with **HTTP transport** in-cluster
because kagent reaches MCP servers over HTTP, not stdio. Add this to
`kmcp.yaml` so `kmcp deploy` runs the right command:

```yaml
# kmcp.yaml (additions)
runtime:
  args: ["src/main.py", "--transport", "http", "--port", "8080", "--read-only=true"]
  port: 8080
  healthCheckPath: /healthz
```

> Verify exact field names against your kmcp CLI version — schemas have
> shifted between releases. The intent: HTTP on 8080, read-only by default
> in-cluster, livez at `/healthz`.

### 10.2 RBAC

`deploy/rbac.yaml` ships a `ServiceAccount` + `ClusterRole` granting:

- `get/list/watch` on all `*.toolkit.fluxcd.io` CRs and `apiextensions.k8s.io/CustomResourceDefinition`
- `get/list` on `pods`, `pods/log`, `events`, `namespaces`, `deployments`, `configmaps`
- `get/list` on `pods.metrics.k8s.io` and `nodes.metrics.k8s.io`
- (write mode only) `patch` on the four Flux groups for annotation triggers,
  `create/patch/delete` on a narrow allowlist for `apply_kubernetes_manifest`

Bind the SA in the MCPServer's pod spec. `kmcp deploy` should pick this up
automatically when the file is referenced from `kmcp.yaml`.

### 10.3 Wiring into kagent

Once deployed, kagent references the MCPServer in an `Agent` (or `Tool`)
CR. Example (verify the schema against your kagent version):

```yaml
apiVersion: kagent.dev/v1alpha1
kind: Agent
metadata:
  name: flux-debugger
  namespace: kagent-system
spec:
  systemPrompt: |
    You are a Flux CD operator assistant. Always start by calling
    get_flux_status to understand cluster state.
  tools:
    - type: McpServer
      mcpServer:
        name: flux-vanilla-mcp           # name of the MCPServer CR
        namespace: default
```

`deploy/kagent-example.yaml` will carry a working version of this once the
kagent schema is confirmed for the user's cluster.

### 10.4 Local ↔ in-cluster parity

The same binary runs in both modes. The differences are entirely runtime
flags + environment detection:

| Concern                | Local                                | In-cluster                              |
| ---------------------- | ------------------------------------ | --------------------------------------- |
| Transport              | `stdio`                              | `http` on `:8080`                       |
| Auth to Kubernetes     | `$KUBECONFIG`                        | ServiceAccount (`KUBERNETES_SERVICE_HOST` triggers) |
| `set_kubeconfig_context` | enabled                            | disabled (no kubeconfig file)           |
| Default `--read-only`  | `false`                              | `true` (override per-deployment)        |

## 11. Testing

- Unit tests per tool using the `kubernetes` client's mock or `pytest-httpx`.
- E2E suite on **kind** + a fresh upstream `flux install` (not flux-operator).
- Golden-file tests for YAML output (managed-fields stripping, masking).

## 12. Out of scope / open questions

- Multi-cluster fanout — single-cluster only, matching upstream parity.
- Git write-back / PR creation — not in scope.
- `ResourceSet` reconciliation — dropped (operator CRD). A generic
  `reconcile_flux_object {apiVersion, kind, name, namespace}` could
  replace it if needed; defer the decision.
