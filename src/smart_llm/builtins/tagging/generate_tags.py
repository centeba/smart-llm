"""``generate_tags`` — instruct the LLM to produce a JSON tag list."""

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_ANY
from smart_llm.registry import register_tool
from smart_llm.security.envelope import untrusted_envelope

_DIRECTIVE = (
    "Produce 3 to 8 short, lowercase, kebab-case tags describing the "
    "subject and type of the input. Tags must be 1-3 words each, no "
    "emoji or punctuation, never PII. Return them in a 'tags' field "
    "of your JSON response, plus a 'confidence' (0.0-1.0) per tag in "
    "a parallel 'tag_confidence' object keyed by tag string."
)


class GenerateTagsSkill(Tool):
    def run(self, input_text: str, **kwargs: Any) -> str:
        return f"{_DIRECTIVE}\n\n{untrusted_envelope(input_text, label='INPUT')}"


register_tool(
    "generate_tags",
    GenerateTagsSkill,
    label="Generate Tags",
    description="Ask the agent to suggest tags + confidence for the input.",
    modality=MODALITY_ANY,
    params_schema={
        "type": "object",
        "properties": {
            "max_tags": {"type": "integer", "minimum": 1, "maximum": 20, "default": 8},
        },
    },
)
