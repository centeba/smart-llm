# smart-llm — User Guide

A practical guide to installing and using `smart-llm`. See
[`REQUIREMENTS.md`](REQUIREMENTS.md) for scope, [`DESIGN.md`](DESIGN.md) for
architecture, and [`agent-loop.md`](agent-loop.md) for the loop internals.

## Install

```bash
pip install smart-llm                    # core (provider SDKs + agent loop)
pip install "smart-llm[db]"              # DB-backed key store / usage (SQLAlchemy)
pip install "smart-llm[observability]"   # Prometheus / OTEL / Sentry
pip install "smart-llm[mcp]"             # MCP client
```

Local development:

```bash
pip install -e ".[db,observability,mcp,test]"
```

## Configure providers

Set the key(s) for the providers you use (see [`../.env.example`](../.env.example)):

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...
export OPENROUTER_API_KEY=...
```

## Quick start

```python
import asyncio
from smart_llm import Agent, AgentManager, ContextPruningTool


async def main():
    agent = Agent(
        name="demo_agent",
        provider_type="gemini",  # anthropic | openai | gemini | openrouter
        system_prompt="You are a concise assistant.",
        api_key="...",  # or rely on the provider env var
        tools=[ContextPruningTool(max_chars=500)],
    )

    manager = AgentManager()  # optional: adds failover across agents
    manager.register_agent(agent)

    response = await manager.analyze("Summarize agentic AI in 3 bullets.")
    print(response.data)  # the model output
    print(response.metadata)  # usage / provider / cost metadata


asyncio.run(main())
```

A runnable version is in [`../examples/agent_demo.py`](../examples/agent_demo.py).

## Defining a tool (and adding integrations)

Tools are typed `ActionTool`s that declare a **risk tier** (`read`, `write`, or
`external`). Read tools dispatch freely; write/external tools require an explicit
policy (deny-by-default — see "Safety"). Subclass `ActionTool`, set its
`args_model`, implement `run_action`, and register it with `register_tool(...)`.
A complete, runnable external-API tool is in
[`../examples/custom_tool.py`](../examples/custom_tool.py).

> **Vendor integrations are intentionally not shipped.** smart-llm keeps the core
> vendor-neutral — adapters for specific services (Stripe, Gmail, Drive, …) belong
> in *your* codebase, added via the `ActionTool` pattern above or the MCP client
> (below). That keeps the package free of any single backend's credentials and
> semantics; mark such tools `risk = "external"` so the policy gate governs them.

## Safety

- **Tool policy gate** — side-effecting tools don't run unless you configure a
  policy. To knowingly opt out (legacy behaviour), set
  `SMART_LLM_ALLOW_UNGATED_TOOLS=true`.
- **Content screens** — prompt-injection, moderation, and PII screens run on I/O
  and fail closed. `SMART_LLM_SAFETY_SHADOW` affects only content screens, never
  the tool gate or PII firewall.
- **Egress** — the built-in scraper refuses private/loopback/link-local/metadata
  targets (SSRF guard).

## Observability

```python
from fastapi import FastAPI
from smart_llm.logging_config import configure_logging
from smart_llm.observability import install_observability

configure_logging(service_name="my-service")  # JSON logs + OTLP export + trace ids
app = FastAPI()
install_observability(app, service_name="my-service")  # /metrics + OTEL + Sentry
```

Everything activates only when its env is set:

| Env | Effect |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | export logs + traces (OTLP/HTTP) |
| `SENTRY_DSN` | error capture |
| `LOG_LEVEL` | verbosity: `DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL` |
| `ENVIRONMENT` | `deployment.environment` on logs + traces (omitted when unset, so the collector can supply it) |

Unset, the helpers no-op and you still get JSON logs on stdout.

### Sending to the SentinelBuild observability platform

[sentinelbuild_observability](https://github.com/centeba/sentinelbuild_observability)
takes standard OTLP, so no extra package is needed:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
ENVIRONMENT=dev
# production collector requires its ingest token:
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer%20<OTEL_INGEST_TOKEN>
```

Logs and traces arrive over OTLP. Metrics are **pulled**: add the service's
`/metrics` to the platform's `prometheus/prometheus.yml`. The `job_name` becomes
the `job` the Overview dashboard filters on:

```yaml
scrape_configs:
  - job_name: my-service
    static_configs: [{ targets: ["my-service:8000"] }]
```

## Connecting an MCP server

With the `[mcp]` extra, connect an external Model Context Protocol tool server;
its tools are adapted into native `ActionTool`s, their descriptions sanitized, and
their definitions fingerprint-pinned (a server that swaps tools after approval is
flagged). See `smart_llm.mcp.client`.

## Keys & rotation

`smart_llm.key_manager` / `key_store` manage multiple keys per provider with
rotation and failover. The default store is in-memory; the `[db]` extra provides a
SQLAlchemy-backed store for persistence and per-key usage accounting.

## Multi-provider failover (AgentManager)

There are **two independent resilience layers**, and they compose:

