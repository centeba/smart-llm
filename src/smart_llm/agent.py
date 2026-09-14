import json
import logging
import os
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from .base import AbstractAgent, LLMResponse, OutputTool, Tool
from .providers.anthropic import AnthropicProvider
from .providers.gemini import GeminiProvider
from .providers.openai import OpenAIProvider
from .providers.openrouter import (
    DEFAULT_MODEL as OPENROUTER_DEFAULT_MODEL,
)
from .providers.openrouter import (
    OpenRouterProvider,
)
from .tracing import agent_operation_span, model_call_span, set_usage_attributes

logger = logging.getLogger(__name__)


def _provider_input_text(provider_input: Any) -> str:
    """Flatten a provider input (string or message list) to screenable text."""
    if isinstance(provider_input, str):
        return provider_input
    parts: list[str] = []
    for msg in provider_input or []:
        content = msg.get("content") if isinstance(msg, dict) else None
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
    return "\n".join(parts)


def _response_text(data: Any) -> str:
    """Extract the model's textual output from response data for screening."""
    if isinstance(data, dict):
        content = data.get("content")
        if isinstance(content, str):
            return content
        try:
            return json.dumps(data, default=str, ensure_ascii=False)
        except Exception:
            return str(data)
    return str(data)


class _PromptSkillTool(Tool):
    """Wraps a DB-backed ``kind=prompt`` skill so its content augments
    the user prompt at runtime. Registry-backed Python tools subclass
    :class:`Tool` directly and do not go through this wrapper.
    """

    def __init__(self, name: str, content: str):
        self.name = name
        self._content = content or ""

    def run(self, input_text: str, **kwargs: Any) -> str:
        if not self._content:
            return input_text
        return f"[Skill: {self.name}]\n{self._content}\n\n{input_text}"


