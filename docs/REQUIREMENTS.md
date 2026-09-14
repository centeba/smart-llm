# smart-llm — Requirements

Status: draft · Scope: the standalone `smart-llm` package.

## 1. Purpose

Provide a single, provider-agnostic Python interface for building **agentic LLM
applications** — one that is safe by default (enforced tool policy, screened I/O),
resilient (failover, circuit breakers, key rotation), and observable (logs,
metrics, traces) — without tying the caller to any one model vendor or host
platform.

## 2. Functional requirements

### 2.1 Providers & models
- **FR-1** Support multiple providers behind one interface: Anthropic, OpenAI,
  Google Gemini, and OpenRouter.
- **FR-2** Select a provider by model name; allow explicit base-URL / client
  overrides.
- **FR-3** Fail over across providers/keys on transient errors.
- **FR-4** Manage multiple API keys per provider with **rotation** and a
  pluggable key store (in-memory by default; DB-backed via the `[db]` extra).

### 2.2 Agent loop
- **FR-5** Run a tool-calling agent loop that plans, calls tools, and integrates
  results until completion or a guard trips.
- **FR-6** Enforce **loop/cost guards** (max iterations, max cost) per run.
- **FR-7** Gate every tool call through a **policy gate** that is deny-by-default
  for write/external tools when no explicit policy is configured.

### 2.3 Tools
- **FR-8** Define tools as typed `ActionTool`s with a read/write/external **risk
  tier**.
- **FR-9** Ship built-in tools (e.g. web search, URL scraper) with per-tool
  safety (the scraper blocks private/link-local/metadata targets — SSRF egress
  guard).
- **FR-10** Adapt external **MCP** (Model Context Protocol) tool servers into
  native tools, **sanitizing** their descriptions and **fingerprint-pinning**
  their definitions to detect drift/rug-pull (via the `[mcp]` extra).

### 2.4 Safety
- **FR-11** Screen model input/output through a mandatory pipeline: prompt-
  injection filtering, moderation, and a PII firewall — each **fail-closed**.
- **FR-12** Provide per-tenant/agent **rate limiting** and SQL-safety validation
  for any db-query tool.

### 2.5 Observability & runtime
- **FR-13** One-call wiring of Prometheus `/metrics`, OTEL traces, and Sentry for
  a FastAPI app (`install_observability`), all env-gated and no-op-safe.
- **FR-14** Structured JSON logging with trace correlation (`configure_logging`)
  and deep readiness probes (`add_readiness_route`).
- **FR-15** Emit GenAI-semantic spans for agent cycles and tool dispatch.

## 3. Non-functional requirements

- **NFR-1 Provider-agnostic & standalone** — no dependency on any host platform;
  core install pulls only the provider SDKs + pydantic/fastapi/httpx.
- **NFR-2 Safe by default** — safety screens and the tool gate are on unless
  explicitly opted out; opt-outs are explicit and logged.
- **NFR-3 Optional deps stay optional** — `[db]`, `[observability]`, `[mcp]` are
  extras; the core imports and runs without them (helpers no-op).
- **NFR-4 Typed** — `mypy --strict` clean; public APIs return typed models.
- **NFR-5 Quality-gated** — ruff (lint + format), mypy strict, and pytest with a
  coverage floor run in CI on 3.10–3.12.
- **NFR-6 Resilient** — transient failures are retried; a downed vendor trips a
  per-process circuit breaker rather than cascading.

## 4. Out of scope

- Hosting/serving infrastructure (the package ships an example FastAPI app, not a
  product service).
- Vector stores / RAG orchestration beyond tool interfaces.
- A UI.

## 5. Acceptance criteria

- `pip install smart-llm` imports and runs an agent against a configured provider
  with no optional extras present.
- A write/external tool is denied when no policy gate is configured; allowed only
  under an explicit policy.
- The scraper refuses `169.254.169.254` / RFC1918 / loopback targets.
- With `OTEL_EXPORTER_OTLP_ENDPOINT` set, logs carry `trace_id` and traces export;
  unset, everything still runs.
- CI (ruff + mypy strict + pytest) is green on 3.10–3.12.
