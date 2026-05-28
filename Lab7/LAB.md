# Lab-7: Фінальна робота — "Vin's Questions"

Research: "Vin's Questions" — дослідження та оцінка власного сетапу AI-інфраструктури.

#### 1. How could we handle "agent got stuck" scenarios?

> "Stuck" дуже amibigous поняття, бо різні випадки:
>
> - **Pod завис без OOM/crash**. Класичний k8s — liveness/readiness probes на агента, щоб controller перезапустив. Для kagent-агентів я цього окремо не налаштовував, бо runtime простий, але для власних A2A-агентів з Lab2 — варто додати.
> - **Цикл агента не завершується** (нескінченний reasoning/tool-call loop). У kagent на рівні `Agent` CRD є `maxIterations` — це жорсткий запобіжник, який не дає агенту крутитися безкінечно.
> - **LLM не відповідає або відповідає дуже довго**. Тут вже agentgateway: на `TrafficPolicy` вішається `timeout` (request/idle) і `retry`. У моєму сетапі Ollama іноді "тоне" коли модель ще не warmed-up — без timeout'а агент висить хвилинами.
> - **Tool-call зависає** (наприклад, MCP-сервер мовчить). На MCP-федерації я тримаю `failureMode: FailOpen`, щоб один поламаний backend не клав весь federated endpoint. Плюс A2A-таски мають state machine (`submitted → working → completed/failed/canceled`) — підвисле завдання можна явно скасувати через `tasks/cancel`.
> Спостерігати і алертити можна через метрики agentgateway (`llm_request_duration_seconds`, `tool_call_duration`) у VictoriaMetrics. Якщо p99 поповз — є шанс зловити "stuck" до того, як на нього поскаржиться користувач.

---

#### 2. Any automatic timeout/circuit breaker patterns coming out of this framework?

> Так, agentgateway успадковує патерни envoy-style:
>
> - **Timeouts** на рівні `TrafficPolicy` / route — request timeout, idle timeout, per-try timeout для retry.
> - **Retry policy** — з backoff і умовами (на яких HTTP-кодах ретраїти; для LLM-backend-ів зазвичай 5xx + rate-limit-помилки).
> - **Outlier detection / circuit breaker** — після N послідовних помилок бекенд тимчасово ejected з пулу. Для multi-provider LLM-сетапу це ключове — щоб після кількох таймаутів OpenAI трафік пішов на fallback без участі людини.
>
> На kagent-стороні явного circuit-breaker-а немає — це не його роль, він делегує мережеві гарантії gateway-у. На рівні агента є `maxIterations` (питання 1) — це не зовсім circuit-breaker, але смислово близько.

---

#### 3. How does agentgateway handle model failover?

> Через `AgentgatewayBackend` / LLM backend, який підтримує **список моделей з пріоритетами**. Конфіг приблизно такий:
>
> ```yaml
> llm:
>   models:
>     - name: "primary"
>       provider: anthropic
>       priority: 1
>     - name: "secondary"
>       provider: openAI
>       priority: 2
>     - name: "fallback-local"
>       provider: ollama
>       params:
>         hostOverride: "ollama.talos-aw.home.oydev.me"
>       priority: 3
> ```
>
> Якщо primary повертає 5xx/429/timeout — спрацьовує retry, який бере наступну модель за пріоритетом. Failover керується тими ж `TrafficPolicy` retry-правилами. Плюс outlier detection (питання 2) тимчасово викине "хворий" провайдер з ротації.
>
> У моєму випадку failover тривіальний — все ходить в локальну Ollama, і "failover" це фактично fallback на меншу модель того ж бекенда (Gemma → Qwen). Але архітектурно весь патерн готовий.

---

#### 4. Can we automatically switch from OpenAI to Claude to local model?

> Так, це і є use-case попереднього питання. На agentgateway-у можна тримати три бекенди — Anthropic, OpenAI, локальна Ollama — і route через них по пріоритету або по cost-policy. На рівні клієнта (kagent-агента) це виглядає як одна модель з одним endpoint-ом, провайдер прихований за gateway.
>
> - **Семантика різна**: Claude часто інакше реагує на system prompt і tool-calls, ніж GPT-4. Автоматичний свіч за збоєм — ок, за якістю — ні (доведеться валідувати під кожний use-case).
> - **Context window різні** — Claude може прийняти 200k, локальний Qwen — 32k. Якщо primary падає на запиті 150k токенів, fallback просто впаде з context overflow.
> - **Tool-calling формати** — провайдери конвертуються agentgateway-єм у OpenAI-совмісний формат, але edge-кейси (parallel tool calls, structured output) поводяться неоднаково.