class Agent(AbstractAgent):
    """
    A concrete implementation of an AI Agent.
    """

    def __init__(
        self,
        name: str,
        provider_type: str,
        system_prompt: str,
        api_key: str,
        tools: list[Tool] | None = None,
        output_tools: list[OutputTool] | None = None,
        model_name: str | None = None,
        base_url: str | None = None,
        # Phase E4 — usage tracking + budget enforcement. Opt-in: when
        # ``usage_session``/``usage_model`` are ``None`` the agent
        # behaves exactly as it did pre-E4 (no DB round-trips on hot
        # paths, no budget check). Hosts that want the protection wire
        # all four fields:
        #   * usage_session — an AsyncSession scoped to the call site
        #   * usage_model — the host's AIUsageEvent ORM class
        #   * company_id — tenant identifier (UUID or string)
        #   * monthly_budget_usd — cap; <=0 means "unlimited"
        # ``agent_id`` is recorded on each usage row so the admin
        # Usage tab can attribute spend per agent.
        usage_session: Any = None,
        usage_model: Any = None,
        company_id: Any = None,
        monthly_budget_usd: float = 0.0,
        agent_id: str | None = None,
        # Recorded on each usage row for platform billing attribution: the
        # individual user whose action drove the call, and the primary skill the
        # agent is running (None for multi-skill or promptless agents).
        user_id: str | None = None,
        skill_id: str | None = None,
        # Content-safety pipeline (mandatory by default — unlike the opt-in
        # budget gate). ``allowed_scope`` is a short description of the agent's
        # task; when set, the guard rejects off-topic output. Pass
        # ``safety_enabled=False`` (or set SMART_LLM_MODERATION_ENABLED=false)
        # for break-glass; pass an explicit ``safety_guard`` to share one.
        allowed_scope: str | None = None,
        safety_guard: Any = None,
        safety_enabled: bool = True,
        # ── PII masking firewall ────────────────────────────────────────────
        # ``pii_policy`` is the ALREADY-RESOLVED effective policy string
        # ('off'|'detect-only'|'enforce'|'strict') — the host combines the
        # company + per-agent policy via ``smart_llm.pii.resolve_pii_policy`` and
        # passes the result here. When active (≠ 'off') the concrete provider is
        # wrapped in a :class:`~smart_llm.pii.MaskingProvider`, so EVERY egress
        # path (chat, documents, the no-tools broker, the autonomous tool loop)
        # is masked and every response re-hydrated with no other call-site
        # change. ``pii_firewall`` optionally shares one process-wide firewall
        # singleton; a default is built when omitted. ``pii_allow_vision`` is the
        # per-agent escape hatch honoured under 'enforce' (ignored under 'strict').
        pii_policy: str | None = None,
        pii_firewall: Any = None,
        pii_allow_vision: bool = False,
        # Declared-field hints: exact ``(value, type)`` pairs the host knows are
        # PII (e.g. the acting user's name/email, or values from columns a
        # company admin marked PII). Seeded into the request's masking vault so
        # they mask with 100% precision — catching free-text PII (names) the
        # regex detector can't. Services supply these as DATA; the masking act
        # still happens only inside the firewall.
        pii_hints: Any = None,
    ):
        super().__init__(name, system_prompt, tools, output_tools)
        self.provider_type = provider_type.lower()
        self.api_key = api_key
        self.model_name = model_name
        self.base_url = base_url
        self._pii_policy = pii_policy
        self._pii_firewall = pii_firewall
        self._pii_allow_vision = pii_allow_vision
        self._pii_hints = pii_hints
        self._provider = self._init_provider()
        # ── Content-safety guard ────────────────────────────────────────────
        self._allowed_scope = allowed_scope
        self._safety_enabled = safety_enabled
        if safety_guard is not None:
            self._safety_guard = safety_guard
        elif safety_enabled:
            from .security.guard import SafetyGuard

            self._safety_guard = SafetyGuard(
                provider=self._provider,
                key_getter=self._moderation_key_getter,
            )
        else:
            self._safety_guard = None
        # Usage tracking handles — stored as private members to avoid
        # colliding with any future public attribute named ``session``.
        self._usage_session = usage_session
        self._usage_model = usage_model
        self._company_id = company_id
        self._monthly_budget_usd = float(monthly_budget_usd or 0.0)
        self._agent_id = agent_id
        self._user_id = user_id
        self._skill_id = skill_id

    def _init_provider(self) -> Any:
        """Build the concrete provider, then wrap it in the PII masking
        firewall when a policy is active. This is the ONE seam every ``Agent``
        funnels through, so wrapping here masks every egress path at once with
        no change to the call methods or the agent loop. When the policy is
        'off' (or unset) the bare provider is returned — zero overhead."""
        inner = self._build_inner_provider()
        from .pii import MaskingProvider, PiiFirewall, is_active

        if self._pii_policy and is_active(self._pii_policy):
            firewall = self._pii_firewall or PiiFirewall()
            return MaskingProvider(
                inner,
                firewall,
                self._pii_policy,
                allow_vision_pii=self._pii_allow_vision,
                hints=self._pii_hints,
            )
        return inner

    def _build_inner_provider(self) -> Any:
        if self.provider_type == "gemini":
            return GeminiProvider(self.api_key, self.model_name or "gemini-2.5-flash")
        elif self.provider_type == "openai":
            return OpenAIProvider(
                self.api_key, self.model_name or "gpt-4-turbo-preview", self.base_url
            )
        elif self.provider_type == "anthropic":
            return AnthropicProvider(
                self.api_key, self.model_name or "claude-3-opus-20240229", self.base_url
            )
        elif self.provider_type == "openrouter":
            # SPIKE — route this agent through OpenRouter instead of a direct
            # vendor SDK. This IS the "direct vs OpenRouter" switch: the
            # provider value alone selects the transport. ``model_name`` is an
            # OpenRouter slug (e.g. "anthropic/claude-sonnet-4.5") or the
            # meta-router default. ``base_url`` may override the endpoint.
            return OpenRouterProvider(
                self.api_key,
                self.model_name or OPENROUTER_DEFAULT_MODEL,
                self.base_url,
            )
        else:
            raise ValueError(f"Unsupported provider type: {self.provider_type}")

    # ── Content-safety hooks ────────────────────────────────────────────────

    def _moderation_key_getter(self) -> str | None:
        """Resolve an OpenAI key for the /moderations backend.

        Reuses this agent's key when it is itself an OpenAI agent; otherwise
        falls back to ``OPENAI_API_KEY`` in the environment. Returns ``None``
        when no key is available, which makes the moderation chain fall through
        to the LLM-classifier backend (this agent's own provider).
        """
        if self.provider_type == "openai" and self.api_key:
            return self.api_key
        return os.getenv("OPENAI_API_KEY")

    async def _screen_input(self, text: str) -> None:
        if self._safety_guard is not None:
            await self._safety_guard.screen_input(text)

    async def _screen_output(self, text: str) -> None:
        if self._safety_guard is not None:
            await self._safety_guard.screen_output(
                text, allowed_scope=self._allowed_scope
            )

    async def _screen_image(self, image_bytes: bytes, mime_type: str) -> None:
        if self._safety_guard is not None:
            await self._safety_guard.screen_image(image_bytes, mime_type)

    # ── Phase E4 — usage tracking hooks ─────────────────────────────────────

    @property
    def _usage_tracking_enabled(self) -> bool:
        """True when the host wired both the session + model. Either
        being ``None`` short-circuits both ``_check_budget`` and
        ``_record_usage`` so the pre-E4 hot path stays free of DB
        round-trips for hosts that don't care."""
        return self._usage_session is not None and self._usage_model is not None

    async def _check_budget(self) -> None:
        """Raise :class:`BudgetExceededError` if the company has burned
        through its monthly cap. No-op when tracking is disabled or the
        budget is <=0 (interpreted as 'unlimited')."""
        if not self._usage_tracking_enabled or self._company_id is None:
            return
        if self._monthly_budget_usd <= 0:
            return
        from .usage import assert_within_budget

        await assert_within_budget(
            self._usage_session,
            self._usage_model,
            str(self._company_id),
            monthly_budget_usd=self._monthly_budget_usd,
        )

    async def _record_usage(self, response: LLMResponse) -> None:
        """Insert one ``ai_usage_events`` row reflecting the just-
        completed provider call. Token counts are pulled from
        ``response.metadata.usage`` (populated by ``analyze``)."""
        if not self._usage_tracking_enabled or self._company_id is None:
            return
        from .usage import UsageContext, record_usage

        usage = (response.metadata or {}).get("usage") or {}
        # A gateway provider (OpenRouter) reports the authoritative USD cost of
        # the call on ``last_usage``; when present, bill that exact figure
        # rather than re-estimating from the static PRICING table.
        provider_usage = getattr(self._provider, "last_usage", None) or {}
        reported_cost = provider_usage.get("cost_usd")
        # PII-masking audit summary (counts only, never values) when the provider
        # is the masking firewall. Scoped to MaskingProvider specifically — bare
        # providers don't carry a summary, and this avoids a duck-typed mock
        # false-positive on the ``masking_summary`` name.
        from .pii import MaskingProvider

        pii_masking = (
            self._provider.masking_summary()
            if isinstance(self._provider, MaskingProvider)
            else None
        )
        try:
            await record_usage(
                self._usage_session,
                self._usage_model,
                UsageContext(
                    company_id=str(self._company_id),
                    agent_id=self._agent_id,
                    skill_id=self._skill_id,
                    user_id=self._user_id,
                    provider=self.provider_type,
                    model=self.model_name or "",
                ),
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                cost_usd=reported_cost,
                pii_masking=pii_masking,
            )
        except Exception as e:  # noqa: BLE001
            # Recording must never break the user-facing call. Log and
            # swallow — the agent's response is already returned.
            logger.warning("Agent %s: failed to record usage: %s", self.name, e)

    def _trace_usage(self, span: Any, usage: dict[str, Any]) -> None:
        """Stamp token counts (+ gateway cost, + PII summary) onto the agent
        span, matching what ``_record_usage`` writes to the billing ledger.
        No-op when tracing is off."""
        from .pii import MaskingProvider

        provider_usage = getattr(self._provider, "last_usage", None) or {}
        pii = (
            self._provider.masking_summary()
            if isinstance(self._provider, MaskingProvider)
            else None
        )
        set_usage_attributes(
            span,
            usage=usage,
            cost_usd=provider_usage.get("cost_usd"),
            pii_masking=pii,
        )

    async def analyze(
        self,
        input_text: str | None = None,
        context: str | None = None,
        *,
        messages: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        """Processes input through tools and then sends to the provider.

        Phase SLM2 — accepts an optional ``messages`` kwarg for native
        multi-turn chat. Resolution rules:

        - ``messages`` only: passed straight through to the provider
          (multi-turn chat with no new user turn — useful when the
          caller has already appended their final message).
        - ``messages`` + ``input_text``: ``input_text`` is appended as
          a final user turn after running prompt-shaping tools on it.
        - ``input_text`` only (legacy): unchanged single-turn flow,
          including the ``Context: <ctx>\\n\\nInput: <text>`` wrap.

        ``input_text`` is now optional (was required); callers passing
        only ``messages`` get the pure-multi-turn path.
        """
        if messages is not None and input_text is None:
            # Pure multi-turn — pass message array straight through.
            provider_input: Any = list(messages)
        elif messages is not None:
            # Multi-turn + new user turn.
            processed = self._apply_tools(input_text or "")
            provider_input = list(messages) + [{"role": "user", "content": processed}]
        else:
            # Existing single-turn path.
            processed = self._apply_tools(input_text or "")
            provider_input = (
                f"Context: {context}\n\nInput: {processed}" if context else processed
            )

        # Content-safety: screen input BEFORE we burn a provider credit.
        await self._screen_input(_provider_input_text(provider_input))
        # Phase E4 — budget guard runs before any provider call so we
        # don't burn an LLM credit just to reject the response.
        await self._check_budget()
        # Agent-native tracing — one span per operation, tenant-tagged, ended in
        # ``finally`` so token/cost attributes land even on the error path.
        span = agent_operation_span(
            "analyze",
            agent_name=self.name,
            provider=self.provider_type,
            model=self.model_name,
            company_id=self._company_id,
            agent_id=self._agent_id,
            user_id=self._user_id,
        )
        try:
            with model_call_span(self.provider_type, self.model_name):
                data = await self._provider.complete(self.system_prompt, provider_input)
            # Phase E4 — providers stash token counts on
            # ``last_usage`` after each call. Surface them on the
            # response so the host's usage recorder can persist real
            # numbers instead of placeholder zeros.
            usage = getattr(self._provider, "last_usage", None) or {}
            response = LLMResponse(
                data=data,
                provider=self.provider_type,
                metadata={
                    "agent_name": self.name,
                    "model": self.model_name,
                    "usage": {
                        "input_tokens": int(usage.get("input_tokens", 0)),
                        "output_tokens": int(usage.get("output_tokens", 0)),
                    },
                },
            )
            # Record usage AFTER the response is built but BEFORE
            # output-tools run — failures inside output_tools shouldn't
            # mask the fact that the LLM call was billed by the provider.
            await self._record_usage(response)
            self._trace_usage(span, usage)
            # Content-safety: screen the model output (+ scope) before return.
            await self._screen_output(_response_text(data))
            # Post-processing: apply output tools (sanitization, validation, audit)
            response = self._apply_output_tools(response)
            return response
        except Exception as e:
            span.error(e)
            logger.error(f"Agent {self.name} failed: {e!s}")
            raise e
        finally:
            span.end()

    async def analyze_image(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
        context: str | None = None,
    ) -> LLMResponse:
        """Vision analysis — processes an image and returns structured output.

        Text tools (e.g. RestorationContextTool) run first to enrich the
        user prompt string; the image + enriched prompt are then sent to
        the provider's ``complete_with_image`` method.
        """
        if not hasattr(self._provider, "complete_with_image"):
            raise NotImplementedError(
                f"Provider {self.provider_type!r} has no complete_with_image() method"
            )
        base_prompt = context or "Analyze this image and return JSON."
        enriched_prompt = self._apply_tools(base_prompt)
        # Content-safety: screen the text prompt AND the image content before it
        # egresses to the vision model (visual abuse / embedded-text injection).
        await self._screen_input(enriched_prompt)
        await self._screen_image(image_bytes, mime_type)
        await self._check_budget()
        span = agent_operation_span(
            "analyze_image",
            agent_name=self.name,
            provider=self.provider_type,
            model=self.model_name,
            company_id=self._company_id,
            agent_id=self._agent_id,
            user_id=self._user_id,
        )
        try:
            with model_call_span(self.provider_type, self.model_name):
                result_list = await self._provider.complete_with_image(
                    self.system_prompt, enriched_prompt, image_bytes, mime_type
                )
            usage = getattr(self._provider, "last_usage", None) or {}
            response = LLMResponse(
                data={"results": result_list},
                provider=self.provider_type,
                metadata={
                    "agent_name": self.name,
                    "model": self.model_name,
                    "usage": {
                        "input_tokens": int(usage.get("input_tokens", 0)),
                        "output_tokens": int(usage.get("output_tokens", 0)),
                    },
                },
            )
            await self._record_usage(response)
            self._trace_usage(span, usage)
            await self._screen_output(_response_text({"results": result_list}))
            response = self._apply_output_tools(response)
            return response
        except Exception as e:
            span.error(e)
            logger.error(f"Agent {self.name} vision analysis failed: {e!s}")
            raise
        finally:
            span.end()

    async def analyze_stream(
        self,
        input_text: str | None = None,
        context: str | None = None,
        *,
        messages: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Phase-E3 — yield text deltas from the underlying provider.

        Tools run as usual in the pre-LLM phase (input filtering /
        prompt augmentation); output tools are NOT applied because the
        stream emits raw text chunks rather than a parsed JSON object.
        Callers wanting validated output should still use
        :meth:`analyze`.

        Phase SLM2 — accepts the same ``messages`` kwarg as
        :meth:`analyze` for multi-turn streaming. Provider must
        support ``stream()`` taking a list of messages
        (Anthropic does; OpenAI/Gemini gain it as a follow-up).
        """
        if not hasattr(self._provider, "stream"):
            raise NotImplementedError(
                f"Provider {self.provider_type!r} has no stream() method"
            )
        if messages is not None and input_text is None:
            provider_input: Any = list(messages)
        elif messages is not None:
            processed = self._apply_tools(input_text or "")
            provider_input = list(messages) + [{"role": "user", "content": processed}]
        else:
            processed = self._apply_tools(input_text or "")
            provider_input = (
                f"Context: {context}\n\nInput: {processed}" if context else processed
            )
        # Content-safety: input is screened up-front and can block before the
        # stream opens. Output cannot be retracted mid-stream, so it is screened
        # post-hoc (logged) — prefer non-streaming ``analyze`` for agents whose
        # output is untrusted/needs hard enforcement.
        await self._screen_input(_provider_input_text(provider_input))
        # Phase E4 — budget guard runs before the SSE connection
        # opens. ``record_usage`` runs once after the stream completes
        # since providers populate ``last_usage`` only at end-of-stream.
        await self._check_budget()
        # One span covers the whole stream; ended in ``finally`` so usage lands
        # even if the client disconnects mid-stream (generator closed).
        span = agent_operation_span(
            "analyze_stream",
            agent_name=self.name,
            provider=self.provider_type,
            model=self.model_name,
            company_id=self._company_id,
            agent_id=self._agent_id,
            user_id=self._user_id,
        )
        try:
            _streamed: list[str] = []
            async for chunk in self._provider.stream(self.system_prompt, provider_input):
                _streamed.append(chunk)
                yield chunk
            # Post-hoc output screen — cannot unsend, so a flag is logged, not raised.
            try:
                await self._screen_output("".join(_streamed))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Agent %s: streamed output flagged by content safety (already sent): %s",
                    self.name,
                    exc,
                )
            # Stream terminated cleanly — record a usage row reflecting the
            # provider's final token counts. Wrapped in a synthetic
            # LLMResponse since ``_record_usage`` reads from metadata.
            usage = getattr(self._provider, "last_usage", None) or {}
            synthetic = LLMResponse(
                data={},
                provider=self.provider_type,
                metadata={
                    "agent_name": self.name,
                    "model": self.model_name,
                    "usage": {
                        "input_tokens": int(usage.get("input_tokens", 0)),
                        "output_tokens": int(usage.get("output_tokens", 0)),
                    },
                },
            )
            await self._record_usage(synthetic)
            self._trace_usage(span, usage)
        finally:
            span.end()

    async def run_with_skills(
        self,
        input_text: str | None = None,
        skill_names: Sequence[str] = (),
        db_session: Any = None,
        context: str | None = None,
        *,
        messages: list[dict[str, Any]] | None = None,
        policy_gate: Any = None,
        max_iterations: int | None = None,
        ctx: Any = None,
        guards: Any = None,
        cached_prefix: Any = None,
        volatile_tail: Any = None,
        prompt_cache_key: Any = None,
    ) -> LLMResponse:
        """Resolve ``skill_names`` against the registry first, then the DB,
        attach the resulting tools to this agent for the duration of the
        call, and run :meth:`analyze`.

        Resolution order per name:

        1. :func:`smart_llm.registry.get_tool_meta` — registered Python tool
           (``kind="python_tool"``). Instantiated with no args; subclasses
           that need parameters should accept them via constructor defaults
           or a class-level config hook.
        2. ``db_session`` lookup against the host's ``AISkill`` table — DB
           skill with ``kind="prompt"`` is wrapped via
           :class:`_PromptSkillTool` so its ``content`` augments the user
           prompt. ``kind="python_tool"`` rows fall back to the registry by
           ``content`` (the registry name).

        Unknown names raise ``KeyError`` listing every unresolved name so
        callers can surface a single useful error.
        """
        from .registry import get_tool_meta  # local import avoids cycles

        resolved: list[Tool] = []
        unresolved: list[str] = []

        # Optional: ask the host's session for a DB skill row by name.
        async def _lookup_db(name: str) -> Any:
            if db_session is None:
                return None
            try:
                from sqlalchemy import select
            except Exception:
                return None
            # The host registers the AISkill model class on the session's
            # bind; we look it up by name on the registry so we don't
            # import host code. If the host hasn't wired this, skip.
            ai_skill = getattr(db_session, "_smart_llm_ai_skill_cls", None)
            if ai_skill is None:
                return None
            stmt = select(ai_skill).where(ai_skill.name == name)
            res = await db_session.execute(stmt)
            return res.scalars().first()

        for name in skill_names:
            meta = get_tool_meta(name)
            if meta is not None:
                try:
                    resolved.append(meta.cls())
                    continue
                except TypeError:
                    logger.warning(
                        "Skill '%s' could not be instantiated with no args; skipping",
                        name,
                    )
                    continue

            row = await _lookup_db(name)
            if row is None:
                unresolved.append(name)
                continue

            kind = getattr(row, "kind", "prompt")
            content = getattr(row, "content", None)
            if kind == "python_tool" and content:
                meta2 = get_tool_meta(content)
                if meta2 is not None:
                    try:
                        resolved.append(meta2.cls())
                        continue
                    except TypeError:
                        pass
                unresolved.append(name)
                continue

            # kind == "prompt"
            resolved.append(_PromptSkillTool(name=name, content=content or ""))

        if unresolved:
            raise KeyError(f"Unresolved skills for agent '{self.name}': {unresolved}")

        # Partition resolved skills: prompt-shaper Tools vs ActionTools.
        from .base import ActionTool as _ActionTool

        action_tools = [t for t in resolved if isinstance(t, _ActionTool)]
        prompt_tools = [t for t in resolved if not isinstance(t, _ActionTool)]

        if action_tools:
            # Phase F2 — route through the provider-native function-calling
            # agent loop. Prompt-shaping tools still run on the input first.
            from .agent_loop import run_agent_loop

            pre_processed = self._apply_tools(
                f"Context: {context}\n\nInput: {input_text}"
                if context
                else cast(str, input_text),
            )
            # G3 — volatile tail (date, current view, …) appended to the user
            # message so it stays OUT of the cached prefix. Opaque string.
            if volatile_tail and isinstance(pre_processed, str):
                pre_processed = f"{pre_processed}\n\n{volatile_tail}"
            original_tools = self.tools
            self.tools = list(original_tools) + prompt_tools
            # Content-safety: screen the input before the loop fires any call.
            await self._screen_input(_provider_input_text(pre_processed))
            # Phase E4 — budget guard once before the loop starts. The
            # loop may fire multiple LLM calls; the guard only blocks at
            # 100% (subsequent rounds in the same loop don't re-check,
            # which is fine because the cost gap between starting and
            # finishing a single agent_loop is tiny in practice).
            await self._check_budget()
            # Parent span for the tool-calling loop; the loop adds per-cycle and
            # per-tool child spans under it. Ended in ``finally``.
            span = agent_operation_span(
                "run_with_skills",
                agent_name=self.name,
                provider=self.provider_type,
                model=self.model_name,
                company_id=self._company_id,
                agent_id=self._agent_id,
                user_id=self._user_id,
            )
            try:
                _loop_kwargs: dict[str, Any] = {"guard": self._safety_guard}
                if policy_gate is not None:
                    _loop_kwargs["policy_gate"] = policy_gate
                if ctx is not None:
                    _loop_kwargs["ctx"] = ctx
                if guards is not None:
                    _loop_kwargs["guards"] = guards
                if cached_prefix is not None:
                    _loop_kwargs["cached_prefix"] = cached_prefix
                if prompt_cache_key is not None:
                    _loop_kwargs["prompt_cache_key"] = prompt_cache_key
                if max_iterations is not None:
                    _loop_kwargs["max_iterations"] = max_iterations
                final_text = await run_agent_loop(
                    self._provider,
                    self.system_prompt,
                    pre_processed,
                    action_tools,
                    db_session,
                    **_loop_kwargs,
                )
                # ``last_usage`` is accumulated across loop turns by the loop.
                self._trace_usage(span, getattr(self._provider, "last_usage", None) or {})
            except Exception as loop_exc:
                span.error(loop_exc)
                raise
            finally:
                self.tools = original_tools
                span.end()
            usage = getattr(self._provider, "last_usage", None) or {}
            response = LLMResponse(
                data={"content": final_text},
                provider=self.provider_type,
                metadata={
                    "agent_name": self.name,
                    "model": self.model_name,
                    "usage": {
                        "input_tokens": int(usage.get("input_tokens", 0)),
                        "output_tokens": int(usage.get("output_tokens", 0)),
                    },
                },
            )
            await self._record_usage(response)
            await self._screen_output(final_text)
            return response

        # Prompt-shaping tools only — original path. Phase SLM2:
        # forward optional ``messages`` so callers with chat history
        # still get prompt-shaping skills applied to the latest turn.
        original_tools = self.tools
        self.tools = list(original_tools) + prompt_tools
        try:
            return await self.analyze(
                input_text,
                context=context,
                messages=messages,
            )
        finally:
            self.tools = original_tools
