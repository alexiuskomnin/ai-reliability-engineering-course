# Current State — flux-vanilla-mcp

Last verified: 2026-05-26 on homelab Talos cluster (kagent.dev/v1alpha2,
kmcp controller installed, Flux v2 installed).

Cross-referenced against [`docs/SPEC.md`](SPEC.md).

---

## Tools — 15 of 15 implemented

### 5.1 Cluster discovery — 4 / 4
| Tool                          | Status | File                                       |
| ----------------------------- | ------ | ------------------------------------------ |
| `get_flux_status`             | ✅     | `src/tools/get_flux_status.py`             |
| `get_kubernetes_api_versions` | ✅     | `src/tools/get_kubernetes_api_versions.py` |
| `get_kubeconfig_contexts`     | ✅     | `src/tools/get_kubeconfig_contexts.py`     |
| `set_kubeconfig_context`      | ✅     | `src/tools/set_kubeconfig_context.py`      |

### 5.2 Resource I/O — 5 / 5
| Tool                         | Status | Notes                                          |
| ---------------------------- | ------ | ---------------------------------------------- |
| `get_kubernetes_resources`   | ✅     | `src/tools/get_kubernetes_resources.py`        |
| `get_kubernetes_logs`        | ✅     | `src/tools/get_kubernetes_logs.py`             |
| `get_kubernetes_metrics`     | ✅     | `src/tools/get_kubernetes_metrics.py`          |
| `apply_kubernetes_manifest`  | ✅     | SSA, fieldManager=`flux-vanilla-mcp`           |
| `delete_kubernetes_resource` | ✅     | gates Namespace/CRD/kube-system on `--allow-destructive` |

### 5.3 Flux operations (annotation patches) — 5 / 5
All write tools. Shared helpers live in `src/core/flux_actions.py`.
| Tool                            | Status | File                                          |
| ------------------------------- | ------ | --------------------------------------------- |
| `reconcile_flux_source`         | ✅     | `src/tools/reconcile_flux_source.py`          |
| `reconcile_flux_kustomization`  | ✅     | `src/tools/reconcile_flux_kustomization.py`   |
| `reconcile_flux_helmrelease`    | ✅     | `src/tools/reconcile_flux_helmrelease.py`     |
| `suspend_flux_reconciliation`   | ✅     | `src/tools/suspend_flux_reconciliation.py`    |
| `resume_flux_reconciliation`    | ✅     | `src/tools/resume_flux_reconciliation.py`     |

### 5.4 Docs — 1 / 1
| Tool                | Status | Notes                                                     |
| ------------------- | ------ | --------------------------------------------------------- |
| `search_flux_docs`  | ✅     | GitHub code search by default; requires `GITHUB_TOKEN`. URL template overridable via `--flux-docs-search-url` / `FLUX_MCP_DOCS_SEARCH_URL`. |

## Prompts — 2 / 2
`DynamicMCPServer` scans `src/prompts/` after `src/tools/` (fail-fast on
import errors, same as tools).
| Prompt                       | Status | File                                            |
| ---------------------------- | ------ | ----------------------------------------------- |
| `debug_flux_kustomization`   | ✅     | `src/prompts/debug_flux_kustomization.py`       |
| `debug_flux_helmrelease`     | ✅     | `src/prompts/debug_flux_helmrelease.py`         |

## Cross-cutting

| Area                                      | Status |
| ----------------------------------------- | ------ |
| `core/config.py` — runtime singleton      | ✅     |
| `core/flux_types.py` — GVK constants      | ✅     |
| `core/k8s_client.py` — kubeconfig + in-cluster + DynamicClient | ✅ |
| `core/scopes.py` — `(read_only, in_cluster)` gating | ✅ |
| `core/secrets.py` — masking helpers       | ✅     |
| Impersonation flags (`--kube-as*`) wired into client | ❌ |
| Audit log (JSON line to stderr on write)  | ✅     |
| `GET /healthz` endpoint                   | ✅     |
| `kmcp.yaml` runtime block (transport/port/args) | ❌ — passed via `--args` in Makefile |
| Unit tests for new tools                  | ❌     |
| Kind-based E2E                            | ❌     |

## Deployment & ops — done
- `deploy/rbac.yaml` (read + write ClusterRoles, SA `flux-vanilla-mcp` in `default`)
- `deploy/kagent-example.yaml` (`Accepted=True` on live cluster via
  `RemoteMCPServer` in `kagent` namespace pointing at the in-cluster Service)
