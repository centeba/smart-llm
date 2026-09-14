"""``summarize`` — ask the LLM for a concise summary of the input."""

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool
from smart_llm.security.envelope import untrusted_envelope

_DIRECTIVE = (
    "Produce a concise (3-5 sentences) summary of the following content "
    "in a 'summary' field of your JSON response."
)


class SummarizeSkill(Tool):
    def run(self, input_text: str, **kwargs: Any) -> str:
        return f"{_DIRECTIVE}\n\n{untrusted_envelope(input_text, label='CONTENT')}"


register_tool(
    "summarize",
    SummarizeSkill,
    label="Summarize",
    description="Add a short summary field to the agent's response.",
    modality=MODALITY_TEXT,
    params_schema={
        "type": "object",
        "properties": {
            "max_sentences": {
                "type": "integer",
                "minimum": 1,
                "maximum": 20,
                "default": 5,
            },
            "style": {
                "type": "string",
                "enum": ["neutral", "bullet", "executive"],
                "default": "neutral",
            },
        },
    },
)
