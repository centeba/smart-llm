import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any, cast

from google import genai
from google.genai import types

from smart_llm.agent_loop import AgentTurn, ToolCall

logger = logging.getLogger(__name__)

NAME = "gemini"


def _messages_to_gemini_contents(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert agent_loop message dicts to the Gemini ``contents`` shape.

    Anthropic/OpenAI messages use ``role`` + ``content`` (string or blocks).
    Gemini expects ``role`` (``"user"`` | ``"model"``) + ``parts`` (list of
    ``{"text": ...}`` or ``{"function_call": ...}`` or
    ``{"function_response": ...}`` dicts).
    """
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        parts_raw = msg.get("parts")  # pre-built Gemini parts (from our own builders)

        # Already in Gemini shape (our _build_*_turn helpers produce this).
        if parts_raw is not None:
            gemini_role = "model" if role == "assistant" else "user"
            out.append({"role": gemini_role, "parts": parts_raw})
            continue

        # Anthropic-style content: list of typed blocks.
        if isinstance(content, list):
            parts: list[dict[str, Any]] = []
            for block in content:
                btype = block.get("type", "")
                if btype == "text":
                    parts.append({"text": block.get("text", "")})
                elif btype == "tool_use":
                    parts.append(
                        {
                            "function_call": {
                                "name": block["name"],
                                "args": block.get("input", {}),
                            }
                        }
                    )
                elif btype == "tool_result":
                    try:
                        resp = json.loads(block.get("content", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        resp = {"output": block.get("content", "")}
                    parts.append(
                        {
                            "function_response": {
                                "name": block.get("tool_use_id", ""),
                                "response": resp,
                            }
                        }
                    )
            gemini_role = "model" if role == "assistant" else "user"
            out.append({"role": gemini_role, "parts": parts})
        else:
            # Simple string content (user message).
            gemini_role = "model" if role == "assistant" else "user"
            out.append({"role": gemini_role, "parts": [{"text": str(content)}]})
    return out


def _scrub_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove / replace JSON Schema fields that Gemini rejects.

    Gemini's ``FunctionDeclaration`` only understands a subset of
    JSON Schema: no ``$schema``, ``$defs``, ``additionalProperties``,
    ``format: "uuid"``, or OpenAPI-style ``anyOf`` null unions.
    """
    if not isinstance(schema, dict):
        return schema

    cleaned: dict[str, Any] = {}
    for k, v in schema.items():
        # Drop Gemini-incompatible root keys.
        if k in ("$schema", "$defs", "additionalProperties"):
            continue
        # Drop format=uuid — Gemini doesn't recognise it.
        if k == "format" and v == "uuid":
            continue
        # Replace anyOf: [<type>, null] with the base type + nullable.
        if k == "anyOf" and isinstance(v, list):
            non_null = [i for i in v if i != {"type": "null"}]
            if non_null:
                inner = _scrub_schema(non_null[0])
                inner["nullable"] = True
                cleaned.update(inner)
            continue
        if isinstance(v, dict):
            cleaned[k] = _scrub_schema(v)
        elif isinstance(v, list):
            cleaned[k] = [_scrub_schema(i) if isinstance(i, dict) else i for i in v]
        else:
            cleaned[k] = v
    return cleaned


class GeminiProvider:
    """Gemini-specific LLM execution logic (uses the `google-genai` SDK)."""

    NAME = NAME

    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model_name = model_name
        # Instance-based client — isolates state per provider, supporting key rotation.
        self.client = genai.Client(api_key=self.api_key)
        # Populated by :meth:`complete` for the host's usage recorder.
        self.last_usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}

    async def complete(
        self,
        system_prompt: str,
        user_prompt: str | list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Executes a completion and returns parsed JSON.

        ``user_prompt`` accepts either a single string or a list of
        ``{"role", "content"}`` message dicts (Phase SLM2 multi-turn).
        Lists are mapped to Gemini's ``contents`` shape via the
        existing ``_messages_to_gemini_contents`` helper.
        """
        if isinstance(user_prompt, str):
            contents: Any = user_prompt
        else:
            contents = _messages_to_gemini_contents(user_prompt)
        try:
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
            )
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=cast(Any, contents),
                config=config,
            )
            text = response.text
            meta = getattr(response, "usage_metadata", None)
            self.last_usage = {
                "input_tokens": int(getattr(meta, "prompt_token_count", 0) or 0),
                "output_tokens": int(getattr(meta, "candidates_token_count", 0) or 0),
            }
            return self._parse_json(cast(str, text))
        except Exception as e:
            logger.error(f"Gemini error: {e!s}")
            raise e

    async def complete_with_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> list[dict[str, Any]]:
        """Vision completion — returns a list of dicts parsed from the response."""
        image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        text_part = types.Part.from_text(text=f"{system_prompt}\n\n{user_prompt}")

        # No response_mime_type for vision calls — Gemini rejects JSON mode with images
        config = types.GenerateContentConfig()

        def _sync_call() -> types.GenerateContentResponse:
            return self.client.models.generate_content(
                model=self.model_name,
                contents=cast(Any, [image_part, text_part]),
                config=config,
            )

        loop = asyncio.get_running_loop()
        try:
            response = await loop.run_in_executor(None, _sync_call)
            meta = getattr(response, "usage_metadata", None)
            self.last_usage = {
                "input_tokens": int(getattr(meta, "prompt_token_count", 0) or 0),
                "output_tokens": int(getattr(meta, "candidates_token_count", 0) or 0),
            }
            return self._parse_json_array(response.text or "[]")
        except Exception as e:
            logger.error(f"Gemini vision error: {e!s}")
            raise

    def _parse_json_array(self, text: str) -> list[dict[str, Any]]:
        """Extract a JSON array or object from model output."""
        text = text.strip() if text else "[]"
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if fence:
            text = fence.group(1).strip()
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return cast(list[dict[str, Any]], parsed)
        if isinstance(parsed, dict):
            return cast(list[dict[str, Any]], parsed.get("results", [parsed]))
        return []

    async def stream(self, system_prompt: str, user_prompt: str) -> AsyncIterator[str]:
        """Phase-E3 — yield text deltas from Gemini streaming.

        ``generate_content_stream`` is sync-iterable in the genai SDK;
        we adapt it via an executor so the surrounding API stays async.
        """
        import asyncio

        config = types.GenerateContentConfig(system_instruction=system_prompt)

        def _start() -> Any:
            return self.client.models.generate_content_stream(
                model=self.model_name,
                contents=cast(Any, user_prompt),
                config=config,
            )

        loop = asyncio.get_running_loop()
        iterator = await loop.run_in_executor(None, _start)
        # Each next() also blocks; defer to executor to avoid stalling
        # the event loop on slow chunks.
        sentinel = object()

        def _next() -> object:
            try:
                return next(iterator)
            except StopIteration:
                return sentinel

        while True:
            chunk = await loop.run_in_executor(None, _next)
            if chunk is sentinel:
                return
            # Gemini streams usage_metadata on (typically) the final chunk;
            # capture whenever present so the host can bill the streamed turn.
            meta = getattr(chunk, "usage_metadata", None)
            if meta is not None:
                self.last_usage = {
                    "input_tokens": int(getattr(meta, "prompt_token_count", 0) or 0),
                    "output_tokens": int(
                        getattr(meta, "candidates_token_count", 0) or 0
                    ),
                }
            text = getattr(chunk, "text", None)
            if text:
                yield text

    async def call_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        action_tools: list[Any],
    ) -> AgentTurn:
        """Phase F2 — Gemini native tool-calling.

        Returns an :class:`~smart_llm.agent_loop.AgentTurn`.
        Runs in an executor because the google-genai SDK is synchronous.
        """
        tool_declarations: list[types.FunctionDeclaration] = []
        for t in action_tools:
            raw_schema = t.args_model.model_json_schema()
            scrubbed = _scrub_schema(raw_schema)
            tool_declarations.append(
                types.FunctionDeclaration(
                    name=type(t).__name__,
                    description=getattr(t, "description", "") or "",
                    parameters=scrubbed,
                )
            )
        gemini_tools = [types.Tool(function_declarations=tool_declarations)]

        # Convert agent_loop messages to Gemini contents list.
        contents = _messages_to_gemini_contents(messages)

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=gemini_tools,
        )

        def _sync_call() -> types.GenerateContentResponse:
            return self.client.models.generate_content(
                model=self.model_name,
                contents=cast(Any, contents),
                config=config,
            )

        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, _sync_call)

        meta = getattr(response, "usage_metadata", None)
        self.last_usage = {
            "input_tokens": int(getattr(meta, "prompt_token_count", 0) or 0),
            "output_tokens": int(getattr(meta, "candidates_token_count", 0) or 0),
        }

        tool_calls: list[ToolCall] = []
        text_parts: list[str] = []
        candidate = response.candidates[0] if response.candidates else None
        if candidate and candidate.content:
            for part in cast(list[types.Part], candidate.content.parts):
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    tool_calls.append(
                        ToolCall(
                            id=cast(str, getattr(fc, "id", fc.name)),
                            name=cast(str, fc.name),
                            input=dict(fc.args or {}),
                        )
                    )
                elif hasattr(part, "text") and part.text:
                    text_parts.append(part.text)

        text = "\n".join(text_parts) if text_parts else None
        return AgentTurn(
            content=text,
            tool_calls=tool_calls,
            stop_reason="tool_use" if tool_calls else "end_turn",
            usage=self.last_usage.copy(),
        )

    async def stream_with_tools(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        action_tools: list[Any],
    ) -> AsyncIterator[dict[str, Any]]:
        """Phase F2 streaming follow-up — Gemini streaming with tools.

        Yields the discriminated-union events documented in
        :mod:`smart_llm.agent_loop` (``text_delta``, ``tool_use_start``,
        ``tool_use_input_delta``, ``tool_use_stop``, ``turn_complete``,
        ``error``).

        Gemini streaming chunk shape:
        - Each chunk's ``candidates[0].content.parts`` is a list of
          part dicts that are either ``{text: ...}`` or
          ``{function_call: {name, args}}``.
        - ``function_call`` parts arrive whole (args is a dict, not
          a JSON fragment string). We surface them as a
          tool_use_start + a single tool_use_input_delta with the
          full args JSON-encoded + tool_use_stop.
        - ``usage_metadata`` arrives on the final chunk.
        - The google-genai SDK is synchronous; we adapt it via an
          executor, matching the existing ``stream`` method.
        """
        tool_declarations: list[types.FunctionDeclaration] = []
        for t in action_tools:
            raw_schema = t.args_model.model_json_schema()
            scrubbed = _scrub_schema(raw_schema)
            tool_declarations.append(
                types.FunctionDeclaration(
                    name=type(t).__name__,
                    description=getattr(t, "description", "") or "",
                    parameters=scrubbed,
                )
            )
        gemini_tools = [types.Tool(function_declarations=tool_declarations)]
        contents = _messages_to_gemini_contents(messages)
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=gemini_tools,
        )

        def _start() -> Any:
            return self.client.models.generate_content_stream(
                model=self.model_name,
                contents=cast(Any, contents),
                config=config,
            )

        loop = asyncio.get_running_loop()
        try:
            iterator = await loop.run_in_executor(None, _start)
        except Exception as e:  # noqa: BLE001
            logger.error("Gemini stream_with_tools start error: %s", e)
            yield {"type": "error", "message": str(e)}
            return

        sentinel = object()

        def _next() -> object:
            try:
                return next(iterator)
            except StopIteration:
                return sentinel

        # Gemini doesn't expose stable per-call ids; synthesise one
        # per emitted function_call so consumers can route the
        # subsequent input_delta + stop events.
        call_counter = 0
        usage: dict[str, int] = {"input_tokens": 0, "output_tokens": 0}
        had_function_call = False

        try:
            while True:
                chunk = await loop.run_in_executor(None, _next)
                if chunk is sentinel:
                    break

                # Accumulate usage from each chunk (final chunk has
                # the populated values).
                meta = getattr(chunk, "usage_metadata", None)
                if meta is not None:
                    usage["input_tokens"] = int(
                        getattr(meta, "prompt_token_count", 0) or 0
                    )
                    usage["output_tokens"] = int(
                        getattr(meta, "candidates_token_count", 0) or 0
                    )

                candidates = getattr(chunk, "candidates", None) or []
                if not candidates:
                    continue
                cand = candidates[0]
                content = getattr(cand, "content", None)
                if content is None:
                    continue
                parts = getattr(content, "parts", None) or []

                for part in parts:
                    fc = getattr(part, "function_call", None)
                    if fc:
                        had_function_call = True
                        call_counter += 1
                        # Synthesise an id from name + counter so
                        # repeated calls to the same tool are
                        # distinguishable. Use the model-provided
                        # id when available.
                        tc_id = (
                            getattr(fc, "id", None) or f"call_{fc.name}_{call_counter}"
                        )
                        yield {
                            "type": "tool_use_start",
                            "id": tc_id,
                            "name": fc.name,
                        }
                        args_dict = dict(fc.args or {})
                        yield {
                            "type": "tool_use_input_delta",
                            "id": tc_id,
                            "partial_json": json.dumps(args_dict),
                        }
                        yield {"type": "tool_use_stop", "id": tc_id}
                        continue

                    text = getattr(part, "text", None)
                    if text:
                        yield {"type": "text_delta", "delta": text}

            mapped_reason = "tool_use" if had_function_call else "end_turn"
            self.last_usage = usage.copy()
            yield {
                "type": "turn_complete",
                "stop_reason": mapped_reason,
                "usage": usage,
            }
        except Exception as e:  # noqa: BLE001
            logger.error("Gemini stream_with_tools error: %s", e)
            yield {"type": "error", "message": str(e)}

    def _build_assistant_tool_use_turn(self, turn: AgentTurn) -> dict[str, Any]:
        """Gemini multi-turn: model role with function_call parts."""
        parts: list[dict[str, Any]] = []
        if turn.content:
            parts.append({"text": turn.content})
        for tc in turn.tool_calls:
            parts.append({"function_call": {"name": tc.name, "args": tc.input}})
        return {"role": "model", "parts": parts}

    def _build_tool_results_turn(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Gemini multi-turn: user role with function_response parts."""
        parts: list[dict[str, Any]] = []
        for r in results:
            try:
                content = json.loads(r["content"])
            except (json.JSONDecodeError, TypeError):
                content = {"output": r["content"]}
            parts.append(
                {"function_response": {"name": r["name"], "response": content}}
            )
        return {"role": "user", "parts": parts}

    def _parse_json(self, text: str) -> dict[str, Any]:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return cast(dict[str, Any], json.loads(text.strip()))
