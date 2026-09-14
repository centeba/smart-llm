"""``classify_intent`` — ask the LLM to classify the input's intent.

The default labels (``support``, ``sales``, ``billing``, ``other``) are
a pragmatic starter set; downstream agent graphs (Phase E2 "Document
Triage") use the result to route to specialised follow-up skills.
"""

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool
from smart_llm.security.envelope import untrusted_envelope

_DIRECTIVE = (
    "Classify the input's intent into exactly one of: "
    "support, sales, billing, contract, other. "
    "Add an 'intent' field to your JSON response with that label."
)


class ClassifyIntentSkill(Tool):
    def run(self, input_text: str, **kwargs: Any) -> str:
        return f"{_DIRECTIVE}\n\n{untrusted_envelope(input_text, label='INPUT')}"


register_tool(
    "classify_intent",
    ClassifyIntentSkill,
    label="Classify Intent",
    description="Add an intent label to the agent's JSON response.",
    modality=MODALITY_TEXT,
)
