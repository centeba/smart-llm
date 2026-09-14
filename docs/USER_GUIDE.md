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

## Defining a tool

Tools are typed `ActionTool`s that declare a **risk tier** (`read`, `write`, or
`external`). Read tools dispatch freely; write/external tools require an explicit
policy (deny-by-default — see "Safety"). Subclass `ActionTool`, implement its
`run_action`, and pass it to the agent's `tools=[...]`.

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
| `ENVIRONMENT` | `deployment.environment` on signals |

Unset, the helpers no-op and you still get JSON logs on stdout.

## Connecting an MCP server

With the `[mcp]` extra, connect an external Model Context Protocol tool server;
its tools are adapted into native `ActionTool`s, their descriptions sanitized, and
their definitions fingerprint-pinned (a server that swaps tools after approval is
flagged). See `smart_llm.mcp.client`.

## Keys & rotation

`smart_llm.key_manager` / `key_store` manage multiple keys per provider with
rotation and failover. The default store is in-memory; the `[db]` extra provides a
SQLAlchemy-backed store for persistence and per-key usage accounting.

## Development

```bash
ruff check . && ruff format --check .     # lint + format
mypy src                                  # strict types
pytest                                    # tests + coverage floor
```

CI runs all of the above on Python 3.10–3.12 (`.github/workflows/ci.yml`).
