"""The PII masking firewall — tokenisation, payload walking, re-hydration.

All masking lives here (and in :class:`smart_llm.pii.masking_provider`); no
service ever transforms text itself. The firewall:

* detects PII in every outbound content shape the four providers accept
  (plain string, chat messages, Anthropic content blocks, OpenAI tool-call
  argument JSON, Gemini parts),
* replaces each value with a stable, per-request placeholder ``U+27E6 TYPE_N
  U+27E7`` held in an in-memory :class:`TokenVault` (PII is never persisted or
  logged), and
* re-hydrates those placeholders back into the model's output — including
  token-boundary-safe re-hydration of streamed deltas via
  :class:`StreamRestorer`.
"""

import json
import logging
from collections.abc import Iterable
from typing import Any

from .detectors import (
    CompositeDetector,
    Detector,
    RegexDetector,
    load_entry_point_detectors,
)

logger = logging.getLogger(__name__)

# Placeholder brackets — U+27E6 / U+27E7 (mathematical white square brackets).
# Chosen because they essentially never occur in real prompts or model output,
# so a stray bracket won't be mistaken for a token boundary.
_OPEN = "⟦"
_CLOSE = "⟧"


class PiiMaskingError(RuntimeError):
    """Raised (under ``enforce``/``strict``) when masking cannot complete, so
    the provider call is aborted *before* any raw content egresses."""


class TokenVault:
    """Per-request, in-memory bidirectional map between PII values and their
    placeholder tokens.

    One vault is created per :class:`~smart_llm.pii.masking_provider.MaskingProvider`
    instance — i.e. per request — so a given value gets the *same* token across
    every turn of one agent loop (letting the model correlate it) while never
    leaking across requests. Nothing here is ever written to a DB or a log.
    """

    def __init__(self, hints: Iterable[tuple[str, str]] | None = None) -> None:
        self._to_token: dict[str, str] = {}
        self._to_value: dict[str, str] = {}
        self._counts: dict[str, int] = {}
        # Declared-field hints: exact (value, type) pairs the owning service
        # marked as PII (e.g. a person's name a regex can't catch). Pre-minted
        # here and force-masked by :meth:`apply_hints` before detection runs, so
        # declared values are tokenised with 100% precision. Ordered longest
        # value first so a longer value is replaced before any shorter substring
        # of it. The masking act still happens only in the firewall — services
        # supply these as data, never as a transform.
        self._hint_values: list[str] = []
        for value, pii_type in hints or []:
            if isinstance(value, str) and value:
                self.tokenize(value, pii_type or "PII")
                self._hint_values.append(value)
        self._hint_values.sort(key=len, reverse=True)

    def tokenize(self, value: str, pii_type: str) -> str:
        """Return a stable placeholder for ``value``, minting one on first sight."""
        existing = self._to_token.get(value)
        if existing is not None:
            return existing
        n = self._counts.get(pii_type, 0) + 1
        self._counts[pii_type] = n
        token = f"{_OPEN}{pii_type}_{n}{_CLOSE}"
        self._to_token[value] = token
        self._to_value[token] = value
        return token

    def apply_hints(self, text: str) -> str:
        """Force-mask declared hint values (exact, longest-first) before the
        detector runs. No-op when the request carried no hints."""
        if not text or not self._hint_values:
            return text
        for value in self._hint_values:
            if value in text:
                text = text.replace(value, self._to_token[value])
        return text

    def restore_text(self, text: str) -> str:
        """Swap every known placeholder in ``text`` back to its real value."""
        if not text or _OPEN not in text:
            return text
        for token, value in self._to_value.items():
            if token in text:
                text = text.replace(token, value)
        return text

    @property
    def is_empty(self) -> bool:
        return not self._to_value

    def token_count(self) -> int:
        return len(self._to_value)

    def type_counts(self) -> dict[str, int]:
        return dict(self._counts)


