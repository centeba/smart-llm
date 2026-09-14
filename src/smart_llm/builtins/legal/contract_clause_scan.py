"""``contract_clause_scan`` — extract notable clauses from a contract."""

from typing import Any

from smart_llm.base import Tool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool
from smart_llm.security.envelope import untrusted_envelope

_DIRECTIVE = (
    "Scan the contract text below and return JSON with a 'clauses' "
    "array. Each item: { type, summary, span: [start, end] }. "
    "Cover at minimum: termination, payment, liability, "
    "confidentiality, IP assignment, indemnity, governing law, "
    "auto-renewal. Omit a clause type rather than guess if absent."
)


class ContractClauseScanSkill(Tool):
    def run(self, input_text: str, **kwargs: Any) -> str:
        return f"{_DIRECTIVE}\n\n{untrusted_envelope(input_text, label='CONTRACT')}"


register_tool(
    "contract_clause_scan",
    ContractClauseScanSkill,
    label="Contract Clause Scan",
    description="Identify notable contract clauses (termination, IP, indemnity, …).",
    modality=MODALITY_TEXT,
)