---

#### 5. Could we seamlessly handle the response formats from these providers?

> agentgateway грає роль — він нормалізує Anthropic Messages API, Gemini, Bedrock тощо до OpenAI Chat Completions формату. Для більшості клієнтів (включно з kagent-овим autogen-runtime) цього достатньо — вони "думають", що говорять з OpenAI, незалежно від того, хто реально обслужив запит.
>
> Де "seamlessly" ламається:
>
> - **Streaming SSE** — фрейми в Anthropic і OpenAI структурно різні (`content_block_delta` vs `delta.content`), gateway переписує, але latency-профіль і chunk boundaries можуть відрізнятися.
> - **Tool/function calling** — у моделей різна "темпераментність" щодо parallel calls та structured output. Формат на виході нормалізований, але кількість і порядок викликів — ні.
> - **Reasoning traces** (як у Ollama-овій Gemma, дивись JSON з Lab1) — це нестандартне поле, його кожен провайдер віддає по-своєму, і консьюмер має знати, що з ним робити.
>
> Тобто формат — так, поведінка — ні.

---

#### 6. Can we version the agents built from kagent?

> Native semantic versioning для агента в kagent CRD немає, але є кілька рівнів, які разом дають версіонування:
>
> - **GitOps** — `Agent` CRD лежить у Flux-репо, кожна зміна — це git commit. Це і є джерело правди версії агента. Можна тегати релізи і робити rollback через `git revert`.
> - **Image tag** для агентського runtime — якщо це власний A2A-агент (як мої з Lab2), його образ тегується semver, і це окрема вісь версіонування.
> - **`ModelConfig` як окремий CRD** — модель можна міняти незалежно від агента, тобто "версія агента" і "версія моделі" роз'єднані. На практиці зручно: тестуєш ту саму system-prompt-логіку на різних моделях.
> - **A2A Agent Card** має поле `version` — якщо власноруч заповнювати, можна публікувати semver через `.well-known/agent.json` (у моєму прикладі з Lab4 воно порожнє, варто це виправити).
>
> Що відсутнє: native registry агентів з історією версій. AgentRegistry з Lab4 показує поточний стан, але не "версія v1.2.3 → v1.3.0".

---

#### 7. Any blue/green or canary deployment patterns for agents?

> Так, кілька шляхів — кожен має свої компроміси:
>
> - **HTTPRoute weighted backends** — два `Agent`-и (стабільний і новий), один `HTTPRoute` з вагами `90/10`. Gateway API це підтримує нативно, agentgateway теж. Найпростіший канарковий патерн.
> - **A2A-рівень** — два агенти живуть на різних URL (`.well-known/agent.json` у кожного свій), оркестратор/A2A-team вибирає за skill і версією. Це більше про paralle deployment, ніж про canary.
> - **ModelConfig swap** — якщо змінилася лише модель, а не system prompt чи toolset, можна робити canary на рівні `ModelConfig` (новий `ModelConfig` → перенавести підмножину агентів).
>
> Метрики для оцінки canary — не звичайні HTTP коди, а agent-specific: success-rate на agentic-задачах, tool-call accuracy, p95 token usage. Без цих метрик автоматизована promote-decision не працює.

---

#### 8. What's the fastmcp-python framework mentioned?

