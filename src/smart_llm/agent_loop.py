"""Phase F2 — provider-agnostic agent loop with native function-calling.

The loop drives a multi-turn conversation between the LLM and a set of
:class:`~smart_llm.base.ActionTool` instances.  Each iteration asks the
provider whether it wants to call a tool; if so, the loop dispatches,
feeds the result back, and repeats.  The loop terminates when the
provider emits ``stop_reason == "end_turn"`` (Anthropic) or produces no
tool calls (OpenAI/Gemini).

Public surface
--------------
:func:`run_agent_loop` — entry point called by
:class:`~smart_llm.agent.Agent`.run_with_skills`` when ActionTools are
in the resolved skill set.

Provider contract
-----------------
Each provider adds a ``call_with_tools(system_prompt, messages,
action_tools) -> AgentTurn`` coroutine.  This module remains provider-
agnostic — it calls :func:`_provider_call_with_tools` which does a duck-
type dispatch to the provider's method.
"""

import inspect
import json
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast

from .tracing import model_call_span, tool_call_span

log = logging.getLogger(__name__)

# G1 — cache (per tool class) whether its run_action opts into the optional
# InvocationContext, so we only pass ``ctx`` to tools that declare it.
_RUN_ACTION_ACCEPTS_CTX: dict[type, bool] = {}


def _accepts_ctx(tool_instance: Any) -> bool:
    cls = type(tool_instance)
    if cls not in _RUN_ACTION_ACCEPTS_CTX:
        try:
            params = inspect.signature(tool_instance.run_action).parameters
            _RUN_ACTION_ACCEPTS_CTX[cls] = "ctx" in params or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            )
        except (TypeError, ValueError):
            _RUN_ACTION_ACCEPTS_CTX[cls] = False
    return _RUN_ACTION_ACCEPTS_CTX[cls]


# Maximum tool-call rounds before we bail out with a RuntimeError.
# Each iteration counts as one round regardless of how many parallel
# tool calls the provider emits.
_DEFAULT_MAX_ITER = 10


