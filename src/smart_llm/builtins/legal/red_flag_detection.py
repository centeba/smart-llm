"""``red_flag_detection`` — surface high-risk clauses in a contract."""

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool
from smart_llm.security.envelope import untrusted_envelope

_DIRECTIVE = (
    "Read the contract text and return JSON with a 'red_flags' array. "
    "Each item: { severity: high|medium|low, category, snippet, "
    "explanation }. Look for: unilateral termination, uncapped "
    "liability, broad indemnification, perpetual IP grants, automatic "
    "renewal without notice, jurisdictions hostile to the buyer, "
    "non-compete clauses extending past termination. "
    "Return [] if nothing notable is found — do not invent risks."
)


class RedFlagDetectionSkill(Tool):
    def run(self, input_text: str, **kwargs: Any) -> str:
        return f"{_DIRECTIVE}\n\n{untrusted_envelope(input_text, label='CONTRACT')}"


register_tool(
    "red_flag_detection",
    RedFlagDetectionSkill,
    label="Red Flag Detection",
    description="Surface high-risk clauses + severity in a contract.",
    modality=MODALITY_TEXT,
)