> [FastMCP](https://github.com/jlowin/fastmcp) — Pythonic фреймворк для MCP-серверів, аналог FastAPI для MCP. Замість того, щоб ручками описувати JSON-RPC хендлери з SDK, пишеш декораторами:
>
> ```python
> from fastmcp import FastMCP
>
> mcp = FastMCP("homelab")
>
> @mcp.tool()
> def query_vm(query: str) -> str:
>     """Run a MetricsQL query."""
>     ...
> ```
>
> Він сам генерує JSON schema з type hints, обробляє транспорт (stdio/SSE/streamable HTTP), додає resources/prompts примітиви. Версія 2.x — це фактично "повноцінний production-grade" фреймворк (auth, middleware, server composition).
>
> Окремо: офіційний `mcp` Python SDK у себе теж має high-level API під назвою "FastMCP" — це fork/merge тієї ж кодової бази на ранньому етапі. Зараз дві гілки існують паралельно: `fastmcp` (Jeremiah Lowin, активніша) і high-level частина в `modelcontextprotocol/python-sdk`.

---

#### 9. Is it the easiest path to MCP?

> Для Python — на сьогодні так, особливо для прототипів. Якщо порівнювати:
>
> - **Raw `mcp` SDK** (low-level) — багато boilerplate, треба самостійно описувати tool listing/call хендлери.
> - **FastMCP** — мінімум коду, type hints роблять схеми, із коробки stdio+HTTP транспорти.
> - **mcp-go / typescript-sdk** — TS зручний, бо MCP сам по собі TS-first (специфікація народжувалася разом з TS-реалізацією); Go хороший для standalone-бінарників.
>
> Чи "найлегший шлях до MCP взагалі" — залежить від цілі:
>
> - Якщо треба **обгорнути існуюче REST API** як MCP — простіше взяти готовий wrapper типу `mcpo`/`mcp-openapi`.
> - Якщо треба **підключити вже існуючий MCP-сервер** (Grafana, Kubernetes, VictoriaMetrics) — нічого писати не треба, просто `kind: RemoteMCPServer` у kagent.
> - Якщо реально треба **писати свій сервер з нуля Python-ом** — FastMCP найкоротший шлях.

---

#### 10. About FinOps: how much control I can have?

> На agentgateway-стеку контроль доволі повний, бо все проходить через єдину точку:
>
> - **Облік (visibility)**: agentgateway віддає метрики per route/backend/model — `llm_prompt_tokens_total`, `llm_completion_tokens_total`, `llm_request_duration_seconds`. У моєму VictoriaMetrics це pre-aggregated по `model`, `consumer`, `agent_name` лейблах.
> - **Атрибуція (allocation)**: при заведенні `consumer` (через JWT/API-key) кожен запит несе ідентичність. Можна побудувати дашборд "tokens per team / per agent / per environment". Аналог Kubecost для AI.
> - **Контроль (enforcement)**: rate-limit і quota policies на agentgateway-у — як на rps, так і на tokens/min, tokens/day. Можна різати або 429-ити при перевищенні бюджету.
> - **Передбачення (forecast)**: маючи метрики, рахується `tokens × $/1M` по таблиці провайдер→ціна; це вже задача дашборду, не gateway-я.
>
> У моєму homelab специфіка: грошового рахунка нема (Ollama локальна), але GPU-час — це електрика на 4090, і це теж FinOps-сигнал. Чи варто гнати на хмарну модель vs локальну — питання latency × кВт × вартість kWh.

---

#### 11. Token level / per agent level

> Метрики agentgateway розрізняють обидва рівні через лейбли:
>
> - **Token-level** — `llm_prompt_tokens_total{model="...", route="..."}` і аналогічний для completion. Це сирий "паливний" сигнал.
> - **Per-agent** — лейбл `consumer` або `agent_name` (залежно від того, як налаштована автентифікація). У kagent кожен `Agent` ходить у gateway зі своєю service-identity, її можна засікти.
>
> У VictoriaMetrics збираю обидва, і робив би дашборд із breakdown-ом:
>
> ```promql
> sum by (agent_name) (rate(llm_prompt_tokens_total[5m]))
> sum by (agent_name, model) (rate(llm_completion_tokens_total[1h]))
> ```
>
> Що ще варто додати, але я поки не зробив: **per-conversation token budget** — це вже не gateway-рівень, а agentic-loop рівень (kagent / autogen runtime), де треба обірвати розмову, якщо вона з'їла N токенів.

---

#### 12. Can I implement custom cost controls?

> Так, кілька рівнів кастомізації:
>
> - **agentgateway TrafficPolicy** — нативні rate-limit і quota фільтри. Цього достатньо для більшості простих бюджетів.
> - **External authorization** — gateway уміє кидати pre-flight запит у зовнішній сервіс (OPA, custom HTTP), який перевірить "чи має цей агент бюджет на цей запит". Так можна реалізувати динамічні бюджети, які залежать від фактичного споживання за період.
> - **WASM-фільтри / custom plugin** — agentgateway успадковує envoy WASM-екстенсії; можна писати власну логіку прямо в data plane (наприклад, лімітувати на основі token estimate з tokenizer-а до того, як запит піде в модель).
> - **Admission webhook на kagent CRD-и** — на рівні K8s можна блокувати створення `Agent` з `maxIterations: 1000` або `ModelConfig` на дорогу модель без анотації-погодження.
> - **MCP-governance** (з Lab4) — це теж шар контролю, тільки сфокусований на безпеці MCP-серверів, не на $$$, але архітектурно схожий і його можна розширити cost-сигналами.

---

#### 13. Per-agent budgets or depth of Token limits

> Натомість одного "magic budget API" — комбінація:
>
> - **Hard cap на iteration**: `Agent.spec.maxIterations` у kagent — найпростіший і найдешевший лімітер. Зупиняє runaway loop, але не залежить від реального token-споживання (10 ітерацій з великим контекстом коштують більше, ніж 50 коротких).
> - **Token-rate limit per consumer** на agentgateway — обмежує токенів/хвилину для конкретного агента. Це справжній бюджет.
> - **Daily / monthly quota** — стейтфул-лічильник у gateway або у зовнішньому сервісі через external authz.
> - **Per-request size guard** — обрізати або відмовляти на запитах із надмірно великим контекстом (наприклад, агент почав підвантажувати весь репозиторій у prompt — стоп).
> - **A2A task timeout** — на рівні протоколу, не token-bound, але обмежує "глибину" опосередковано.
>
> Що **не** працює добре: спроби обмежити "глибину recursion" в agentic-loop через token-count напряму. Бо токени не лінійні до кроків — один tool-call з великою відповіддю з'їсть більше, ніж 5 простих кроків. Краще лімітувати обидві осі окремо.

---

#### 14. vLLM suitable for agents with many back and forth tool calls, or is it better for single shot inference?

> vLLM від народження спроєктований під **high-throughput batching** (PagedAttention, continuous batching) — це його основна перевага. Питання, чи agentic-патерн з 15 турами це його сильна або слабка сторона:
>
> - **На користь vLLM в agentic-режимі**: prefix caching. Кожен наступний хід агента переважно ділить з попереднім великий system prompt + історію — vLLM вміє reuse-ити KV-кеш для спільного префіксу, що дає величезний приріст TTFT на 2-й, 3-й, ..., 15-й хід. Це саме той випадок, де agentic-цикл "розкриває" сильні сторони vLLM.
> - **Проти**: vLLM оптимізований під багатокористувацький паралелізм. Якщо у тебе один агент і один тур — простіший runtime (Ollama/llama.cpp) дає той самий результат із меншим overhead-ом.
> - **Tool-calling специфіка**: vLLM має нативну підтримку tool-calling через `--enable-auto-tool-choice` та tool-parser. Працює, але не для всіх моделей (доступність парсера залежить від chat template).
>
> Висновок: для agentic-сценарію з багатьма турами і **кількома агентами одночасно** vLLM — правильний вибір саме завдяки prefix cache + batching. Для single-shot / single-user — overkill.

---

#### 15. llm-d's scheduler - helps when agents makes 15 llms calls?

> Так, і це фактично основна теза [llm-d](https://github.com/llm-d/llm-d). llm-d — це k8s-native розподілений inference поверх vLLM з власним scheduler-ом, який вирішує дві задачі, релевантні саме для agentic-сценаріїв:
>
> - **KV-cache-aware routing** — scheduler знає, на якому з реплік-pods вже лежить KV-кеш для конкретного prefix-у (system prompt + conversation history). Наступний запит того ж агента йде в той самий pod, що дає cache hit замість recompute. Для 15-кратного agentic-loop це різниця між "перший хід 2с, наступні 0.3с" і "кожен хід 2с".
> - **Disaggregated prefill / decode** — prefill (важкий, compute-bound) і decode (легкий, memory-bound) розводяться по різних подах. Це покращує throughput і latency profile, особливо коли в одного агента багато середніх запитів.
>
> Для конкретно мого homelab-кейсу (одна Ollama-нода на 4090) llm-d — оверкіл. Але якщо проєктувати multi-agent платформу на 10+ агентів з довгими ланцюжками — це той рівень scheduler-а, який відрізняє "працює, але дорого" від "працює і дешево". У зв'язці з agentgateway (роутинг провайдерів) + llm-d (роутинг всередині inference-пулу) — це чесний production-grade стек.

---
