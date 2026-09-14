"""``extract_email_fields`` — pull structured fields out of a raw email body.

The Phase-D email-extractor refactor uses this in place of the old
in-service prompt. The directive instructs the LLM to populate a
predictable shape so downstream Mit Stack workflows can index off
``intent`` / ``sender_role`` / ``action_required`` without bespoke
post-processing.
"""

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool
from smart_llm.security.envelope import untrusted_envelope

_DIRECTIVE = (
    "You are an email data extractor. Read the email body below and "
    "return a JSON object with the following fields:\n"
    "  intent: one of [support, sales, billing, contract, other]\n"
    "  sender_role: short noun phrase describing the sender's role "
    "(e.g. 'customer', 'vendor', 'internal')\n"
    "  action_required: short imperative phrase, or null if none\n"
    "  due_date: ISO-8601 date if explicit, else null\n"
    "  parties: array of named people/organisations referenced\n"
    "  summary: 1-2 sentence neutral summary\n"
    "Return only valid JSON — no markdown fences, no commentary."
)


class ExtractEmailFieldsSkill(Tool):
    def run(self, input_text: str, **kwargs: Any) -> str:
        return f"{_DIRECTIVE}\n\n{untrusted_envelope(input_text, label='EMAIL BODY')}"


register_tool(
    "extract_email_fields",
    ExtractEmailFieldsSkill,
    label="Extract Email Fields",
    description="Pull intent/sender_role/action/due_date/parties/summary out of an email body.",
    modality=MODALITY_TEXT,
)
