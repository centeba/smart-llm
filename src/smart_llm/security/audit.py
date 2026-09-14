"""
Audit logging tools for LLM inputs and outputs.

Provides structured JSON logging of all LLM interactions with
automatic PII stripping for compliance and forensic review.
"""

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from ..base import LLMResponse, OutputTool, Tool
from ..tool import PIIFilterTool

logger = logging.getLogger(__name__)


def _compute_hash(content: str) -> str:
    """Compute a SHA-256 hash of content for correlation."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _strip_pii_from_value(value: Any, pii_filter: Tool) -> Any:
    """Recursively strip PII from a value using the provided filter tool."""
    if isinstance(value, str):
        return pii_filter.run(value)
    elif isinstance(value, dict):
        return {k: _strip_pii_from_value(v, pii_filter) for k, v in value.items()}
    elif isinstance(value, list):
        return [_strip_pii_from_value(item, pii_filter) for item in value]
    return value


class AuditInputTool(Tool):
    """
    Logs input text before it reaches the LLM, with PII stripped.

    This tool does NOT modify the input text — it only logs it.
    Place it at the beginning or end of the tools chain.

    Args:
        logger_name: Name of the Python logger to write to.
        pii_filter: A Tool instance used to strip PII from log entries.
                    Defaults to PIIFilterTool() if not provided.
    """

    def __init__(
        self,
        logger_name: str = "smart_llm.audit",
        pii_filter: Tool | None = None,
    ):
        self._audit_logger = logging.getLogger(logger_name)
        self._pii_filter = pii_filter or PIIFilterTool()

    def run(self, input_text: str, **kwargs: Any) -> str:
        """Log the input text (PII-stripped) and return it unchanged."""
        sanitized_text = self._pii_filter.run(input_text)
        content_hash = _compute_hash(input_text)

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "direction": "input",
            "content_hash": content_hash,
            "sanitized_content": sanitized_text,
            "content_length": len(input_text),
        }

        self._audit_logger.info(json.dumps(log_entry))

        # Return original input unchanged — this tool only logs
        return input_text


class AuditOutputTool(OutputTool):
    """
    Logs LLM response data after the call, with PII stripped.

    This tool does NOT modify the response — it only logs it.
    Place it at the end of the output_tools chain.

    Args:
        logger_name: Name of the Python logger to write to.
        pii_filter: A Tool instance used to strip PII from log entries.
                    Defaults to PIIFilterTool() if not provided.
    """

    def __init__(
        self,
        logger_name: str = "smart_llm.audit",
        pii_filter: Tool | None = None,
    ):
        self._audit_logger = logging.getLogger(logger_name)
        self._pii_filter = pii_filter or PIIFilterTool()

    def run(self, response: LLMResponse, **kwargs: Any) -> LLMResponse:
        """Log the response data (PII-stripped) and return it unchanged."""
        # Serialize and hash the response data
        data_str = json.dumps(response.data, default=str, sort_keys=True)
        content_hash = _compute_hash(data_str)

        # Strip PII from the data for logging
        sanitized_data = _strip_pii_from_value(response.data, self._pii_filter)

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "direction": "output",
            "content_hash": content_hash,
            "sanitized_content": sanitized_data,
            "provider": response.provider,
            "agent_name": response.metadata.get("agent_name", "unknown"),
            "model": response.metadata.get("model", "unknown"),
        }

        self._audit_logger.info(json.dumps(log_entry, default=str))

        # Return response unchanged — this tool only logs
        return response
