# Flux Vanilla MCP — reusable dev / build / deploy commands.
#
# Overridable variables (highest-to-lowest precedence): CLI > env > defaults.
#   VERSION    — image tag. Defaults to dev-YYYYMMDD-HHMMSS so every build
#                produces a unique image and every deploy is a real rollout.
#   REGISTRY   — image registry host
#   REPO       — image repository (under the registry)
#   IMG        — full image ref (overrides REGISTRY/REPO/VERSION composition)
#   PLATFORM   — Docker buildx platform (talos nodes are amd64 in this setup)
#   NAMESPACE  — kube namespace the server is deployed into
#   SERVER     — MCPServer name (must match kmcp.yaml:name)
#
# Common invocations:
#   make build                                 # builds dev-<timestamp>
#   make deploy                                # deploys whatever VERSION resolved to
#   make build deploy VERSION=dev-fix-logs     # explicit tag for this iteration
#   make deploy VERSION=dev-20260521-1530      # roll back to a prior build
#   make promote-latest                        # retag current VERSION as :latest

REGISTRY  ?= registry.traefik.home.oydev.me
REPO      ?= flux-vanilla-mcp
VERSION   ?= dev-$(shell date -u +%Y%m%d-%H%M%S)
IMG       ?= $(REGISTRY)/$(REPO):$(VERSION)
IMG_LATEST ?= $(REGISTRY)/$(REPO):latest
PLATFORM  ?= linux/amd64
NAMESPACE ?= default
SERVER    ?= flux-vanilla-mcp
PORT      ?= 8080

# ---------------------------------------------------------------- local dev --

.PHONY: sync
sync: ## Install / update Python dependencies via uv
	uv sync

.PHONY: stdio
stdio: sync ## Run the MCP server locally over stdio (use from an AI assistant)
	uv run python src/main.py

.PHONY: http
http: sync ## Run the MCP server locally over HTTP on $(PORT)
	uv run python src/main.py --transport http --host 0.0.0.0 --port $(PORT)

.PHONY: http-readonly
http-readonly: sync ## Same as `http` but with --read-only=true
	uv run python src/main.py --transport http --host 0.0.0.0 --port $(PORT) --read-only

.PHONY: lint
lint: ## Run ruff + mypy
	uv run ruff check src
	uv run mypy src || true

# ----------------------------------------------------------------- kmcp ops --

.PHONY: print-image
print-image: ## Print the resolved IMG (useful for scripting)
	@echo $(IMG)

.PHONY: build
build: ## Build the container image for $(PLATFORM) and push as $(IMG)
	@echo "==> Building $(IMG)"
	kmcp build --project-dir . -t $(IMG) --platform $(PLATFORM) --push

.PHONY: build-local
build-local: ## Build the image locally (no push) as $(IMG)
	kmcp build --project-dir . -t $(IMG) --platform $(PLATFORM)

.PHONY: promote-latest
promote-latest: ## Retag $(IMG) as :latest in the registry (no rebuild)
	@command -v regctl >/dev/null 2>&1 || { \
	  echo "regctl not found. Install via 'brew install regclient' or use: docker buildx imagetools create -t $(IMG_LATEST) $(IMG)"; exit 1; }
	regctl image copy $(IMG) $(IMG_LATEST)
	@echo "==> Promoted $(IMG) -> $(IMG_LATEST)"

.PHONY: install-controller
install-controller: ## One-time: install the KMCP controller + MCPServer CRD on the cluster
	kmcp install

.PHONY: rbac
rbac: ## Apply the ServiceAccount + ClusterRole/Binding from deploy/rbac.yaml
	kubectl apply -f deploy/rbac.yaml

.PHONY: deploy-dry
deploy-dry: ## Render the MCPServer manifest without applying (review before deploy)
	kmcp deploy \
	  --namespace $(NAMESPACE) \
	  --image $(IMG) \
	  --transport http \
	  --port $(PORT) \
	  --args "src/main.py,--transport,http,--host,0.0.0.0,--port,$(PORT),--read-only" \
	  --dry-run

.PHONY: deploy
deploy: rbac ## Deploy the MCPServer to the cluster via kmcp (HTTP transport, read-only)
	kmcp deploy \
	  --namespace $(NAMESPACE) \
	  --image $(IMG) \
	  --transport http \
	  --port $(PORT) \
	  --args "src/main.py,--transport,http,--host,0.0.0.0,--port,$(PORT),--read-only" \
	  --no-inspector

.PHONY: deploy-write
deploy-write: rbac ## Deploy with WRITE tools enabled (no --read-only). RBAC write binding is already applied by `rbac`.
	kmcp deploy \
	  --namespace $(NAMESPACE) \
	  --image $(IMG) \
	  --transport http \
	  --port $(PORT) \
	  --args "src/main.py,--transport,http,--host,0.0.0.0,--port,$(PORT)" \
	  --no-inspector
	@echo
	@echo "==> Server is now write-capable. Reminder:"
	@echo "    * Add --allow-destructive to --args above if you also need to delete Namespaces / CRDs / kube-system."
	@echo "    * Uncomment the write entries in deploy/kagent-example.yaml so the Agent can see them."

.PHONY: undeploy
undeploy: ## Remove the MCPServer (RBAC stays — delete with `make rbac-delete`)
	-kubectl -n $(NAMESPACE) delete mcpserver $(SERVER) --ignore-not-found

.PHONY: rbac-delete
rbac-delete: ## Remove RBAC objects
	-kubectl delete -f deploy/rbac.yaml --ignore-not-found

.PHONY: clean-cluster
clean-cluster: undeploy rbac-delete ## Full in-cluster teardown: MCPServer + RBAC
	@echo "Cluster cleanup complete (image in registry not touched)."

.PHONY: clean-local
clean-local: ## Remove local build artifacts (.venv, __pycache__, .ruff_cache, .mypy_cache)
	rm -rf .venv .ruff_cache .mypy_cache
	find src tests -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

.PHONY: clean
clean: clean-cluster clean-local ## Full cleanup: cluster + local

# ----------------------------------------------------------- cluster checks --

.PHONY: logs
logs: ## Tail the deployed server's logs
	kubectl -n $(NAMESPACE) logs deployment/$(SERVER) -f --tail=100

.PHONY: describe
describe: ## Describe pod + service of the deployed server
	kubectl -n $(NAMESPACE) get all -l app.kubernetes.io/name=$(SERVER) -o wide
	kubectl -n $(NAMESPACE) describe deployment $(SERVER)

.PHONY: port-forward
port-forward: ## Port-forward the in-cluster server to localhost:$(PORT)
	kubectl -n $(NAMESPACE) port-forward svc/$(SERVER) $(PORT):$(PORT)

.PHONY: inspect
inspect: ## Open the MCP Inspector against the in-cluster server (requires port-forward in another shell)
	npx @modelcontextprotocol/inspector http://localhost:$(PORT)/mcp

.PHONY: smoke
smoke: ## Quick health probe: list tools via JSON-RPC against http://localhost:$(PORT)/mcp
	@curl -sS -X POST http://localhost:$(PORT)/mcp \
	  -H 'Content-Type: application/json' \
	  -H 'Accept: application/json, text/event-stream' \
	  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
	| sed 's/data: //' | head -c 4096; echo

.PHONY: smoke-health
smoke-health: ## Hit GET /healthz on http://localhost:$(PORT) — for readiness-probe wiring
	@curl -sS -w '\nHTTP_STATUS=%{http_code}\n' http://localhost:$(PORT)/healthz

# -------------------------------------------------------------------- meta --

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS=":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

.DEFAULT_GOAL := help
