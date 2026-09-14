# Agent loop — Phase F2 architecture

The smart-llm package supports three tool flavours and two execution
paths. This note maps the flavours to the paths so the next person
reading the package understands which knob controls what.

## Tool trinity

| Class | Lives in | Single-turn shape | Multi-turn shape | Purpose |
|---|---|---|---|---|
| `Tool` | `base.py` | `run(input_text: str) -> str` | n/a | **Prompt-shaper.** Mutates the user prompt before it hits the LLM. Pure text in, pure text out. Used by `Agent.analyze` to inject context (e.g. `RestorationContextTool` glues a profile blurb into the prompt). |
| `OutputTool` | `base.py` | `process(response: LLMResponse) -> LLMResponse` | n/a | **Post-processor.** Runs after the LLM returns. Sanitisation, schema validation, audit logging. Cannot influence the prompt — only inspect / reshape the response. |
| `ActionTool` | `base.py` | n/a — never single-turn | `run_action(args: BaseModel, *, db_session) -> dict` | **Side-effect tool.** Typed Pydantic args, real I/O. The LLM asks for them by name and the loop dispatches. This is the Phase F2 surface. |

`ActionTool` subclasses **MUST** declare a class attribute
`args_model: type[BaseModel]` — the loop hands its JSON schema to the
provider so the LLM knows what arguments to emit.

## Two execution paths

```
                   Agent.run_with_skills(input_text, skill_names)
                                │
            ┌───── resolves skills ─────┐
            │                            │
       ActionTools                  Tool / OutputTool
            │                            │
            ▼                            ▼
   ┌────────────────┐         ┌──────────────────────┐
   │ run_agent_loop │         │  Agent.analyze       │
   │  (Phase F2)    │         │  (prompt-shape only) │
   └────────────────┘         └──────────────────────┘
```

Routing happens at `agent.py:run_with_skills` — when any resolved
skill is an `ActionTool`, the call diverts to `run_agent_loop`. If
the resolved set is entirely prompt-shaping `Tool`s, the original
`analyze()` path runs unchanged.

## The loop

`run_agent_loop(provider, system_prompt, user_message, action_tools,
db_session, *, max_iterations=10)`

Each iteration:

1. Build the **tool spec list** (the loop never touches this; the
   provider's `call_with_tools` builds it from
   `t.args_model.model_json_schema()`).
2. Provider returns an `AgentTurn` with:
   - `content: str | None` — assistant text for this turn
   - `tool_calls: list[ToolCall]` — zero or more requests
   - `stop_reason: "end_turn" | "tool_use"`
   - `usage: dict` — input/output token counts (accumulated by the
     loop for cost tracking).
3. If `stop_reason == "end_turn"` (Anthropic) **or** `tool_calls` is
   empty (OpenAI/Gemini): return `content` as the final answer.
4. Otherwise: append the assistant turn + a user turn carrying each
   tool result, then iterate.

`_DEFAULT_MAX_ITER = 10` exists as a runaway-cost guardrail. The
loop raises `RuntimeError` on overflow rather than billing the user
infinity dollars.

## Provider differences

Every provider returns the same `AgentTurn`, but they speak
different wire shapes:

| Provider | Tool spec | Assistant turn | Tool result turn |
|---|---|---|---|
| Anthropic | `{name, description, input_schema}` | `{role: "assistant", content: [{type: "tool_use", id, name, input}]}` | `{role: "user", content: [{type: "tool_result", tool_use_id, content}]}` |
| OpenAI | `{type: "function", function: {name, description, parameters}}` | `{role: "assistant", tool_calls: [{id, function: {name, arguments}}]}` | `{role: "tool", tool_call_id, content}` |
| Gemini | `FunctionDeclaration` (with a JSON-schema *scrubber* — Gemini rejects `$schema`, `$defs`, `additionalProperties`, `format: "uuid"`, `anyOf` null unions) | `Content(parts=[{function_call: {name, args}}])` | `Content(parts=[{function_response: {name, response}}])` |

The loop stays format-agnostic because each provider implements
`_build_assistant_tool_use_turn(turn)` and
`_build_tool_results_turn(results)` to convert from the canonical
`AgentTurn` shape back into the provider's native messages list.

## End-to-end example

```python
from smart_llm import Agent

agent = Agent(
    name="Database Inspector",
    provider_type="anthropic",
    system_prompt="You query Postgres for the user.",
    api_key=anthropic_key,
)

# postgres_run_query is an ActionTool registered in
# smart_llm.builtins.integration_hub.
response = await agent.run_with_skills(
    "How many active rules are there in the system?",
    skill_names=["postgres_list_tables", "postgres_run_query"],
    db_session=db,
)
# response.data == {"content": "There are 42 active rules."}
```

Behind the scenes the loop ran ~3 turns: LLM asks for
`postgres_list_tables()`, sees `rules` in the result, asks for
`postgres_run_query(sql="SELECT COUNT(*) FROM rules WHERE is_active = true")`,
then composes the final natural-language answer.

## Workflow integration (mit-stack Temporal)

A Temporal workflow's `action_node` calls a single `ActionTool` via
`run_action_node` (no LLM involved). An `agent_node` instead invokes
`Agent.run_with_skills` for the configured `AIAgentConfig` — that's
the bridge that lets a workflow declare *"ask the Database Inspector
agent"* and get autonomous multi-step tool use for free.

- `services/mit-stack/backend/temporal/activities/agent_activity.py`
  — Temporal activity that POSTs to integration-hub's
  `/ai-invoke/run` endpoint.
- `services/mit-stack/backend/temporal/workflows/workflow_executor.py`
  — `case "agent_node":` dispatches to the activity.
- `services/integration-hub/.../api/routes/ai_invoke.py` — accepts
  `{agent_id | agent_name, prompt, context, company_id}` and runs
  `Agent.run_with_skills(...)` against the looked-up
  `AIAgentConfig`.

## See also

- `packages/smart-llm/src/smart_llm/agent_loop.py` — the loop itself
- `packages/smart-llm/src/smart_llm/base.py` — `Tool`, `OutputTool`,
  `ActionTool` ABCs
- `packages/smart-llm/src/smart_llm/builtins/integration_hub/` — the
  16 ActionTool subclasses shipped today (Postgres, Gmail, Outlook,
  Drive, Stripe, Datadog, Elasticsearch)
- `packages/smart-llm/tests/test_agent_loop.py` — 16 tests covering
  the loop's dispatch, termination, max_iterations, and the multi-
  turn message-building helpers