- `Makefile` (sync / build / rbac / deploy / logs / port-forward / smoke / clean)
- Live: `flux-debugger` Agent reaches MCP through the `RemoteMCPServer`

---

## Image versioning — current concern

### Why `:latest` is fragile here

The image is currently published as `registry.traefik.home.oydev.me/flux-vanilla-mcp:latest`. Problems specific to this stage:

1. **No clear "what's running"**: pulling `:latest` twice at different times yields different binaries. After a `make build && make deploy` cycle, `kubectl describe pod` still shows `image: ...:latest` — gives you zero forensic signal.
2. **Kubernetes caches**: even with `imagePullPolicy: Always` (the K8s default *only* for the `:latest` tag), the kubelet can serve a cached copy if it doesn't see a digest change in flight. On a busy node this hides freshly-pushed builds.
3. **No rollback**: you can't say "go back to what we had two builds ago" — the previous bits are gone from the tag.
4. **No way to pin kagent to a known-good MCP**: if today's `:latest` breaks `get_flux_status`, the Agent on your cluster breaks with it.

### Recommendation (Docker-only, no git)

Use a **timestamp-based version tag** for every build, and treat `:latest` as a *moving alias* you can choose to update or not.

```
registry.traefik.home.oydev.me/flux-vanilla-mcp:dev-20260521-1530
registry.traefik.home.oydev.me/flux-vanilla-mcp:dev-20260521-1545
registry.traefik.home.oydev.me/flux-vanilla-mcp:dev-20260521-1612
                                              :latest   ← only updated when you decide
```

Benefits:
- Each `make build` produces a unique image; each `make deploy` is a real rollout (because the `image:` field in the Deployment changes — kubelet will pull).
- Rollback is `make deploy VERSION=dev-20260521-1530`.
- `kubectl describe` tells you exactly what's running.
- `:latest` stays as a convenience tag for ad-hoc `docker pull` from your laptop.

### Promotion mental model

| Tag prefix | Meaning                                                          |
| ---------- | ---------------------------------------------------------------- |
| `dev-*`    | One per build during development. Disposable. Garbage-collect freely. |
| `:latest`  | "Last thing I ran locally." Optional alias, never relied on by code. |
| `v0.1.0`   | First intentional release. Bumped manually in `pyproject.toml`/`kmcp.yaml`. Immutable. |
| `v0.1.1`   | Bug-fix bump. Immutable.                                         |
| `:stable`  | Optional moving alias to the latest `vX.Y.Z` you trust. Bind kagent to this. |

For the homelab right now you only need `dev-*` + an optional manual `:latest` push. SemVer tags come in once a tool is "done enough that breaking it would annoy you tomorrow."

### Registry hygiene (Talos/registry-on-Pi)

The Pi-hosted registry will fill up with `dev-*` images. Plan:
- Keep the **last N** dev tags (e.g. 10).
- Garbage-collect older ones with `regctl tag rm` or by running `registry garbage-collect` on the registry container after deleting the manifests.
- No automation needed for an MVP — `regctl tag ls` + manual delete every few weeks is fine.

### Action item — Makefile

The Makefile will be updated so that:
- `VERSION` defaults to a timestamp (`dev-YYYYMMDD-HHMMSS`).
- `IMG` is derived from `VERSION`.
- `make build` pushes only the versioned tag.
- `make deploy` uses that same `VERSION` so the new pod actually rolls.
- Optional `make promote-latest` retags + pushes `:latest`.

---

## Suggested next slice

Spec catalog is complete. Remaining polish:

1. Impersonation flags (`--kube-as`, `--kube-as-group`, `--kube-as-uid`) wired into the k8s client.
2. Basic per-tool unit tests (mock the dynamic client; cover scope-rejection paths).
3. RBAC split — `deploy/rbac-read.yaml` + `deploy/rbac-write.yaml` with separate make targets; current `rbac.yaml` always grants writes regardless of `--read-only`.
4. Confirm `kmcp deploy`-generated Pod actually uses the `flux-vanilla-mcp` SA (not `default`).
5. Update `kmcp.yaml` `runtime.args` block so the deploy command isn't living in the Makefile's `--args` string.
6. Wire `/healthz` to a kubernetes `readinessProbe` on the kmcp-generated Deployment (currently only the endpoint exists; pod probes aren't configured).
7. Set `POD_SERVICE_ACCOUNT` env var on the deployed Pod so the audit log records the real SA name instead of the `flux-vanilla-mcp` default fallback.
