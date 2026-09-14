"""Tamper-evident audit hash-chain + tool-policy gate integration."""

import pytest
from pydantic import BaseModel

from smart_llm.security.audit_chain import GENESIS, AuditChain, verify_chain
from smart_llm.security.tool_policy import AgentRunContext, ToolPolicyGate


def test_stamp_links_records():
    chain = AuditChain()
    r1 = chain.stamp({"tool": "a", "decision": "allow"})
    r2 = chain.stamp({"tool": "b", "decision": "deny"})
    assert r1["prev_hash"] == GENESIS
    assert r2["prev_hash"] == r1["record_hash"]
    assert r1["record_hash"] != r2["record_hash"]


def test_verify_valid_chain():
    chain = AuditChain()
    records = [chain.stamp({"i": i}) for i in range(5)]
    assert verify_chain(records) is True


def test_verify_detects_mutation():
    chain = AuditChain()
    records = [chain.stamp({"i": i}) for i in range(5)]
    records[2] = {**records[2], "i": 999}  # tamper with the content
    assert verify_chain(records) is False


def test_verify_detects_deletion():
    chain = AuditChain()
    records = [chain.stamp({"i": i}) for i in range(5)]
    del records[2]  # remove a record → link breaks
    assert verify_chain(records) is False


def test_verify_detects_reorder():
    chain = AuditChain()
    records = [chain.stamp({"i": i}) for i in range(3)]
    records[0], records[1] = records[1], records[0]
    assert verify_chain(records) is False


def test_verify_detects_forged_record_hash():
    chain = AuditChain()
    records = [chain.stamp({"i": i}) for i in range(3)]
    records[1] = {**records[1], "record_hash": "f" * 64}
    assert verify_chain(records) is False


def test_chain_continues_across_runs():
    c1 = AuditChain()
    a = [c1.stamp({"i": 0}), c1.stamp({"i": 1})]
    # A new run seeds from the last record_hash → one continuous chain.
    c2 = AuditChain(head=c1.head)
    b = [c2.stamp({"i": 2})]
    assert verify_chain(a + b) is True


# ── gate integration ─────────────────────────────────────────────────────────


class _Args(BaseModel):
    pass


class _ReadTool:
    @classmethod
    def effective_risk(cls):
        return "read"


@pytest.mark.asyncio
async def test_gate_stamps_chained_audit_rows():
    captured: list[dict] = []

    async def sink(audit):
        captured.append(audit)

    chain = AuditChain()
    ctx = AgentRunContext(
        agent_id="ag",
        acting_company_id="co",
        tool_modes={"ReadThing": "allow", "Other": "allow"},
        audit_sink=sink,
        audit_chain=chain,
    )
    gate = ToolPolicyGate(ctx)
    await gate.evaluate(tool_name="ReadThing", tool_cls=_ReadTool, validated_args=_Args())
    await gate.evaluate(tool_name="Other", tool_cls=_ReadTool, validated_args=_Args())

    assert len(captured) == 2
    assert all("record_hash" in r and "prev_hash" in r for r in captured)
    assert verify_chain(captured) is True
    # Tampering with a persisted decision is detectable.
    captured[0] = {**captured[0], "decision": "deny"}
    assert verify_chain(captured) is False
