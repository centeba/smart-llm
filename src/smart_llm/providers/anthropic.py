import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any, cast

from anthropic import AsyncAnthropic
from anthropic.types import MessageParam, TextBlock, ToolParam, ToolUseBlock

from smart_llm.agent_loop import AgentTurn, ToolCall

logger = logging.getLogger(__name__)

NAME = "anthropic"

# Phase SLM1 — single source for the default. Hosts that want to bump
# the cap set ``SMART_LLM_MAX_TOKENS`` in their env; per-instance
# overrides flow via ``AnthropicProvider(..., max_tokens=...)``.
_DEFAULT_MAX_TOKENS = 4096


def _resolve_max_tokens(explicit: int | None) -> int:
    if explicit is not None:
        return int(explicit)
    raw = os.getenv("SMART_LLM_MAX_TOKENS")
    if raw is None or raw.strip() == "":
        return _DEFAULT_MAX_TOKENS
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "SMART_LLM_MAX_TOKENS=%r is not an integer; falling back to %d",
            raw,
            _DEFAULT_MAX_TOKENS,
        )
        return _DEFAULT_MAX_TOKENS


class AnthropicProvider:
    """Anthropic-specific LLM execution logic."""

    NAME = NAME

    def __init__(
        self,
        api_key: str,
        model_name: str = "claude-3-opus-20240229",
        base_url: str | None = None,
        *,
        max_tokens: int | None = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.client = AsyncAnthropic(api_key=self.api_key, base_url=base_url)
        # Phase SLM1 — env-driven max_tokens. Caller-supplied value wins;
        # otherwise read ``SMART_LLM_MAX_TOKENS`` (default 4096).
        self.max_tokens = _resolve_max_tokens(max_tokens)
        # Populated by :meth:`complete`; used by :class:`smart_llm.Agent`
        # to attach token usage to ``LLMResponse.metadata``.
        self.last_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str | list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Executes a completion and returns parsed JSON.

        ``user_prompt`` accepts either:
        - a ``str`` — wrapped as a single ``{"role":"user"}`` message
          (backwards-compatible with single-turn callers).
        - a ``list`` of ``{"role", "content"}`` dicts — passed directly
          to the Anthropic Messages API for native multi-turn chat
          (Phase SLM2).

        Returns the parsed dict; token counts are stashed on the
        most-recent call via :attr:`last_usage` so :class:`Agent`
        can fold them into ``LLMResponse.metadata`` without changing
        the public return type.
        """
        if isinstance(user_prompt, str):
            messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
        else:
            messages = list(user_prompt)
        try:
            response = await self.client.messages.create(
                model=self.model_name,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=cast(list[MessageParam], messages),
            )
            text = cast(TextBlock, response.content[0]).text
            usage = getattr(response, "usage", None)
            self.last_usage = {
                "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            }
            return self._parse_json(text)
        except Exception as e:
            logger.error(f"Anthropic error: {e!s}")
            raise e

    async def complete_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> list[dict[str, Any]]:
        """Vision completion — sends an image + text to Claude and returns a
        list of dicts parsed from the model's JSON output (e.g. the
        photo_tagger ``[{category, label, confidence}]`` list). Claude 3+
        models accept image content blocks on the Messages API.
        """
        import base64

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        try:
            response = await self.client.messages.create(
                model=self.model_name,
                max_tokens=self.max_tokens,
                system=system_prompt,
                messages=cast(
                    list[MessageParam],
                    [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {
                                        "type": "base64",
                                        "media_type": mime_type,
                                        "data": b64,
                                    },
                                },
                                {"type": "text", "text": user_prompt},
                            ],
                        }
                    ],
                ),
            )
            text = (
                cast(TextBlock, response.content[0]).text
                if response.content
                else "[]"
            )
            usage = getattr(response, "usage", None)
            self.last_usage = {
                "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
            }
            return self._parse_json_array(text)
        except Exception as e:
            logger.error(f"Anthropic vision error: {e!s}")
            raise

    def _parse_json_array(self, text: str) -> list[dict[str, Any]]:
        """Extract a JSON array (or object) from model output, stripping any
        markdown code fences. Mirrors the OpenAI provider's parser so vision
        callers get a uniform ``List[Dict]`` regardless of provider."""
        text = (text or "").strip()
        if "```" in text:
            seg = text.split("```", 2)
            if len(seg) >= 2:
                body = seg[1]
                if body.lstrip().lower().startswith("json"):
                    body = body.lstrip()[4:]
                text = body.strip()
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return cast(list[dict[str, Any]], parsed)
        if isinstance(parsed, dict):
            return cast(list[dict[str, Any]], parsed.get("results", [parsed]))
        return []

    async def stream(
        self,
        system_prompt: str,
        user_prompt: str | list[dict[str, Any]],
    ) -> AsyncIterator[str]:
        """Phase-E3 — yield text deltas from Anthropic SSE.

        Streams plain text (not JSON-parsed) so the run-history viewer
        can render incremental output. Callers that need structured
        output should use :meth:`complete`.

        Accepts a single string OR a pre-built list of messages
        (multi-turn streaming).
        """
        if isinstance(user_prompt, str):
            messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
        else:
            messages = list(user_prompt)
        async with self.client.messages.stream(
            model=self.model_name,
            max_tokens=self.max_tokens,
            system=system_prompt,
            messages=cast(list[MessageParam], messages),
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    yield text
            # Capture final token counts so the host's usage recorder bills the
            # streamed turn (best-effort — must never break the stream).
            try:
                final = await stream.get_final_message()
                usage = getattr(final, "usage", None)
                if usage is not None:
                    self.last_usage = {
                        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
                    }
            except Exception:  # noqa: BLE001 — usage capture is best-effort
                logger.debug("anthropic stream usage capture failed", exc_info=True)

    @staticmethod
    def _system_with_cache(
        system_prompt: str, cached_prefix: str | None
    ) -> str | list[dict[str, Any]]:
        """G3 — when a stable ``cached_prefix`` is supplied, emit the system as
        two text blocks with a ``cache_control`` breakpoint on the prefix so the
        provider caches it; identical prefixes across turns hit the prompt cache.
        Returns the plain string when there's no prefix (unchanged behaviour).
        The runtime never builds the prefix content — it's an opaque string."""
        if not cached_prefix:
            return system_prompt
        return [
            {
                "type": "text",
                "text": cached_prefix,
                "cache_control": {"type": "ephemeral"},
            },
            {"type": "text", "text": system_prompt or ""},
        ]

    async def call_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        action_tools: list[Any],
        cached_prefix: str | None = None,
        prompt_cache_key: str | None = None,  # opaque; Anthropic caches by content
    ) -> AgentTurn:
        """Phase F2 — Anthropic native tool-calling.

        Returns an :class:`~smart_llm.agent_loop.AgentTurn`.
        """
        tool_specs = [
            {
                "name": type(t).__name__,
                "description": getattr(t, "description", "") or "",
                "input_schema": t.args_model.model_json_schema(),
            }
            for t in action_tools
        ]

        response = await self.client.messages.create(
            model=self.model_name,
            max_tokens=self.max_tokens,
            system=cast(Any, self._system_with_cache(system_prompt, cached_prefix)),
            messages=cast(list[MessageParam], messages),
            tools=cast(list[ToolParam], tool_specs),
        )

        usage = getattr(response, "usage", None)
        self.last_usage = {
            "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        }

        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=b.input)
            for b in response.content
            if isinstance(b, ToolUseBlock)
        ]
        text = next(
            (
                getattr(b, "text", None)
                for b in response.content
                if getattr(b, "type", None) == "text"
            ),
            None,
        )
        return AgentTurn(
            content=text,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason or "end_turn",
            usage=self.last_usage.copy(),
        )

    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        action_tools: list[Any],
        cached_prefix: str | None = None,
        prompt_cache_key: str | None = None,  # opaque; Anthropic caches by content
    ) -> AsyncIterator[dict[str, Any]]:
        """Phase F2 streaming follow-up — Anthropic SSE with native
        tool-calling enabled.

        Yields the discriminated-union events documented in
        :mod:`smart_llm.agent_loop` (``text_delta``, ``tool_use_start``,
        ``tool_use_input_delta``, ``tool_use_stop``, ``turn_complete``,
        ``error``). The agent loop's ``run_agent_loop_stream`` driver
        consumes these to surface incremental text + tool calls to
        the WebSocket transport in real time.

        Anthropic SSE event mapping (one of the few places where the
        SDK's low-level raw event stream actually pays off):
        - ``content_block_start`` with type=text → noop (we lazy-emit
          on the first delta).
        - ``content_block_start`` with type=tool_use → ``tool_use_start``.
        - ``content_block_delta`` with text_delta → ``text_delta``.
        - ``content_block_delta`` with input_json_delta →
          ``tool_use_input_delta``.
        - ``content_block_stop`` for a tool_use block → ``tool_use_stop``.
        - ``message_delta`` carries the stop_reason and usage tail.
        - ``message_stop`` → ``turn_complete``.
        """
        tool_specs = [
            {
                "name": type(t).__name__,
                "description": getattr(t, "description", "") or "",
                "input_schema": t.args_model.model_json_schema(),
            }
            for t in action_tools
        ]

        # Track per-content-block metadata as the stream unfolds. The
        # Anthropic event stream uses block ``index`` (0, 1, …) not
        # block id for delta routing, so we keep a parallel map from
        # block index → block id + type so deltas can be matched.
        block_meta: dict[int, dict[str, Any]] = {}
        stop_reason: str = "end_turn"
        usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

        try:
            async with self.client.messages.stream(
                model=self.model_name,
                max_tokens=self.max_tokens,
                system=cast(
                    Any, self._system_with_cache(system_prompt, cached_prefix)
                ),
                messages=cast(list[MessageParam], messages),
                tools=cast(list[ToolParam], tool_specs),
            ) as stream:
                async for raw in stream:
                    etype = getattr(raw, "type", None)
                    if etype == "content_block_start":
                        block = getattr(raw, "content_block", None)
                        idx = getattr(raw, "index", None)
                        btype = getattr(block, "type", None)
                        if idx is None or block is None:
                            continue
                        block_meta[idx] = {
                            "type": btype,
                            "id": getattr(block, "id", None),
                            "name": getattr(block, "name", None),
                        }
                        if btype == "tool_use":
                            yield {
                                "type": "tool_use_start",
                                "id": block_meta[idx]["id"],
                                "name": block_meta[idx]["name"],
                            }
                    elif etype == "content_block_delta":
                        idx = getattr(raw, "index", None)
                        delta = getattr(raw, "delta", None)
                        if idx is None or delta is None:
                            continue
                        dtype = getattr(delta, "type", None)
                        meta = block_meta.get(idx, {})
                        if dtype == "text_delta":
                            text = getattr(delta, "text", "") or ""
                            if text:
                                yield {"type": "text_delta", "delta": text}
                        elif dtype == "input_json_delta":
                            partial = getattr(delta, "partial_json", "") or ""
                            tid = meta.get("id")
                            if tid and partial:
                                yield {
                                    "type": "tool_use_input_delta",
                                    "id": tid,
                                    "partial_json": partial,
                                }
                    elif etype == "content_block_stop":
                        idx = getattr(raw, "index", None)
                        meta = block_meta.get(idx, {}) if idx is not None else {}
                        if meta.get("type") == "tool_use" and meta.get("id"):
                            yield {"type": "tool_use_stop", "id": meta["id"]}
                    elif etype == "message_delta":
                        delta = getattr(raw, "delta", None)
                        if delta is not None:
                            sr = getattr(delta, "stop_reason", None)
                            if sr:
                                stop_reason = sr
                        ev_usage = getattr(raw, "usage", None)
                        if ev_usage is not None:
                            # The output_tokens count finalises on
                            # message_delta; input_tokens was set on
                            # message_start (Anthropic-side detail).
                            usage["output_tokens"] = int(
                                getattr(ev_usage, "output_tokens", 0) or 0
                            )
                    elif etype == "message_start":
                        msg = getattr(raw, "message", None)
                        if msg is not None:
                            ev_usage = getattr(msg, "usage", None)
                            if ev_usage is not None:
                                usage["input_tokens"] = int(
                                    getattr(ev_usage, "input_tokens", 0) or 0
                                )

                # Stream finished — surface the stop reason + usage tail.
                self.last_usage = usage.copy()
                yield {
                    "type": "turn_complete",
                    "stop_reason": stop_reason,
                    "usage": usage,
                }
        except Exception as e:  # noqa: BLE001
            logger.error("Anthropic stream_with_tools error: %s", e)
            yield {"type": "error", "message": str(e)}

    def _build_assistant_tool_use_turn(self, turn: AgentTurn) -> dict[str, Any]:
        """Anthropic multi-turn: assistant message with tool_use blocks."""
        blocks: list[dict[str, Any]] = []
        if turn.content:
            blocks.append({"type": "text", "text": turn.content})
        for tc in turn.tool_calls:
            blocks.append(
                {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input}
            )
        return {"role": "assistant", "content": blocks}

    def _build_tool_results_turn(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Anthropic multi-turn: user message with tool_result blocks."""
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

    def _parse_json(self, text: str) -> dict[str, Any]:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        return cast(dict[str, Any], json.loads(text.strip()))
