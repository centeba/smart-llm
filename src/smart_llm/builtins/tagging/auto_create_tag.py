"""``auto_create_tag`` — post-LLM hook that persists novel tags.

Implemented as an :class:`OutputTool` because the work is *after* the
LLM call: it inspects the parsed response (``data.tags`` and
``data.tag_confidence``) and writes any tag whose confidence exceeds
``threshold`` into the host's tag table.

The host wires the actual persistence callback at startup via
:func:`set_tag_writer`. If no writer is configured the skill is a
no-op (so the agent still runs in environments without a tag store).
"""

import logging
from collections.abc import Callable
from typing import Any

from smart_llm.base import LLMResponse, OutputTool
from smart_llm.db.models import MODALITY_ANY
from smart_llm.registry import register_tool

log = logging.getLogger(__name__)

# Host-injected persistence hook. Signature:
#   writer(tag_name: str, confidence: float, scope: dict) -> None
TagWriter = Callable[[str, float, dict[str, Any]], None]
_writer: TagWriter | None = None


def set_tag_writer(writer: TagWriter) -> None:
    """Hosts call this once at startup to wire the tag-persistence side
    effect. The writer is responsible for de-duplication against its
    own canonical tag table."""
    global _writer
    _writer = writer


class AutoCreateTagSkill(OutputTool):
    """Persists any tag in the LLM response above ``threshold`` confidence."""

    threshold: float = 0.75

    def run(self, response: LLMResponse, **kwargs: Any) -> LLMResponse:
        data = response.data or {}
        tags = data.get("tags") or []
        confs = data.get("tag_confidence") or {}
        if _writer is None:
            log.debug("auto_create_tag: no writer configured; skipping persistence")
            return response

        for t in tags:
            try:
                c = float(confs.get(t, 0.0))
            except (TypeError, ValueError):
                c = 0.0
            if c >= self.threshold:
                try:
                    _writer(t, c, kwargs.get("scope", {}))
                except Exception:  # noqa: BLE001 — never break the agent run
                    log.exception("auto_create_tag: writer raised on tag=%r", t)
        return response


register_tool(
    "auto_create_tag",
    AutoCreateTagSkill,
    label="Auto-Create Tag",
    description=(
        "Persist any high-confidence tag from the LLM response into the "
        "host's tag table. Requires the host to call set_tag_writer()."
    ),
    modality=MODALITY_ANY,
    params_schema={
        "type": "object",
        "properties": {
            "threshold": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "default": 0.75,
            },
        },
    },
)
