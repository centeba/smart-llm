# smart-llm — Technical Design

Status: draft · Companion to [`REQUIREMENTS.md`](REQUIREMENTS.md) and
[`agent-loop.md`](agent-loop.md).

## 1. Overview

```
                       ┌─────────────────────────── Agent ───────────────────────────┐
   caller ── run() ──▶ │  plan → tool calls → integrate results → repeat (guards)     │
                       │        │                                   ▲                  │
                       │        ▼                                   │                  │
                       │   Safety pipeline           Tool policy gate (deny-by-default)│
                       │   (injection / moderation /       │                           │
                       │    PII firewall, fail-closed)     ▼                           │
                       │                              ActionTool dispatch              │
                       └───────┬──────────────────────────┬───────────────────────────┘
                               ▼                          ▼
                    Provider abstraction         Tools: builtins + MCP-adapted
              (Anthropic/OpenAI/Gemini/OpenRouter)   (risk-tiered, egress-guarded)
                 key rotation · failover · breakers
                               │
                               ▼  observability: logs (JSON+OTLP), metrics, traces
```

## 2. Core components (`src/smart_llm/`)

- **`agent.py` / `agent_loop.py`** — the agent and its tool-calling loop; applies
  loop/cost guards, runs the safety pipeline on I/O, and dispatches tools through
  the policy gate. See [`agent-loop.md`](agent-loop.md) for the step machine.
- **`providers/`** — one adapter per vendor (`anthropic`, `openai`, `gemini`,
  `openrouter`) behind a shared base; `provider_policy.py` selects/falls-back.
- **`key_manager.py` / `key_store.py`** — multiple keys per provider with
  rotation; store is in-memory by default, DB-backed with the `[db]` extra.
- **`tool.py` / `base.py`** — `ActionTool` contract with `effective_risk()`
  (read/write/external); `builtins/` ships ready tools (web search, scraper, …).
- **`mcp/client.py`** — adapts external MCP tool servers into `ActionTool`s;
  descriptions are sanitized through the injection filter and definitions are
  fingerprint-pinned so a server that swaps tools after approval is caught.
- **`security/`** — `tool_policy.py` (the gate + `AgentRunContext`), `rate_limit.py`,
  `egress.py` (SSRF allow/deny), `prompt_injection.py`, moderation, and the PII
  firewall (`secret_envelope.py`, `envelope.py`); `sql_safety.py` validates
  db-query SQL.
- **`observability.py` / `logging_config.py` / `service_runtime.py` / `tracing.py`**
  — metrics/Sentry/OTEL wiring, structured logging with trace correlation, deep
  readiness + uniform error handling, and GenAI-semantic agent spans.
- **`resilience.py`** — per-host circuit breakers + retry helpers.
- **`api/`** — an example FastAPI app + middleware (idempotency, rate limit) and
  routers (e.g. usage/cost). Illustrative, not a product service.

## 3. Request/agent flow

1. `Agent.run(prompt, tools=…)` builds an `AgentRunContext` (policy gate, rate
   limiter, audit sink) and enters `agent_loop`.
2. Each turn: user/model content is screened (injection/moderation/PII) —
   fail-closed. The provider is invoked (with failover + breaker + key rotation).
3. Requested tool calls are resolved to `ActionTool`s and passed to the **policy
   gate**: `read` tools dispatch; `write`/`external` require an explicit allow
   (deny-by-default when no gate is configured), subject to rate limits.
4. Tool results are screened, integrated, and the loop repeats until completion or
   a guard (max iterations / max cost) trips.
5. Spans/metrics/logs are emitted throughout, correlated by `trace_id`.

## 4. Safety model

- **Deny-by-default gate** — side-effecting tools do not run without an explicit
  policy. `SMART_LLM_ALLOW_UNGATED_TOOLS=true` restores legacy ungated dispatch.
- **Fail-closed screens** — injection/moderation/PII screens block on failure
  rather than passing content through; `SMART_LLM_SAFETY_SHADOW` affects only
  content screens (never the tool gate or PII firewall).
- **Egress guard** — the scraper validates every resolved address against
  loopback/RFC1918/link-local/metadata ranges before connecting.
- **MCP trust** — external tool descriptions are neutered before the model sees
  them; definition fingerprints are pinned to detect drift.

## 5. Provider abstraction & resilience

A model name maps to a provider adapter; calls go through failover ordering with a
per-host circuit breaker and key rotation. Adding a provider = a new adapter under
`providers/` implementing the base contract; no agent-loop changes.

## 6. Observability

- **Logs** — `configure_logging()`: structlog → JSON on stdout, optional OTLP
  export, `trace_id`/`span_id` stamped for log↔trace correlation.
- **Metrics/traces** — `install_observability(app, service_name=…)`: Prometheus
  `/metrics` + OTEL traces + Sentry, all env-gated.
- **Agent spans** — `tracing.py` emits spans around agent cycles and tool
  dispatch with GenAI-semantic attributes.

## 7. Configuration

Providers via env keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`,
`OPENROUTER_API_KEY`); behavior via `SMART_LLM_*` flags; observability via the
standard `OTEL_*` / `SENTRY_DSN` / `ENVIRONMENT` env. See [`../.env.example`](../.env.example).

## 8. Extensibility

- **New tool** — subclass `ActionTool`, declare its risk tier, register it.
- **New provider** — add an adapter under `providers/`.
- **New MCP server** — connect via the MCP client; tools are adapted + pinned.
- **New backend for keys/usage** — implement the store interface (`[db]` gives a
  SQLAlchemy one).

## 9. Testing & quality

`pytest` (with `pytest-asyncio`, coverage floor), `mypy --strict` (+ pydantic
plugin), and `ruff` (lint + format) — enforced in CI across Python 3.10–3.12.
