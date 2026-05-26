# Lab-2: Agentic Dashboard, MCP та GitOps-агенти

## Початківці

### 1. Розгорнути abox

> Робив на власній інфрі (Talos Linux K8s + Vanilla Flux)

### 2. Отримати UI доступи до Flux, Kagent та agentgateway

> Із-за того, що ванільний Flux, то без UI. Kagent та Agentgateway UI були розгорнуті і заекспоужені ще в [Lab1](../Lab1/LAB.md/)

### 3. Підключити модель, створити declarative MCP tool server та агента в Kagent

> Одразу деплоїв усе через GitOps, переробив стандартного observability-agent під свій стек VictoriaMetrics/Logs, спорядивши MCP [victoriametrics-mcp](vm-mcp-remoteserver.yaml) та []().
Зіштовхнувся з проблемою, що при використання в межах того самого агента одночасно victoriametrics-mcp та victorialogs-mcp, виникав конфлікт, тому що обидва mcp мали тул з схожою назвою query. Вирішив проблему тим, що створив 3 окремі сабагенти

- [homelab-grafana-agent](./homelab-grafana-agent.yaml)
- [homelab-logs-agent](./homelab-logs-agent.yaml)
- [homelab-metrics-agent](./homelab-metrics-agent.yaml)

і обʼєднав їх в одному

- [homelab-observability-agent](./homelab-observability-agent.yaml)

![alt text](homelab-observability-agent.png)

## Досвідчені

### 1. Розгортання MCP сервера та агента за допомогою GitOps

