import logging
from typing import Any

from .base import Tool

logger = logging.getLogger(__name__)


class ContextPruningTool(Tool):
    """
    A tool that prunes/truncates input text to a maximum character length.
    Ensures agents don't exceed model context limits.
    """

    def __init__(self, max_chars: int = 10000):
        self.max_chars = max_chars

    def run(self, input_text: str, **kwargs: Any) -> str:
        if len(input_text) > self.max_chars:
            logger.info(
                f"Pruning input from {len(input_text)} to {self.max_chars} chars."
            )
            return input_text[: self.max_chars] + "... [TRUNCATED]"
        return input_text


class PIIFilterTool(Tool):
    """
    A mock PII filter tool (placeholder).

    DEPRECATED for egress protection. This destructively redacts only
    16-digit card numbers on a single string and is bypassed by the system
    prompt, context, multi-turn messages, tool results, images, and the
    no-tools broker. Real PII masking on AI egress now lives in
    :mod:`smart_llm.pii` (the :class:`~smart_llm.pii.MaskingProvider` firewall
    wraps the provider so every path is covered). This class is retained only
    as a lightweight log-scrubbing default for
    :mod:`smart_llm.security.audit` and will be removed once that caller
    migrates to the firewall's detector pack.
    """

    def run(self, input_text: str, **kwargs: Any) -> str:
        # Placeholder logic: filter out things that look like credit cards (very basic)
        import re

        processed = re.sub(
            r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b", "[REDACTED CARD]", input_text
        )
        return processed
