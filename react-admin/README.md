# smart-llm admin (React)

A small React + TypeScript admin UI for smart-llm — the web counterpart to the
Flutter package in [`../flutter_package`](../flutter_package). Displays **agents**,
**skills**, **LLM keys**, and **usage & budgets**, reading the same API:

| View | Endpoint |
|---|---|
| Agents | `GET /api/v1/ai-agents/` |
| Skills | `GET /api/v1/ai-skills/` |
| LLM Keys | `GET /api/v1/ai-agents/llm-keys/` |
| Usage & Budgets | `GET /api/v1/ai-usage/cost-dashboard` |

## Develop

```bash
npm install
VITE_API_TARGET=http://localhost:8000 npm run dev   # dev server proxies /api -> your smart-llm service
```

Open http://localhost:5173. A bearer token in `localStorage.smart_llm_token` is
sent as `Authorization: Bearer …` when present.

## Build / typecheck

```bash
npm run build       # tsc -b && vite build  -> dist/
npm run typecheck
```

## Deploy

`npm run build` emits a static `dist/`. Serve it behind the same origin as the
smart-llm API (or set `VITE_API_BASE` at build time to an absolute API base).
