import json
import logging

import pytest

from smart_llm.base import LLMResponse
from smart_llm.security.audit import AuditInputTool, AuditOutputTool


@pytest.fixture
def audit_logger(caplog):
    """Set up the audit logger to capture log messages."""
    logger = logging.getLogger("smart_llm.audit")
    logger.setLevel(logging.INFO)
    return logger


@pytest.fixture
def make_response():
    def _make(data, provider="openai", metadata=None):
        return LLMResponse(data=data, provider=provider, metadata=metadata or {})

    return _make


class TestAuditInputTool:
    def test_returns_input_unchanged(self):
        tool = AuditInputTool()
        text = "Hello, analyze this data."
        assert tool.run(text) == text

    def test_logs_input_entry(self, caplog):
        tool = AuditInputTool()
        with caplog.at_level(logging.INFO, logger="smart_llm.audit"):
            tool.run("Test input text")

        assert len(caplog.records) == 1
        log_entry = json.loads(caplog.records[0].message)
        assert log_entry["direction"] == "input"
        assert "timestamp" in log_entry
        assert "content_hash" in log_entry
        assert log_entry["sanitized_content"] == "Test input text"
        assert log_entry["content_length"] == len("Test input text")

    def test_strips_pii_from_log(self, caplog):
        tool = AuditInputTool()
        text_with_pii = "My card is 1234-5678-9012-3456"
        with caplog.at_level(logging.INFO, logger="smart_llm.audit"):
            result = tool.run(text_with_pii)

        # Original text returned unchanged
        assert result == text_with_pii

        # But log entry has PII stripped
        log_entry = json.loads(caplog.records[0].message)
        assert "1234-5678-9012-3456" not in log_entry["sanitized_content"]
        assert "[REDACTED CARD]" in log_entry["sanitized_content"]

    def test_content_hash_is_consistent(self, caplog):
        tool = AuditInputTool()
        text = "consistent hash test"
        with caplog.at_level(logging.INFO, logger="smart_llm.audit"):
            tool.run(text)
            tool.run(text)

        entry1 = json.loads(caplog.records[0].message)
        entry2 = json.loads(caplog.records[1].message)
        assert entry1["content_hash"] == entry2["content_hash"]

    def test_custom_pii_filter(self, caplog):
        """Test using a custom PII filter tool."""
        from smart_llm.base import Tool

        class EmailFilter(Tool):
            def run(self, input_text, **kwargs):
                import re

                return re.sub(r"\S+@\S+\.\S+", "[EMAIL REDACTED]", input_text)

        tool = AuditInputTool(pii_filter=EmailFilter())
        with caplog.at_level(logging.INFO, logger="smart_llm.audit"):
            result = tool.run("Contact me at test@example.com")

        assert result == "Contact me at test@example.com"  # unchanged
        log_entry = json.loads(caplog.records[0].message)
        assert "[EMAIL REDACTED]" in log_entry["sanitized_content"]


class TestAuditOutputTool:
    def test_returns_response_unchanged(self, make_response):
        tool = AuditOutputTool()
        resp = make_response(
            {"result": "success"},
            metadata={"agent_name": "test_agent", "model": "gpt-4"},
        )
        result = tool.run(resp)
        assert result.data == resp.data
        assert result.provider == resp.provider
        assert result.metadata == resp.metadata

    def test_logs_output_entry(self, caplog, make_response):
        tool = AuditOutputTool()
        resp = make_response(
            {"answer": "42"},
            metadata={"agent_name": "test_agent", "model": "gpt-4"},
        )
        with caplog.at_level(logging.INFO, logger="smart_llm.audit"):
            tool.run(resp)

        assert len(caplog.records) == 1
        log_entry = json.loads(caplog.records[0].message)
        assert log_entry["direction"] == "output"
        assert "timestamp" in log_entry
        assert "content_hash" in log_entry
        assert log_entry["provider"] == "openai"
        assert log_entry["agent_name"] == "test_agent"
        assert log_entry["model"] == "gpt-4"

    def test_strips_pii_from_output_log(self, caplog, make_response):
        tool = AuditOutputTool()
        resp = make_response({"customer": "Card: 1234-5678-9012-3456"})
        with caplog.at_level(logging.INFO, logger="smart_llm.audit"):
            result = tool.run(resp)

        # Response data unchanged
        assert "1234-5678-9012-3456" in result.data["customer"]

        # Log entry has PII stripped
        log_entry = json.loads(caplog.records[0].message)
        sanitized = log_entry["sanitized_content"]
        assert "1234-5678-9012-3456" not in str(sanitized)
        assert "[REDACTED CARD]" in str(sanitized)