| Layer | Scope | Owner | Triggers |
|---|---|---|---|
| **Key rotation** | *within* one provider | `KeyManager` (§ Keys & rotation) | a key is rate-limited / invalid |
| **Provider failover** | *across* providers | `AgentManager` | a whole provider errors or its circuit is open |

`AgentManager` holds a pool of agents and tries them **in registration order**
until one succeeds — so to fail from Anthropic over to OpenRouter, register an
Anthropic agent first and an OpenRouter agent second:

```python
from smart_llm import Agent, AgentManager

primary = Agent(
    name="primary",
    provider_type="anthropic",
    system_prompt="You are a concise assistant.",
)
fallback = Agent(
    name="fallback",
    provider_type="openrouter",
    system_prompt="You are a concise assistant.",
)

manager = AgentManager()
manager.register_agent(primary)  # tried first
manager.register_agent(fallback)  # tried only if primary fails / is circuit-open

response = await manager.analyze("Summarize agentic AI in 3 bullets.")
```

How a call flows through the sequence (`AgentManager.analyze` /
`analyze_image`):

1. **Circuit check first.** Each provider has a shared breaker keyed
   `llm-<provider_type>`. If it's **open**, that agent is skipped immediately
   (no request burned waiting for a timeout) and the manager moves to the next.
2. **Call inside a `resilient_section`** (`failure_threshold=5`,
   `recovery_timeout=30s`). Success returns straight away.
3. **On failure**, the manager rotates the failed provider's keys
   (`key_manager.rotate_on_failure(provider_type)`), records the breaker miss,
   and falls over to the next agent in the sequence.
4. **If every agent fails**, the last underlying error is re-raised; if every
   agent was skipped because its circuit was open, a `RuntimeError` is raised
   naming the open providers (wait for breaker recovery).

Because breakers are **per-provider and shared**, registering several agents on
the *same* provider only adds key/config variety — it does not add vendor
redundancy. For true redundancy, give each fallback a **different**
`provider_type`. (Same-provider agents are still useful for A/B configs or
distinct system prompts — see `smart_llm/api/main.py` for a paired example.)

## Persistence & schema (agents, skills, keys, usage/budgets)

smart-llm defines its tables as **ORM models bound to a host-provided declarative
`Base`**, not as migrations — the package is a library, so the host app owns
schema creation. The models:

- `smart_llm.db.models` — `ai_skills`, `ai_agent_configs`, `ai_agent_skill_links`,
  `ai_agent_grants`, `ai_skill_grants`, `agent_runs`, `agent_action_audit`.
- `smart_llm.models` — `llm_api_keys`.
- `smart_llm.usage.make_usage_model(Base)` — the **`ai_usage_events`** ledger that
  powers usage & budgets (usd_cost, tokens, company_id, created_at); budget
  enforcement lives in `smart_llm.usage` (`UsageContext`, `BudgetExceededError`).

### Batteries-included (standalone)

`smart_llm.db.schema` bundles every table onto one `Base` (needs the `[db]` extra):

```python
from sqlalchemy import create_engine
from smart_llm.db.schema import create_all

create_all(create_engine("postgresql+psycopg://user:pw@host/db"))
```

Or use the bundled **Alembic baseline** (repo-root `alembic.ini` + `alembic/`):

```bash
pip install -e ".[db]"
DATABASE_URL="postgresql+psycopg://user:pw@host/db" alembic upgrade head
```

Either path creates `ai_usage_events` (usage/budgets), `llm_api_keys`,
`ai_agent_configs`, `ai_skills`, the grant/link tables, `agent_runs`, and
`agent_action_audit`. After the baseline, evolve the schema with normal
`alembic revision --autogenerate`.

### Bring-your-own Base (embedding in a host app)

If your app already owns a `Base` + migrations, **don't import `schema`** — bind
the factories to your Base and manage them with your own migrations instead:

```python
from smart_llm.db.models import make_ai_models
from smart_llm.usage import make_usage_model

ai_models = make_ai_models(host_base)  # agent/skill/grant/run/audit models
AIUsageEvent = make_usage_model(host_base)  # ai_usage_events ledger
```

## Admin UIs

Two optional front-ends render agents / skills / LLM keys / usage & budgets:

- **Flutter** — [`../flutter_package`](../flutter_package) (`smart_llm_ui`): provide
  an authenticated `Dio` via `smartLlmDioProvider` and use `AgentsScreen`,
  `SkillsScreen`, `LlmKeysScreen`, `UsageScreen`.
- **React** — [`../react-admin`](../react-admin): `npm install && npm run dev`
  (dev-proxies `/api` to your service); build with `npm run build`.

Both read the same endpoints (`/api/v1/ai-agents`, `ai-skills`,
`ai-agents/llm-keys`, `ai-usage/cost-dashboard`).

## Development

```bash
ruff check . && ruff format --check .     # lint + format
mypy src                                  # strict types
pytest                                    # tests + coverage floor
```

CI runs all of the above on Python 3.10–3.12 (`.github/workflows/ci.yml`).
