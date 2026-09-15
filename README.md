# smart-llm

A generic, agentic LLM interface for Python — multi-provider, with a safety-first
agent loop, tool policy enforcement, key rotation, and first-class observability.
Standalone and dependency-clean (no host-platform coupling).

## Features

- **Multi-provider** — Anthropic, OpenAI, Google Gemini, and OpenRouter behind one
  interface, with automatic failover and per-provider key rotation.
- **Agentic loop** — tool-calling agent with cost/loop guards, a deny-by-default
  **tool policy gate**, and a mandatory safety pipeline (prompt-injection
  screening, moderation, PII firewall) that fails closed.
- **Tools** — typed `ActionTool`s with read/write/external risk tiers; built-ins
  (web search, scraper with SSRF egress guard, …) plus an **MCP client** that
  adapts external Model Context Protocol tool servers into native tools
  (descriptions sanitized + fingerprint-pinned).
- **Observability** — OTEL traces + Prometheus metrics + Sentry, structured JSON
  logging with trace correlation, and deep readiness helpers — all opt-in and
  no-op-safe (`smart_llm.observability`, `smart_llm.logging_config`,
  `smart_llm.service_runtime`).
- **Resilience** — per-host circuit breakers and retry helpers
  (`smart_llm.resilience`).

## Install

```bash
pip install smart-llm                      # core
pip install "smart-llm[db]"                # + SQLAlchemy-backed key store / usage
pip install "smart-llm[observability]"     # + Prometheus / OTEL / Sentry
pip install "smart-llm[mcp]"               # + MCP client
```

(Local dev: `pip install -e ".[db,observability,mcp,test]"`.)

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
    manager = AgentManager()  # optional failover across agents
    manager.register_agent(agent)

    response = await manager.analyze("Summarize agentic AI in 3 bullets.")
    print(response.data)  # model output
    print(response.metadata)  # usage / provider / cost


asyncio.run(main())
```

Set provider keys via env (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GOOGLE_API_KEY`, `OPENROUTER_API_KEY`) — see [`.env.example`](.env.example) — and
run the full example in [`examples/agent_demo.py`](examples/agent_demo.py).

## Documentation

- [Requirements](docs/REQUIREMENTS.md) — scope and acceptance criteria.
- [Design](docs/DESIGN.md) — architecture, safety model, extensibility.
- [User Guide](docs/USER_GUIDE.md) — install, configure, tools, observability, MCP.
- [Agent loop](docs/agent-loop.md) — the loop internals.

## Observability

```python
from fastapi import FastAPI
from smart_llm.observability import install_observability
from smart_llm.logging_config import configure_logging

configure_logging(service_name="my-service")  # JSON logs + OTLP export + trace ids
app = FastAPI()
install_observability(app, service_name="my-service")  # /metrics + OTEL + Sentry
```

All exporters activate only when their env is set (`OTEL_EXPORTER_OTLP_ENDPOINT`,
`SENTRY_DSN`); everything is a no-op otherwise.

## Admin UIs

Two optional front-ends render the same management views — **agents, skills,
LLM keys, and usage & budgets** — over the API (`/api/v1/ai-agents`, `ai-skills`,
`ai-agents/llm-keys`, `ai-usage/cost-dashboard`):

- [`flutter_package/`](flutter_package) — a Flutter/Dart package (`smart_llm_ui`).
- [`react-admin/`](react-admin) — a Vite + React + TypeScript app.

Each has its own README.

## Layout

- `src/smart_llm/` — the package (agent, providers, tools, security, mcp,
  observability, resilience, …).
- `examples/` — runnable examples.
- `docs/` — design and usage notes.
- `tests/` — the suite (`pytest`).
- `flutter_package/`, `react-admin/` — the admin UIs.

## Used by

- [**notification-hub**](https://github.com/centeba/notification-hub) — a
  multi-channel notification service (email / SMS / webhook) that builds its
  agentic AI layer, key store, usage/budgets, and observability rails on
  smart-llm.

## License

MIT — see [`LICENSE`](LICENSE).
