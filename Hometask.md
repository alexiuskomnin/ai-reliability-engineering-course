# Lab-1: Розгортання Basic Agentic Infrastructure:

Початківці:
1. Встановити agentgateway локально https://agentgateway.dev/docs/standalone/latest/deployment/binary/
2. Обрати llm провайдера https://agentgateway.dev/docs/standalone/latest/llm/providers/
3. Налаштувати config.yaml https://agentgateway.dev/docs/standalone/latest/tutorials/llm-gateway/
4. Запустити gateway та отримати доступ через UI http://localhost:15000/ui/
5. Перевірити доступ до llm та ознайомитися з фундаментальними можливостями Backends та Policy

Досвідчені
1. Виконати завдання початківців але як helm deployment в Kubernetes кластері
2. Налаштувати Secrets та ConfigMap для API ключів та конфігурації
3. Розгорнути kagent https://kagent.dev/docs/kagent/getting-started/quickstart
4. Налаштувати маршрут моделі через agentgateway
5. Перевірити роботу будь-якого вбудованого агента

Макс:
1. Виконати завдання досвідчених але з gateway API https://agentgateway.dev/docs/kubernetes/main/about/gateway-api/

Research-1: Дати оцінку ADR проекту S&T: DevOps Bot/Agent
1. Ваші питання до проекту, запропонуйте покращення та рішення

# Lab-2
Початківці (завдання на сертифікат)
1. Розгорнути abox
2. Отримати доступи до UI Flux, Kagent, agentgateway

3. Підключити модель, створити declarative MCP tool server та агента в Kagent

Досвідчені
1. Завдання початківців але розгортання MCP сервера та агента за допомогою GitOps 

Макс
Development:
1. Завдання досвідчених але з власноруч розробленим MCP ( наприклад за допомогою KMCP) сервером та GitLessOps


Research: підготовка до сесії MCP/A2A
1. Курс https://anthropic.skilljar.com/model-context-protocol-advanced-topics


Kubernetes: https://github.com/den-vasyliev/mastering-k8s
Controllers: https://github.com/den-vasyliev/k8s-controller-tutorial



# Lab-3
Початківці
Research:
1. Які реальні технічні та бізнесові кейси можуть бути імплементовані з MCP Sampling/Elicitation/MCP Apps (на вибір)

Development:
1. Ознайомитися з kmcp https://www.solo.io/blog/introducing-kmcp, розробити та задеплоїти в abox власний сервер
2. Ознайомитися з google-agents-cli https://google.github.io/agents-cli/, розробити та задеплоїти в abox власний агент з MCP власного сервера
3. Ознайомитися з використанням npx @modelcontextprotocol/inspector@0.21.1 та agents-cli playground для власного MCP серверу та agent запущеного у вашій інфраструктурі

Досвідчені
1. Завдання початківців
2. Development: Реалізувати свій MCP Apps кейс

Макс
1. Завдання досвідчених
2. Development: Реалізувати свій MCP Sampling/Elicitation кейс

# Lab-4

Початківці (завдання на сертифікат)
Research:
1. Ознайомитися із специфікацією a2a https://a2a-protocol.org
Development:
2. Реалізувати власного агента (будь який фреймовк) з Agent Card та отримати карту агента за Well-Known URI
Infrastructure:
3. Розгорнути Inventory на abox (або будь-яку альтернативу, можна на власному середовищі) та отримати перелік AI ресурсів в кластері
4. Infrastructure: розгорнути MCPG у власній AI Інфраструктурі (або аналогічний інструмент)
5. Розгорнути в abox (на власному середовищі) векторну базу даних qdrant https://github.com/qdrant/qdrant-helm

Досвідчені
1. Завдання початківців
2. Development: Реалізувати a2a task комунікацію між двома агентами

Макс
1. Завдання досвідчених
2. Development: Реалізувати a2a team з власним агентом та агентами kagent (на власний вибір) і поставьте одне завдання на виконання різними агентами комплексно

*результат завдання можна здавати у форматі ascinema з посиланням на паблік запис (не сам файл запису)