> Виконав в [секції 3](#3-підключити-модель-створити-declarative-mcp-tool-server-та-агента-в-kagent)

## Макс

> Передивишись на оригінальне рішення на якому базувався мій flux-vanilla-mcp вже запізно виявив, що в цілому можна було застосоувати і flux-operator-mcp підтюнивши MCP, та повідключавши tools-и install_flux_instance, get_flux_instance, reconcile_flux_resourceset які використовують CRD унікальні для Flux Operator

### Development: 1. Завдання досвідчених але з власноруч розробленим MCP ( наприклад за допомогою KMCP) сервером та GitLessOps

> Підняв власний MCP сервер [`flux-vanilla-mcp`](./flux-vanilla-mcp/) на FastMCP + KMCP — інструмент для діагностики GitOps пайплайну прямо з кагентa. Покриває upstream Flux v2 CRDs (`source.toolkit.fluxcd.io`, `kustomize.toolkit.fluxcd.io`, `helm.toolkit.fluxcd.io`, `notification.toolkit.fluxcd.io`, `image.toolkit.fluxcd.io`) без залежності від `flux-operator` — тобто без `FluxInstance`/`FluxReport`, тільки CRDs які ставить `flux install`. Прототипом служив [`controlplaneio-fluxcd/flux-operator/cmd/mcp`](https://github.com/controlplaneio-fluxcd/flux-operator/tree/main/cmd/mcp), але переписаний під мою інсталяцію.

**Каталог 15 тулзів** (повний у [`docs/SPEC.md`](./flux-vanilla-mcp/docs/SPEC.md)):

- Cluster discovery: `get_flux_status`, `get_kubernetes_api_versions`, `get_kubeconfig_contexts`, `set_kubeconfig_context`
- Resource I/O: `get_kubernetes_resources`, `get_kubernetes_logs`, `get_kubernetes_metrics`, `apply_kubernetes_manifest`, `delete_kubernetes_resource`
- Flux operations (через annotation-патчі `reconcile.fluxcd.io/requestedAt` + `spec.suspend`): `reconcile_flux_source`, `reconcile_flux_kustomization`, `reconcile_flux_helmrelease`, `suspend_flux_reconciliation`, `resume_flux_reconciliation`
- Docs: `search_flux_docs` (GitHub code search по `fluxcd/website`)

Плюс 2 MCP-промпти — `debug_flux_kustomization` і `debug_flux_helmrelease`, які кодують повний chain "обʼєкт → sourceRef → events → controller logs" одним викликом.

#### Reliability-фічі

> Серверу буде доступний весь кластер через kagent, тому defense-in-depth обовʼязковий. Заклав чотири рівні:

1. **Read-only за замовчуванням.** Прапор `--read-only=true` ріже всі `apply_*`/`delete_*`/`reconcile_*`/`suspend_*`/`resume_*` на рівні застосунку (`core/scopes.py`). Write-режим вмикається окремою командою `make deploy-write`.
2. **RBAC split.** [`deploy/rbac.yaml`](./flux-vanilla-mcp/deploy/rbac.yaml) тримає дві окремі `ClusterRole` — `flux-vanilla-mcp:read` (get/list/watch на Flux CRDs, pods, logs, events, metrics) і `flux-vanilla-mcp:write` (patch на чотири Flux групи + вузький create/patch/update/delete для `apply_kubernetes_manifest`). Якщо хочеш RBAC-level enforcement замість application-level — просто не біндиш `:write`.
3. **Secret masking.** Прапор `--mask-secrets` (увімкнений by default) ріже `v1/Secret.{data,stringData}` і будь-які поля з суфіксом `password|token|key|cert` у `"***"` перед поверненням клієнту.
4. **Audit log.** Кожен write-тул емітить один JSON рядок у stderr — `{ts, tool, user, context, namespace, kind, name, durationMs, outcome}`. Видно через `kubectl logs deploy/flux-vanilla-mcp` і фільтрується по `outcome=error`.

#### Топологія в кластері

> Cross-namespace констрейнт kagent — `MCPServer` не можна референсити з іншого неймспейсу. `kmcp deploy` ставить `MCPServer` CR у `default`, а агенти живуть у `kagent`, тому довелось ввести `RemoteMCPServer`-проксі.

```
default                        kagent
┌─────────────────────────┐    ┌─────────────────────────┐
│ MCPServer               │    │ RemoteMCPServer         │
│   flux-vanilla-mcp      │◄───│   flux-vanilla-mcp      │
│ Service :8080 /mcp      │    │ url: http://...:8080/mcp│
│ Deployment (SA:         │    └───────────▲─────────────┘
│   flux-vanilla-mcp)     │                │
└─────────────────────────┘    ┌───────────┴─────────────┐
                               │ Agent                   │
                               │   flux-debugger         │
                               │ toolNames: [15 штук]    │
                               └─────────────────────────┘
```

Маніфест агента — [`deploy/kagent-example.yaml`](./flux-vanilla-mcp/deploy/kagent-example.yaml).

> Окремий gotcha: поле `toolNames` у `tools[].mcpServer` **обовʼязкове**. Без нього агент отримує **нуль** тулзів з MCP-сервера, при цьому статус залишається `Accepted=True` — мовчазний фейл. Тримаю список синхронним з `src/tools/` (за винятком `get_kubeconfig_contexts`/`set_kubeconfig_context` — вони не мають сенсу в in-cluster режимі і самі себе вимикають).

Поточний стан у кластері:

```
$ kubectl get mcpserver,remotemcpserver,agent -A | grep -E 'flux-vanilla|flux-debugger'
default     mcpserver.kagent.dev/flux-vanilla-mcp           True
kagent      remotemcpserver.kagent.dev/flux-vanilla-mcp     STREAMABLE_HTTP   http://flux-vanilla-mcp.default.svc.cluster.local:8080/mcp   True
kagent      agent.kagent.dev/flux-debugger                  Declarative   python    True    True
```

#### Image versioning

> Перше, від чого відмовився з kmcp дефолтом — `:latest`. Після другого `make build && make deploy` `kubectl describe pod` показує те саме `image: ...:latest`, але код інший — нульовий forensic signal, неможливо відкотитись.

Замість того — timestamp-теги `dev-YYYYMMDD-HHMMSS` на кожен білд:

```
registry.traefik.home.oydev.me/flux-vanilla-mcp:dev-20260526-110449
```

Поточний `MCPServer` теж тримає цей тег явно, не `:latest`:

```yaml
spec:
  deployment:
    image: registry.traefik.home.oydev.me/flux-vanilla-mcp:dev-20260526-110449
```

Тоді кожен `make deploy` — це справжній rollout (kubelet бачить нове `image:` і робить pull), а `kubectl describe pod` — це аудит-трейл "що зараз працює". Деталі мотивації в [`docs/currentstate.md`](./flux-vanilla-mcp/docs/currentstate.md).

