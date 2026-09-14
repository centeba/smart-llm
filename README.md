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
from smart_llm.agent import Agent

agent = Agent(model_name="claude-sonnet-4-5")           # provider inferred from the model
reply = await agent.run("Summarize the attached ticket", tools=[...])
```

Set provider keys via env (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GOOGLE_API_KEY`, `OPENROUTER_API_KEY`) — see [`.env.example`](.env.example).

## Observability

```python
from fastapi import FastAPI
from smart_llm.observability import install_observability
from smart_llm.logging_config import configure_logging

configure_logging(service_name="my-service")   # JSON logs + OTLP export + trace ids
app = FastAPI()
install_observability(app, service_name="my-service")   # /metrics + OTEL + Sentry
```

All exporters activate only when their env is set (`OTEL_EXPORTER_OTLP_ENDPOINT`,
`SENTRY_DSN`); everything is a no-op otherwise.

## Layout

- `src/smart_llm/` — the package (agent, providers, tools, security, mcp,
  observability, resilience, …).
- `examples/` — runnable examples.
- `docs/` — design and usage notes.
- `tests/` — the suite (`pytest`).

## License

MIT — see [`LICENSE`](LICENSE).