def _ungated_tools_allowed() -> bool:
    """Escape hatch: when ``SMART_LLM_ALLOW_UNGATED_TOOLS`` is truthy, the loop
    dispatches write/external tools even without a policy gate (legacy behaviour).
    Default off → side-effecting tools are denied when no gate is wired."""
    return os.environ.get("SMART_LLM_ALLOW_UNGATED_TOOLS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _tool_risk(tool_instance: Any) -> str:
    """The tool's risk tier (read/write/external), defaulting to the safe
    ``write`` when a tool doesn't declare one."""
    cls = type(tool_instance)
    try:
        return cls.effective_risk() if hasattr(cls, "effective_risk") else "write"
    except Exception:  # noqa: BLE001
        return "write"


@dataclass
class LoopGuards:
    """G2 — configurable robustness guards for the tool-calling loop.

    All default to today's behaviour:
    - ``per_tool_call_cap`` (+ per-tool ``per_tool_overrides``): max times one
      tool may run across the loop; further calls are short-circuited with the
      tool's cached prior result + a "stop calling this tool" note instead of
      re-running. ``None`` = unlimited.
    - ``finalize_on_cap``: when the tool-turn budget (``max_iterations``) is
      exhausted, make ONE final provider call with tools unbound + a finalize
      nudge so a text answer is still returned, rather than raising.
    """

    per_tool_call_cap: int | None = None
    per_tool_overrides: dict[str, int] = field(default_factory=dict)
    finalize_on_cap: bool = False
    # M3 — per-run USD cost ceiling. When set, the loop stops and returns its
    # best text once accumulated turn cost reaches it (a per-run cap distinct
    # from the Agent's monthly budget gate). None = no per-run cap.
    max_cost_usd: float | None = None


# ── Turn representation ───────────────────────────────────────────────────────


@dataclass
class ToolCall:
    """A single tool-call block emitted by the LLM."""

    id: str  # Provider-assigned call ID (used in result messages).
    name: str  # Registered tool name, e.g. ``"postgres_run_query"``.
    input: dict[str, Any]  # Raw args dict — validated against args_model in the tool.


@dataclass
class AgentTurn:
    """Parsed response from one ``call_with_tools`` invocation."""

    content: str | None  # Final text (None during tool-use rounds).
    tool_calls: list[ToolCall]  # Empty when stop_reason == "end_turn".
    stop_reason: str  # ``"end_turn"`` | ``"tool_use"`` | ``"stop"``.
    usage: dict[str, Any] = field(
        default_factory=dict
    )  # ``input_tokens`` / ``output_tokens``.


# ── Streaming events (Tech-debt #5 / F2 streaming follow-up) ─────────────────
#
# ``stream_with_tools`` yields a discriminated union of dicts. Each
# event has a ``type`` discriminator; consumers (the agent loop, the
# WebSocket router, frontend handler) branch on it.
#
# Event types — alphabetical, all dicts so they JSON-serialize for
# the WebSocket transport without further work:
#
#   {"type": "text_delta", "delta": str}
#     Incremental text from the assistant. Stream order is
#     guaranteed; concatenate to render.
#
#   {"type": "tool_use_start", "id": str, "name": str}
#     The model decided to call a tool. Args arrive via
#     ``tool_use_input_delta`` events that follow.
#
#   {"type": "tool_use_input_delta", "id": str, "partial_json": str}
#     Incremental JSON fragment of the tool's input. Buffer per
#     id; parse when the matching ``tool_use_stop`` arrives.
#
#   {"type": "tool_use_stop", "id": str}
#     The tool-use block finished; the buffered partial_json is
#     complete and can be parsed into a ToolCall.
#
#   {"type": "turn_complete", "stop_reason": str, "usage": dict}
#     The whole assistant turn finished. ``stop_reason="end_turn"``
#     means the loop terminates; ``"tool_use"`` means dispatch the
#     accumulated tool calls and continue with another turn.
#
#   {"type": "error", "message": str}
#     Provider-side error. Stream is finished; do not consume more.


# ── Main entry point ──────────────────────────────────────────────────────────


async def run_agent_loop(
    provider: Any,
    system_prompt: str,
    user_message: str,
    action_tools: list[Any],  # list[ActionTool]
    db_session: Any,
    *,
    max_iterations: int = _DEFAULT_MAX_ITER,
    guard: Any = None,
    policy_gate: Any = None,
    ctx: Any = None,
    guards: Any = None,
    cached_prefix: Any = None,
    prompt_cache_key: Any = None,
) -> str:
    """Run a multi-turn agentic loop until the LLM produces a final text
    response or ``max_iterations`` rounds are exhausted.

    Args:
        provider:       An LLM provider instance that exposes
                        ``call_with_tools``.
        system_prompt:  System/instruction text forwarded to the provider.
        user_message:   Initial human-turn text.
        action_tools:   Resolved :class:`~smart_llm.base.ActionTool`
                        instances.  Each must have ``args_model`` and
                        ``run_action``.
        db_session:     Injected session forwarded to every
                        ``run_action`` call.
        max_iterations: Safety cap.  Raises :exc:`RuntimeError` when
                        exceeded.

    Returns:
        The LLM's final text response (empty string if the provider
        returned no text after tool-call resolution).
    """
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    # G2 — per-tool call counts + last results, maintained across iterations so
    # the cap (and its cached short-circuit) apply over the whole loop.
    call_counts: dict[str, int] = {}
    last_results: dict[str, str] = {}
    # M3 — accumulated for the per-run cost cap. Decimal (estimate_cost_usd
    # returns Decimal) so the cap math is exact and never mixes float/Decimal.
    total_cost_usd: Decimal = Decimal("0")

    _prov = getattr(provider, "provider_type", None) or type(provider).__name__
    _model = getattr(provider, "model_name", None)
    for iteration in range(max_iterations):
        # One model span per loop round (a round ≈ a cycle in Strands terms).
        with model_call_span(_prov, _model):
            turn: AgentTurn = await _provider_call_with_tools(
                provider,
                system_prompt,
                messages,
                action_tools,
                cached_prefix=cached_prefix,
                prompt_cache_key=prompt_cache_key,
            )

        # Accumulate token usage onto the provider so Agent can pick it up.
        if turn.usage:
            prev = getattr(provider, "last_usage", {})
            provider.last_usage = {
                "input_tokens": prev.get("input_tokens", 0)
                + turn.usage.get("input_tokens", 0),
                "output_tokens": prev.get("output_tokens", 0)
                + turn.usage.get("output_tokens", 0),
            }

        # M3 — per-run cost cap. Accumulate this turn's cost; if we've reached
        # the ceiling, stop before dispatching another (paid) tool round and
        # return the best text we have.
        if guards is not None and getattr(guards, "max_cost_usd", None) and turn.usage:
            try:
                from smart_llm.usage import estimate_cost_usd

                prov_name = (
                    getattr(provider, "provider_type", None)
                    or type(provider).__name__.replace("Provider", "").lower()
                )
                total_cost_usd += estimate_cost_usd(
                    prov_name,
                    getattr(provider, "model_name", "") or "",
                    turn.usage.get("input_tokens", 0),
                    turn.usage.get("output_tokens", 0),
                )
            except Exception:  # noqa: BLE001 — cost estimation must never break a run
                pass
            if total_cost_usd >= Decimal(str(guards.max_cost_usd)):
                log.info(
                    "agent_loop: per-run cost cap $%.4f reached ($%.4f) — stopping",
                    guards.max_cost_usd,
                    total_cost_usd,
                )
                return turn.content or ""

        if turn.stop_reason == "end_turn" or not turn.tool_calls:
            return turn.content or ""

        # Append the assistant's tool-use block(s) to the conversation.
        messages.append(_build_assistant_turn(turn, provider))

        # Dispatch each tool call and collect results.
        results = await _dispatch_all(
            turn.tool_calls,
            action_tools,
            db_session,
            guard=guard,
            policy_gate=policy_gate,
            ctx=ctx,
            guards=guards,
            call_counts=call_counts,
            last_results=last_results,
        )

        # Append tool results so the provider can continue reasoning.
        # Providers may return a single message dict OR a list (e.g. OpenAI
        # uses one role="tool" message per call).
        tool_result_messages = _build_tool_results_turn(results, provider)
        if isinstance(tool_result_messages, list):
            messages.extend(tool_result_messages)
        else:
            messages.append(tool_result_messages)
        log.debug(
            "agent_loop: iteration %d/%d dispatched %d tool call(s)",
            iteration + 1,
            max_iterations,
            len(results),
        )

    # G2 — tool-turn budget exhausted. When finalize_on_cap is set, make one
    # final provider call with tools UNBOUND + a nudge, so a text answer is
    # guaranteed instead of raising on a stuck tool-call cycle.
    if guards is not None and getattr(guards, "finalize_on_cap", False):
        messages.append(
            {
                "role": "user",
                "content": (
                    "You have reached the tool-call limit. Do not call any more "
                    "tools. Give your best final answer now using what you have."
                ),
            }
        )
        final_turn: AgentTurn = await _provider_call_with_tools(
            provider, system_prompt, messages, []
        )
        return final_turn.content or ""

    raise RuntimeError(
        f"Agent loop exceeded max_iterations={max_iterations}. "
        "This usually means the LLM is stuck in a tool-call cycle."
    )


# ── Single-turn driver (durable autonomous path) ──────────────────────────────


async def run_one_turn(
    provider: Any,
    system_prompt: str,
    messages: list[dict[str, Any]],
    action_tools: list[Any],
    *,
    policy_gate: Any = None,
) -> dict[str, Any]:
    """Run EXACTLY ONE provider turn and return a structured result, without
    dispatching any tools. Used by the durable :class:`AgentRunWorkflow` so the
    workflow can orchestrate approvals/pauses between turns.

    Returns one of:
      ``{"status": "final", "content": str, "usage": dict}``
      ``{"status": "tool_calls", "assistant_message": dict, "usage": dict,
         "tool_calls": [{"id", "name", "input", "decision", "reason",
                          "target_company_id"}], }``

    ``decision`` is the policy-gate verdict (``allow`` | ``deny`` |
    ``approval_required``) when a gate is supplied, else ``allow``.
    """
    turn: AgentTurn = await _provider_call_with_tools(
        provider, system_prompt, messages, action_tools
    )
    usage = turn.usage or {}
    if turn.stop_reason == "end_turn" or not turn.tool_calls:
        return {"status": "final", "content": turn.content or "", "usage": usage}

    by_name: dict[str, Any] = {}
    for t in action_tools:
        by_name[type(t).__name__] = t
        reg_name = getattr(t, "_registry_name", None)
        if reg_name:
            by_name[reg_name] = t

    calls_out: list[dict[str, Any]] = []
    for call in turn.tool_calls:
        tool_instance = by_name.get(call.name)
        decision = "allow"
        reason = ""
        target_company = None
        if tool_instance is None:
            decision, reason = "deny", f"unknown tool: {call.name!r}"
        else:
            try:
                validated = tool_instance.args_model(**call.input)
            except Exception as exc:  # noqa: BLE001
                validated = None
                decision, reason = "deny", f"invalid tool args: {exc}"
            if validated is not None and policy_gate is not None:
                d = await policy_gate.evaluate(
                    tool_name=call.name,
                    tool_cls=type(tool_instance),
                    validated_args=validated,
                )
                decision, reason = d.decision, d.reason
                target_company = d.target_company_id
        calls_out.append(
            {
                "id": call.id,
                "name": call.name,
                "input": call.input,
                "decision": decision,
                "reason": reason,
                "target_company_id": target_company,
            }
        )

    return {
        "status": "tool_calls",
        "assistant_message": _build_assistant_turn(turn, provider),
        "tool_calls": calls_out,
        "usage": usage,
    }


def build_tool_results_message(
    results: list[dict[str, Any]], provider: Any
) -> dict[str, Any] | list[dict[str, Any]]:
    """Public wrapper around :func:`_build_tool_results_turn` so the durable
    workflow's activity can shape tool results in the provider's native format."""
    return _build_tool_results_turn(results, provider)


# ── Provider dispatch ─────────────────────────────────────────────────────────


def _cache_kwargs(fn: Any, cached_prefix: Any, prompt_cache_key: Any) -> dict[str, Any]:
    """G3 — forward cache hints only to providers whose method accepts them, so
    providers that haven't adopted prompt caching are unaffected."""
    out: dict[str, Any] = {}
    if cached_prefix is None and prompt_cache_key is None:
        return out
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return out
    accepts_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if cached_prefix is not None and ("cached_prefix" in params or accepts_kw):
        out["cached_prefix"] = cached_prefix
    if prompt_cache_key is not None and ("prompt_cache_key" in params or accepts_kw):
        out["prompt_cache_key"] = prompt_cache_key
    return out


async def _provider_call_with_tools(
    provider: Any,
    system_prompt: str,
    messages: list[dict[str, Any]],
    action_tools: list[Any],
    *,
    cached_prefix: Any = None,
    prompt_cache_key: Any = None,
) -> AgentTurn:
    """Duck-type dispatch to the provider's ``call_with_tools`` method."""
    fn = getattr(provider, "call_with_tools", None)
    if fn is None:
        provider_name = type(provider).__name__
        raise NotImplementedError(
            f"Provider {provider_name!r} does not implement call_with_tools. "
            "Upgrade the provider or use a provider that supports F2."
        )
    result = await fn(
        system_prompt,
        messages,
        action_tools,
        **_cache_kwargs(fn, cached_prefix, prompt_cache_key),
    )
    return cast(AgentTurn, result)


# ── Tool execution ────────────────────────────────────────────────────────────


async def _dispatch_all(
    tool_calls: list[ToolCall],
    action_tools: list[Any],
    db_session: Any,
    *,
    guard: Any = None,
    policy_gate: Any = None,
    ctx: Any = None,
    guards: Any = None,
    call_counts: dict[str, int] | None = None,
    last_results: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Execute every tool call sequentially and return a list of result dicts.

    When ``guard`` is supplied, each tool result is screened for injection /
    abusive content (indirect-injection defense) before being handed back to
    the model; flagged results are withheld and replaced with an error marker
    so a poisoned document cannot steer the agent.

    When ``policy_gate`` (a :class:`smart_llm.security.tool_policy.ToolPolicyGate`)
    is supplied, each tool call is evaluated BEFORE dispatch. A ``deny`` or
    ``approval_required`` decision means ``run_action`` is NOT called — instead
    a synthetic tool_result is returned so the model sees a well-formed result
    and can replan. ``policy_gate=None`` preserves pre-harness behaviour.
    """
    # Index by both the registry name (used by Anthropic/OpenAI) and the class
    # name (used as a fallback when providers send class names as tool names).
    by_name: dict[str, Any] = {}
    for t in action_tools:
        by_name[type(t).__name__] = t
        # Best-effort: if the tool has a registered name attr, index that too.
        reg_name = getattr(t, "_registry_name", None)
        if reg_name:
            by_name[reg_name] = t

    results = []
    for call in tool_calls:
        tool_instance = by_name.get(call.name)
        if tool_instance is None:
            error_text = f"Unknown tool: {call.name!r}"
            log.warning("agent_loop: %s", error_text)
            results.append(
                {"tool_call_id": call.id, "name": call.name, "content": error_text}
            )
            continue
        try:
            # Validate and cast args via the tool's Pydantic model.
            validated_args = tool_instance.args_model(**call.input)
        except Exception as exc:  # noqa: BLE001
            log.error("agent_loop: tool %r arg validation failed: %s", call.name, exc)
            results.append(
                {
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": json.dumps({"error": f"invalid tool args: {exc}"}),
                }
            )
            continue

        # ── Tool-policy gate (autonomous safety harness) ──────────────────
        if policy_gate is not None:
            decision = await policy_gate.evaluate(
                tool_name=call.name,
                tool_cls=type(tool_instance),
                validated_args=validated_args,
            )
            if not decision.allowed:
                # deny / approval_required → do NOT run the tool. Surface a
                # well-formed synthetic result so the conversation stays coherent.
                payload = {
                    "status": decision.decision,
                    "reason": decision.reason,
                    "tool": call.name,
                }
                results.append(
                    {
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": json.dumps(payload),
                    }
                )
                log.info(
                    "agent_loop: tool %r %s (%s)",
                    call.name,
                    decision.decision,
                    decision.reason,
                )
                continue
        elif not _ungated_tools_allowed() and _tool_risk(tool_instance) != "read":
            # No policy gate wired: deny side-effecting (write/external) tools by
            # default so a caller that forgot to pass a gate can't dispatch them
            # ungated. read-only tools still run. Set SMART_LLM_ALLOW_UNGATED_TOOLS=
            # true to restore the legacy ungated behaviour for callers that
            # knowingly opt out.
            reason = "no policy gate configured; write/external tools denied by default"
            results.append(
                {
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": json.dumps(
                        {"status": "deny", "reason": reason, "tool": call.name}
                    ),
                }
            )
            log.warning("agent_loop: tool %r denied — %s", call.name, reason)
            continue

        # ── G2 — per-tool call cap with cached-result short-circuit ──────────
        if guards is not None and call_counts is not None:
            cap = guards.per_tool_overrides.get(call.name, guards.per_tool_call_cap)
            if cap is not None and call_counts.get(call.name, 0) >= cap:
                note = {
                    "status": "call_cap_reached",
                    "tool": call.name,
                    "message": (
                        "You have already called this tool the maximum number "
                        "of times; stop calling it and use the prior result."
                    ),
                    "prior_result": (last_results or {}).get(call.name),
                }
                results.append(
                    {
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": json.dumps(note, default=str),
                    }
                )
                log.info("agent_loop: tool %r hit per-tool call cap %d", call.name, cap)
                continue

        try:
            _risk = type(tool_instance).effective_risk()
        except Exception:  # noqa: BLE001 — non-ActionTool / missing method
            _risk = None
        with tool_call_span(call.name, risk=_risk) as _tspan:
            try:
                if ctx is not None and _accepts_ctx(tool_instance):
                    result = await tool_instance.run_action(
                        validated_args, db_session=db_session, ctx=ctx
                    )
                else:
                    result = await tool_instance.run_action(
                        validated_args, db_session=db_session
                    )
                content = json.dumps(result, default=str)
                if call_counts is not None:
                    call_counts[call.name] = call_counts.get(call.name, 0) + 1
            except Exception as exc:  # noqa: BLE001
                log.error("agent_loop: tool %r raised %s", call.name, exc)
                content = json.dumps({"error": str(exc)})
                if _tspan is not None:
                    try:
                        _tspan.set_attribute("sentinelbuild.tool.error", True)
                    except Exception:  # noqa: BLE001
                        pass
        # Indirect-injection defense: screen the tool result before it re-enters
        # the model's context. A flagged/poisoned result is withheld rather than
        # crashing the loop.
        if guard is not None:
            try:
                await guard.screen_tool_result(content)
            except Exception as exc:  # noqa: BLE001 — any safety verdict → withhold
                log.warning(
                    "agent_loop: tool %r result withheld by content safety: %s",
                    call.name,
                    exc,
                )
                content = json.dumps(
                    {"error": "tool result withheld by content safety"}
                )
        if last_results is not None:
            last_results[call.name] = content  # G2 — cache for cap short-circuit
        results.append({"tool_call_id": call.id, "name": call.name, "content": content})
    return results


# ── Multi-turn message builders ───────────────────────────────────────────────


def _build_assistant_turn(turn: AgentTurn, provider: Any) -> dict[str, Any]:
    """Build an assistant-role message from a tool-use turn.

    Each provider uses a different content shape for tool-use blocks.
    We ask the provider to build it; fall back to the Anthropic format.
    """
    fn = getattr(provider, "_build_assistant_tool_use_turn", None)
    if fn:
        return cast(dict[str, Any], fn(turn))
    # Anthropic default: content is a list of tool_use blocks.
    return {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.input,
            }
            for tc in turn.tool_calls
        ],
    }


async def run_agent_loop_stream(
    provider: Any,
    system_prompt: str,
    user_message: str,
    action_tools: list[Any],
    db_session: Any,
    *,
    max_iterations: int = _DEFAULT_MAX_ITER,
    guard: Any = None,
    policy_gate: Any = None,
    ctx: Any = None,
    guards: Any = None,
    cached_prefix: Any = None,
    prompt_cache_key: Any = None,
) -> AsyncIterator[dict[str, Any]]:
    """Streaming counterpart to :func:`run_agent_loop`.

    Yields the discriminated-union events documented at the top of
    this module. After each ``turn_complete`` with
    ``stop_reason="tool_use"``, dispatches every accumulated tool
    call, appends the results to the conversation, and starts the
    next turn — same agent-loop semantics as the non-streaming
    version, but surfaced incrementally so the UI can render text
    deltas live and surface tool calls as they happen.

    Provider requirements: must implement ``stream_with_tools`` AND
    the same ``_build_assistant_tool_use_turn`` /
    ``_build_tool_results_turn`` helpers used by ``run_agent_loop``.
    When the provider lacks ``stream_with_tools`` (currently only
    Anthropic ships it; OpenAI/Gemini follow-up), raises
    :exc:`NotImplementedError`.
    """
    fn = getattr(provider, "stream_with_tools", None)
    if fn is None:
        raise NotImplementedError(
            f"Provider {type(provider).__name__!r} does not implement "
            "stream_with_tools. Use run_agent_loop instead, or upgrade "
            "the provider."
        )

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    call_counts: dict[str, int] = {}  # G2 — per-tool cap state
    last_results: dict[str, str] = {}

    for iteration in range(max_iterations):
        # Per-turn accumulators — built up from stream events so we
        # can reconstruct the AgentTurn after the iterator completes.
        text_chunks: list[str] = []
        tool_partial: dict[
            str, dict[str, Any]
        ] = {}  # id -> {"name": str, "json_buf": str}
        turn_stop_reason: str = "end_turn"
        turn_usage: dict[str, Any] = {}

        async for event in fn(
            system_prompt,
            messages,
            action_tools,
            **_cache_kwargs(fn, cached_prefix, prompt_cache_key),
        ):
            yield event

            etype = event.get("type")
            if etype == "text_delta":
                text_chunks.append(event.get("delta", ""))
            elif etype == "tool_use_start":
                tool_partial[event["id"]] = {
                    "name": event.get("name", ""),
                    "json_buf": "",
                }
            elif etype == "tool_use_input_delta":
                slot = tool_partial.get(event["id"])
                if slot is not None:
                    slot["json_buf"] += event.get("partial_json", "")
            elif etype == "turn_complete":
                turn_stop_reason = event.get("stop_reason", "end_turn")
                turn_usage = event.get("usage", {}) or {}
            elif etype == "error":
                # Provider-side error — propagate by ending the stream.
                return

        # Accumulate token usage on the provider so Agent picks it up.
        if turn_usage:
            prev = getattr(provider, "last_usage", {}) or {}
            provider.last_usage = {
                "input_tokens": prev.get("input_tokens", 0)
                + turn_usage.get("input_tokens", 0),
                "output_tokens": prev.get("output_tokens", 0)
                + turn_usage.get("output_tokens", 0),
            }

        # End conditions — no tool calls or end_turn → we're done.
        if turn_stop_reason == "end_turn" or not tool_partial:
            return

        # Parse buffered partial_json into typed ToolCall objects.
        tool_calls: list[ToolCall] = []
        for tid, slot in tool_partial.items():
            try:
                args_dict = json.loads(slot["json_buf"]) if slot["json_buf"] else {}
            except json.JSONDecodeError:
                log.warning(
                    "agent_loop_stream: failed to parse tool input JSON for %s",
                    tid,
                )
                args_dict = {}
            tool_calls.append(ToolCall(id=tid, name=slot["name"], input=args_dict))

        # Build the assistant-tool-use turn and append.
        synthetic_turn = AgentTurn(
            content="".join(text_chunks) or None,
            tool_calls=tool_calls,
            stop_reason="tool_use",
            usage=turn_usage,
        )
        messages.append(_build_assistant_turn(synthetic_turn, provider))

        # Dispatch tool calls — same path as the non-streaming loop. Collect any
        # ui_events a tool emits (G6) and surface them as their own frames,
        # distinct from tool frames and not recorded as tool invocations.
        from smart_llm.ui_events import collect_ui_events

        with collect_ui_events() as ui_events:
            results = await _dispatch_all(
                tool_calls,
                action_tools,
                db_session,
                guard=guard,
                policy_gate=policy_gate,
                ctx=ctx,
                guards=guards,
                call_counts=call_counts,
                last_results=last_results,
            )
        for ui_ev in ui_events:
            yield ui_ev

        tool_result_messages = _build_tool_results_turn(results, provider)
        if isinstance(tool_result_messages, list):
            messages.extend(tool_result_messages)
        else:
            messages.append(tool_result_messages)
        log.debug(
            "agent_loop_stream: iteration %d/%d dispatched %d tool call(s)",
            iteration + 1,
            max_iterations,
            len(results),
        )

    # Exceeded max_iterations — emit a synthetic error event so the
    # consumer knows the stream ended without resolution.
    yield {
        "type": "error",
        "message": f"Agent loop exceeded max_iterations={max_iterations}",
    }


def _build_tool_results_turn(
    results: list[dict[str, Any]], provider: Any
) -> dict[str, Any] | list[dict[str, Any]]:
    """Build a user-role (or tool-role) message containing tool results.

    Each provider uses a different shape; we ask the provider to build
    it; fall back to the Anthropic format.
    """
    fn = getattr(provider, "_build_tool_results_turn", None)
    if fn:
        return cast(dict[str, Any] | list[dict[str, Any]], fn(results))
    # Anthropic default: user message with tool_result blocks.
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": r["tool_call_id"],
                "content": r["content"],
            }
            for r in results
        ],
    }
