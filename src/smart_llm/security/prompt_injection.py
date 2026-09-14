"""
Prompt injection detection and filtering tool.

Detects common prompt injection patterns in user input and either
blocks the request or sanitizes the offending segments.
"""

from typing import Any
import logging
import re
import unicodedata

from ..base import Tool

logger = logging.getLogger(__name__)


# Zero-width, bidi-override, and other invisible/format characters attackers
# insert to split trigger phrases ("ig​nore previous…") and slip past regex.
_INVISIBLE_CHARS = (
    "​‌‍‎‏"  # zero-width space/non-joiner/joiner, LRM/RLM
    "‪‫‬‭‮"  # bidi embeddings / overrides
    "⁠﻿"  # word-joiner, BOM/zero-width no-break space
)
_INVISIBLE_RE = re.compile(f"[{_INVISIBLE_CHARS}]")


def _normalize(text: str) -> str:
    """Normalize text before matching so homoglyph/zero-width bypasses fail.

    Applies Unicode NFKC (folds full-width/compatibility homoglyphs to ASCII)
    and strips zero-width / bidi-control characters. Matching runs on this
    normalized form; the *original* text is what gets returned/sanitized.
    """
    if not text:
        return text
    normalized = unicodedata.normalize("NFKC", text)
    return _INVISIBLE_RE.sub("", normalized)


class PromptInjectionError(ValueError):
    """Raised when a prompt injection attempt is detected."""

    def __init__(self, message: str, matched_pattern: str = ""):
        self.matched_pattern = matched_pattern
        super().__init__(message)


# Compiled regex patterns for known injection techniques
_DEFAULT_PATTERNS = [
    # Instruction override
    (
        r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules|context)",
        "instruction_override",
    ),
    (
        r"disregard\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules|context)",
        "instruction_override",
    ),
    (
        r"forget\s+(all\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules|context)",
        "instruction_override",
    ),
    (
        r"do\s+not\s+follow\s+(the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)",
        "instruction_override",
    ),
    (
        r"override\s+(the\s+)?(system|previous|prior)\s+(prompt|instructions|rules)",
        "instruction_override",
    ),
    # Role hijacking
    (r"you\s+are\s+now\s+(a|an|the)\b", "role_hijacking"),
    (r"you\s+must\s+now\s+(act|behave|pretend|respond)\s+as", "role_hijacking"),
    (r"act\s+as\s+(a|an|the|if)\b", "role_hijacking"),
    (r"pretend\s+(to\s+be|you\s+are)", "role_hijacking"),
    (r"from\s+now\s+on[,\s]+(you|your)\s+(are|role|task)", "role_hijacking"),
    # System prompt extraction
    (
        r"(reveal|show|print|display|output|repeat)\s+(your|the)\s+(system\s+)?(prompt|instructions|rules)",
        "system_prompt_extraction",
    ),
    (
        r"what\s+(are|is)\s+your\s+(system\s+)?(prompt|instructions|rules|directives)",
        "system_prompt_extraction",
    ),
    # Delimiter / context injection
    (r"^\s*system\s*:", "delimiter_injection"),
    (r"^\s*\[system\]", "delimiter_injection"),
    (r"^\s*<\|system\|>", "delimiter_injection"),
    (r"<\|im_start\|>", "chatml_injection"),
    (r"<\|im_end\|>", "chatml_injection"),
    (r"<\|endoftext\|>", "chatml_injection"),
    # Encoded/obfuscated injection
    (r"base64[:\s]+(decode|encode)", "encoding_attack"),
    (r"eval\s*\(", "code_injection"),
    (r"exec\s*\(", "code_injection"),
]


class PromptInjectionFilterTool(Tool):
    """
    Detects and handles prompt injection attempts in user input.

    Args:
        mode: "block" raises PromptInjectionError on detection.
              "sanitize" strips offending segments and logs a warning.
        custom_patterns: Optional list of additional regex patterns (strings)
                         to detect. Each is compiled case-insensitively.
        sensitivity: "high" matches all patterns.
                     "medium" skips system_prompt_extraction patterns.
                     "low" only matches instruction_override and chatml_injection.
    """

    def __init__(
        self,
        mode: str = "block",
        custom_patterns: list[str] | None = None,
        sensitivity: str = "high",
    ):
        if mode not in ("block", "sanitize"):
            raise ValueError(f"Invalid mode: {mode!r}. Must be 'block' or 'sanitize'.")
        if sensitivity not in ("high", "medium", "low"):
            raise ValueError(
                f"Invalid sensitivity: {sensitivity!r}. Must be 'high', 'medium', or 'low'."
            )

        self.mode = mode
        self.sensitivity = sensitivity

        # Filter patterns by sensitivity
        sensitivity_filters = {
            "low": {"instruction_override", "chatml_injection"},
            "medium": {
                "instruction_override",
                "chatml_injection",
                "role_hijacking",
                "delimiter_injection",
                "encoding_attack",
                "code_injection",
            },
            "high": None,  # None = include all
        }
        allowed_categories = sensitivity_filters[sensitivity]

        self._patterns = []
        for pattern_str, category in _DEFAULT_PATTERNS:
            if allowed_categories is None or category in allowed_categories:
                self._patterns.append(
                    (re.compile(pattern_str, re.IGNORECASE | re.MULTILINE), category)
                )

        # Add custom patterns
        if custom_patterns:
            for pat in custom_patterns:
                self._patterns.append(
                    (re.compile(pat, re.IGNORECASE | re.MULTILINE), "custom")
                )

    def run(self, input_text: str, **kwargs: Any) -> str:
        """
        Check input text for prompt injection patterns.

        Returns:
            The original or sanitized text.

        Raises:
            PromptInjectionError: If mode is "block" and injection is detected.

        Note: matching runs on a Unicode-normalized, invisible-char-stripped
        copy so homoglyph / zero-width bypasses are caught. In "sanitize" mode
        the returned text is the normalized form (with offending segments
        replaced), since the stripped characters cannot be reliably mapped back
        onto the original.
        """
        input_text = _normalize(input_text)
        for compiled_pattern, category in self._patterns:
            match = compiled_pattern.search(input_text)
            if match:
                matched_text = match.group(0)
                logger.warning(
                    f"Prompt injection detected [category={category}]: "
                    f"matched '{matched_text}'"
                )

                if self.mode == "block":
                    raise PromptInjectionError(
                        f"Prompt injection attempt detected ({category})",
                        matched_pattern=matched_text,
                    )
                else:  # sanitize
                    input_text = compiled_pattern.sub("[FILTERED]", input_text)

        return input_text