class PiiFirewall:
    """Stateless masker/re-hydrator over a shared :class:`~.detectors.Detector`.

    The firewall holds no per-request state — all mutable state lives in the
    :class:`TokenVault` passed to each call — so a single instance is safely
    shared across every request as a process-wide singleton.
    """

    def __init__(
        self,
        detector: Detector | None = None,
        categories: list[str] | None = None,
    ):
        if detector is None:
            detectors: list[Detector] = [RegexDetector(categories=categories)]
            detectors.extend(load_entry_point_detectors())
            detector = (
                detectors[0] if len(detectors) == 1 else CompositeDetector(detectors)
            )
        self._detector = detector

    # ── Text + generic JSON ────────────────────────────────────────────────

    def mask_text(self, text: str, vault: TokenVault) -> str:
        if not text:
            return text
        # Declared-field hints first (exact values), then the detector on what
        # remains — detector patterns never match the placeholder glyphs, so the
        # two passes compose cleanly.
        text = vault.apply_hints(text)
        matches = self._detector.detect(text)
        if not matches:
            return text
        out: list[str] = []
        last = 0
        for m in sorted(matches, key=lambda x: x.start):
            if m.start < last:
                continue  # defensive: skip any residual overlap
            out.append(text[last : m.start])
            out.append(vault.tokenize(m.value, m.type))
            last = m.end
        out.append(text[last:])
        return "".join(out)

    def mask_obj(self, obj: Any, vault: TokenVault) -> Any:
        """Recursively mask every string leaf of a JSON-like structure."""
        if isinstance(obj, str):
            return self.mask_text(obj, vault)
        if isinstance(obj, dict):
            return {k: self.mask_obj(v, vault) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self.mask_obj(v, vault) for v in obj]
        return obj

    def restore_obj(self, obj: Any, vault: TokenVault) -> Any:
        """Recursively re-hydrate placeholders in a JSON-like structure."""
        if isinstance(obj, str):
            return vault.restore_text(obj)
        if isinstance(obj, dict):
            return {k: self.restore_obj(v, vault) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self.restore_obj(v, vault) for v in obj]
        return obj

    # ── Provider payloads ───────────────────────────────────────────────────

    def mask_payload(
        self,
        system: Any,
        provider_input: Any,
        vault: TokenVault,
    ) -> tuple[Any, Any]:
        """Mask a ``(system_prompt, provider_input)`` pair.

        ``provider_input`` is either a plain string (single-turn) or a list of
        message dicts (multi-turn / tool-calling). Every text-bearing leaf is
        masked; image bytes and structural fields (ids, roles, media types) are
        left untouched.
        """
        masked_system = (
            self.mask_text(system, vault) if isinstance(system, str) else system
        )
        masked_input = self._mask_provider_input(provider_input, vault)
        return masked_system, masked_input

    def _mask_provider_input(self, provider_input: Any, vault: TokenVault) -> Any:
        if isinstance(provider_input, str):
            return self.mask_text(provider_input, vault)
        if isinstance(provider_input, list):
            return [self._mask_message(m, vault) for m in provider_input]
        return provider_input

    def _mask_message(self, msg: Any, vault: TokenVault) -> Any:
        if not isinstance(msg, dict):
            return msg
        out = dict(msg)
        if "content" in out:
            out["content"] = self._mask_content(out["content"], vault)
        if isinstance(out.get("tool_calls"), list):  # OpenAI assistant tool calls
            out["tool_calls"] = [
                self._mask_tool_call(tc, vault) for tc in out["tool_calls"]
            ]
        if isinstance(out.get("parts"), list):  # Gemini contents
            out["parts"] = [self._mask_gemini_part(p, vault) for p in out["parts"]]
        return out

    def _mask_content(self, content: Any, vault: TokenVault) -> Any:
        if isinstance(content, str):
            return self.mask_text(content, vault)
        if isinstance(content, list):  # Anthropic content-block list
            return [self._mask_block(b, vault) for b in content]
        return content

    def _mask_block(self, block: Any, vault: TokenVault) -> Any:
        if not isinstance(block, dict):
            return block
        btype = block.get("type")
        out = dict(block)
        if btype == "text" and isinstance(out.get("text"), str):
            out["text"] = self.mask_text(out["text"], vault)
        elif btype == "tool_use" and "input" in out:
            out["input"] = self.mask_obj(out["input"], vault)
        elif btype == "tool_result" and "content" in out:
            out["content"] = self._mask_content(out["content"], vault)
        # image blocks carry base64 bytes, not text — left untouched (vision is
        # gated separately by the MaskingProvider under an active policy).
        return out

    def _mask_tool_call(self, tc: Any, vault: TokenVault) -> Any:
        if not isinstance(tc, dict):
            return tc
        out = dict(tc)
        fn = out.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("arguments"), str):
            fn = dict(fn)
            fn["arguments"] = self._mask_json_string(fn["arguments"], vault)
            out["function"] = fn
        return out

    def _mask_gemini_part(self, part: Any, vault: TokenVault) -> Any:
        if not isinstance(part, dict):
            return part
        out = dict(part)
        if isinstance(out.get("text"), str):
            out["text"] = self.mask_text(out["text"], vault)
        fc = out.get("function_call")
        if isinstance(fc, dict) and "args" in fc:
            fc = dict(fc)
            fc["args"] = self.mask_obj(fc["args"], vault)
            out["function_call"] = fc
        fr = out.get("function_response")
        if isinstance(fr, dict) and "response" in fr:
            fr = dict(fr)
            fr["response"] = self.mask_obj(fr["response"], vault)
            out["function_response"] = fr
        return out

    def _mask_json_string(self, s: str, vault: TokenVault) -> str:
        """Mask the string leaves of a JSON-encoded tool-argument blob.

        Re-serialised so the wire shape stays valid JSON. The detector value
        set (SSN/card/email/phone/IBAN/IP/DOB/MRN) contains no JSON-special
        characters, so re-hydration downstream keeps the JSON parseable.
        """
        try:
            parsed = json.loads(s)
        except (json.JSONDecodeError, TypeError):
            return self.mask_text(s, vault)
        # ensure_ascii=False keeps the placeholder glyphs (U+27E6/27E7) literal
        # on the wire rather than as \uXXXX escapes, so string-level
        # re-hydration stays uniform end to end.
        return json.dumps(self.mask_obj(parsed, vault), ensure_ascii=False)


class StreamRestorer:
    """Token-boundary-safe re-hydrator for streamed text deltas.

    Provider streams split text at arbitrary byte boundaries, so a placeholder
    like ``U+27E6 SSN_1 U+27E7`` can arrive across two chunks. This buffers only
    the shortest suffix that could still become a placeholder — everything
    before the last unmatched opening bracket is safe to emit — and flushes the
    remainder when the stream ends.
    """

    def __init__(self, vault: TokenVault):
        self._vault = vault
        self._buf = ""

    def push(self, delta: str) -> str:
        """Feed a raw delta; return the re-hydrated text safe to emit now."""
        if not delta:
            return ""
        self._buf += delta
        idx = self._buf.rfind(_OPEN)
        if idx != -1 and _CLOSE not in self._buf[idx:]:
            # A dangling opener → hold from it in case a token completes next.
            emit = self._buf[:idx]
            self._buf = self._buf[idx:]
        else:
            emit = self._buf
            self._buf = ""
        return self._vault.restore_text(emit)

    def flush(self) -> str:
        """Emit and clear whatever remains buffered at end-of-stream."""
        out = self._vault.restore_text(self._buf)
        self._buf = ""
        return out
