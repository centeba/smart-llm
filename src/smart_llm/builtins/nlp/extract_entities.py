"""``extract_entities`` — instruct the LLM to enumerate named entities."""

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool
from smart_llm.security.envelope import untrusted_envelope

_DIRECTIVE = (
    "When responding, also include an 'entities' field listing every "
    "named entity (person, org, location, date, money) found in the input."
)


class ExtractEntitiesSkill(Tool):
    def run(self, input_text: str, **kwargs: Any) -> str:
        return f"{_DIRECTIVE}\n\n{untrusted_envelope(input_text, label='INPUT')}"


register_tool(
    "extract_entities",
    ExtractEntitiesSkill,
    label="Extract Entities",
    description="Instruct the agent to extract named entities from the input.",
    modality=MODALITY_TEXT,
)
