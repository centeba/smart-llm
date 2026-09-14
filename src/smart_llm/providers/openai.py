import base64
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any, cast

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionMessageFunctionToolCall,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)

from smart_llm.agent_loop import AgentTurn, ToolCall

logger = logging.getLogger(__name__)

NAME = "openai"


class OpenAIProvider:
    """OpenAI-specific LLM execution logic."""

    NAME = NAME

    def __init__(
        self,
        api_key: str,
        model_name: str = "gpt-4-turbo-preview",
        base_url: str | None = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=base_url)
        # Populated by :meth:`complete` for the host's usage recorder.
        self.last_usage: dict[str, Any] = {"input_tokens": 0, "output_tokens": 0}

    # ── Subclass seams (OpenRouter overrides these) ─────────────────────────
    def _extra_create_kwargs(self) -> dict[str, Any]:
        """Extra kwargs merged into every ``chat.completions.create()`` call.

        Default empty — the direct-OpenAI path is unchanged. OpenRouter uses
        it to request per-request usage/cost accounting.
        """
        return {}

    def _capture_provider_cost(self, response: Any) -> None:
        """Record a provider-reported USD cost onto ``last_usage['cost_usd']``.

        Default no-op — a direct OpenAI response carries no dollar cost. For a
        streaming call the ``response`` is the final usage-bearing chunk.
        OpenRouter overrides this to read ``response.usage.cost``.
        """
        return None

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str | list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Executes a completion and returns parsed JSON.

        ``user_prompt`` accepts either a single string (single-turn,
        wrapped as a user message) or a list of ``{"role", "content"}``
        message dicts (Phase SLM2 native multi-turn). The system prompt
        is always prepended; if the caller-supplied list already
        contains a ``"system"`` message, the explicit system_prompt
        wins to keep agent identity stable.
        """
        if isinstance(user_prompt, str):
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        else:
            # Drop any caller-supplied "system" turn so our agent identity
            # isn't accidentally overridden.
            history = [m for m in user_prompt if m.get("role") != "system"]
            messages = [{"role": "system", "content": system_prompt}, *history]
        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=cast(list[ChatCompletionMessageParam], messages),
                response_format={"type": "json_object"},
                **self._extra_create_kwargs(),
            )
            usage = getattr(response, "usage", None)
            self.last_usage = {
                "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            }
            self._capture_provider_cost(response)
            return cast(dict[str, Any], json.loads(response.choices[0].message.content or ""))
        except Exception as e:
            logger.error(f"OpenAI error: {e!s}")
            raise e

    async def complete_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> list[dict[str, Any]]:
        """Vision completion — returns a list of dicts parsed from JSON output.

        Note: OpenAI rejects response_format={"type":"json_object"} when the
        request contains image_url content, so we parse the raw text instead.
        """
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:{mime_type};base64,{b64}"
        try:
            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_uri}},
                            {
                                "type": "text",
                                "text": f"{system_prompt}\n\n{user_prompt}",
                            },
                        ],
                    }
                ],
                **self._extra_create_kwargs(),
            )
            usage = getattr(response, "usage", None)
            self.last_usage = {
                "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
            }
            self._capture_provider_cost(response)
            return self._parse_json_array(response.choices[0].message.content or "[]")
        except Exception as e:
            logger.error(f"OpenAI vision error: {e!s}")
            raise

    def _parse_json_array(self, text: str) -> list[dict[str, Any]]:
        """Extract a JSON array or object from model output, stripping markdown fences."""
        text = text.strip()
        # Strip markdown fences
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if fence:
            text = fence.group(1).strip()
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return cast(list[dict[str, Any]], parsed)
        if isinstance(parsed, dict):
            # Unwrap {"results": [...]} or return as single-element list
            return cast(list[dict[str, Any]], parsed.get("results", [parsed]))
        return []

    async def call_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        action_tools: list[Any],
    ) -> AgentTurn:
        """Phase F2 — OpenAI native tool-calling (function-calling API).

        Returns an :class:`~smart_llm.agent_loop.AgentTurn`.
        """
        tool_specs = [
            {
                "type": "function",
                "function": {
                    "name": type(t).__name__,
                    "description": getattr(t, "description", "") or "",
                    "parameters": t.args_model.model_json_schema(),
                },
            }
            for t in action_tools
        ]

        oai_messages = [{"role": "system", "content": system_prompt}] + messages
        response = await self.client.chat.completions.create(
            model=self.model_name,
            messages=cast(list[ChatCompletionMessageParam], oai_messages),
            tools=cast(list[ChatCompletionToolParam], tool_specs),
            **self._extra_create_kwargs(),
        )

        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        self.last_usage = {
            "input_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
        }
        self._capture_provider_cost(response)

        tool_calls_raw = choice.message.tool_calls or []
        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                input=json.loads(tc.function.arguments),
            )
            for tc in tool_calls_raw
            if isinstance(tc, ChatCompletionMessageFunctionToolCall)
        ]
        return AgentTurn(
            content=choice.message.content,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=self.last_usage.copy(),
        )

    def _build_assistant_tool_use_turn(self, turn: AgentTurn) -> dict[str, Any]:
        """OpenAI multi-turn: assistant role with tool_calls list."""
        return {
            "role": "assistant",
            "content": turn.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.input),
                    },
                }
                for tc in turn.tool_calls
            ],
        }

    def _build_tool_results_turn(
        self, results: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """OpenAI multi-turn: each tool result is a separate role=``tool``
        message.  The agent loop handles list returns by extending messages."""
        return [
            {
                "role": "tool",
                "tool_call_id": r["tool_call_id"],
                "content": r["content"],
            }
            for r in results
        ]

    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        action_tools: list[Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Phase F2 streaming follow-up — OpenAI tool-calling SSE.

        Yields the discriminated-union events documented in
        :mod:`smart_llm.agent_loop` (``text_delta``, ``tool_use_start``,
        ``tool_use_input_delta``, ``tool_use_stop``, ``turn_complete``,
        ``error``).

        OpenAI's streaming chunked tool-call shape:
        - ``chunk.choices[0].delta.content`` — text deltas
        - ``chunk.choices[0].delta.tool_calls`` — list of
          ``{index, id?, function: {name?, arguments?}}`` entries.
          The ``index`` field stays stable across chunks; ``id`` and
          ``function.name`` arrive on the first chunk that references
          the call; ``function.arguments`` arrives in JSON-fragment
          pieces across many chunks.
        - ``chunk.choices[0].finish_reason`` becomes truthy on the
          terminal chunk (``"tool_calls"`` or ``"stop"``).
        - ``chunk.usage`` is only populated when
          ``stream_options.include_usage = True``.
        """
        tool_specs = [
            {
                "type": "function",
                "function": {
                    "name": type(t).__name__,
                    "description": getattr(t, "description", "") or "",
                    "parameters": t.args_model.model_json_schema(),
                },
            }
            for t in action_tools
        ]

        # Track per-index call metadata so deltas can be routed
        # without needing the id to appear on every chunk.
        index_to_id: dict[int, str] = {}
        index_seen_start: set[int] = set()
        finish_reason: str = "stop"
        usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

        oai_messages = [{"role": "system", "content": system_prompt}] + messages

        try:
            stream = await self.client.chat.completions.create(
                model=self.model_name,
                messages=cast(list[ChatCompletionMessageParam], oai_messages),
                tools=cast(list[ChatCompletionToolParam], tool_specs),
                stream=True,
                stream_options={"include_usage": True},
                **self._extra_create_kwargs(),
            )
            async for chunk in stream:
                # Usage is sent on the final stream message (after all
                # choices have finished). ``choices`` may be empty.
                ev_usage = getattr(chunk, "usage", None)
                if ev_usage is not None:
                    usage["input_tokens"] = int(
                        getattr(ev_usage, "prompt_tokens", 0) or 0
                    )
                    usage["output_tokens"] = int(
                        getattr(ev_usage, "completion_tokens", 0) or 0
                    )
                    # Gateway cost (OpenRouter) rides on the final usage chunk.
                    self._capture_provider_cost(chunk)
                    if "cost_usd" in self.last_usage:
                        usage["cost_usd"] = self.last_usage["cost_usd"]

                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                choice = choices[0]
                fr = getattr(choice, "finish_reason", None)
                if fr:
                    finish_reason = fr

                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                # Text content delta.
                text = getattr(delta, "content", None)
                if text:
                    yield {"type": "text_delta", "delta": text}

                # Tool-call deltas (list, may be empty).
                tcs = getattr(delta, "tool_calls", None) or []
                for tc in tcs:
                    idx = getattr(tc, "index", None)
                    if idx is None:
                        continue
                    tc_id = getattr(tc, "id", None)
                    fn = getattr(tc, "function", None)
                    name = getattr(fn, "name", None) if fn else None
                    args_delta = getattr(fn, "arguments", None) if fn else None

                    # First chunk for this index — emit start.
                    if idx not in index_seen_start:
                        # Some chunks may give name without id (rare).
                        # We need an id to route subsequent deltas;
                        # synthesise one when missing.
                        if not tc_id:
                            tc_id = f"call_{idx}"
                        index_to_id[idx] = tc_id
                        index_seen_start.add(idx)
                        yield {
                            "type": "tool_use_start",
                            "id": tc_id,
                            "name": name or "",
                        }
                    elif tc_id and idx in index_to_id and tc_id != index_to_id[idx]:
                        # Provider belatedly assigned an id — re-map.
                        index_to_id[idx] = tc_id

                    if args_delta:
                        yield {
                            "type": "tool_use_input_delta",
                            "id": index_to_id[idx],
                            "partial_json": args_delta,
                        }

            # Stream finished — emit tool_use_stop for every started
            # call (OpenAI doesn't have a per-block stop event), then
            # turn_complete with the mapped stop_reason.
            for idx, tc_id in index_to_id.items():
                yield {"type": "tool_use_stop", "id": tc_id}
            mapped_reason = "tool_use" if finish_reason == "tool_calls" else "end_turn"
            self.last_usage = usage.copy()
            yield {
                "type": "turn_complete",
                "stop_reason": mapped_reason,
                "usage": usage,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("OpenAI stream_with_tools error: %s", e)
            yield {"type": "error", "message": str(e)}

    async def stream(
        self,
        system_prompt: str,
        user_prompt: str | list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        """Phase-E3 — yield delta content chunks from OpenAI streaming.

        Requests ``stream_options.include_usage`` so the final chunk carries
        token counts (and, for OpenRouter, the reported dollar cost); these are
        stored on :attr:`last_usage` for the host's usage recorder. Accepts a
        single string or a pre-built message list (multi-turn)."""
        if isinstance(user_prompt, str):
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        else:
            history = [m for m in user_prompt if m.get("role") != "system"]
            messages = [{"role": "system", "content": system_prompt}, *history]
        stream = await self.client.chat.completions.create(
            model=self.model_name,
            messages=cast(list[ChatCompletionMessageParam], messages),
            stream=True,
            stream_options={"include_usage": True},
            **self._extra_create_kwargs(),
        )
        async for chunk in stream:
            # Usage rides on the terminal chunk, whose ``choices`` is empty.
            ev_usage = getattr(chunk, "usage", None)
            if ev_usage is not None:
                self.last_usage = {
                    "input_tokens": int(getattr(ev_usage, "prompt_tokens", 0) or 0),
                    "output_tokens": int(getattr(ev_usage, "completion_tokens", 0) or 0),
                }
                self._capture_provider_cost(chunk)
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            try:
                delta = choices[0].delta.content
            except (IndexError, AttributeError):
                delta = None
            if delta:
                yield delta
