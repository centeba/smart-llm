"""
Output sanitization tool for LLM responses.

Recursively sanitizes string values in LLM response data to remove
potentially dangerous content like HTML/scripts, invalid URLs,
and embedded executable code.
"""

import logging
import re
from typing import Any
from urllib.parse import urlparse

from ..base import LLMResponse, OutputTool

logger = logging.getLogger(__name__)

# Patterns for sanitization
_SCRIPT_TAG_PATTERN = re.compile(
    r"<script[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL
)
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_STYLE_TAG_PATTERN = re.compile(r"<style[^>]*>.*?</style>", re.IGNORECASE | re.DOTALL)
_EVENT_HANDLER_PATTERN = re.compile(r"\bon\w+\s*=\s*[\"'][^\"']*[\"']", re.IGNORECASE)
_URL_PATTERN = re.compile(
    r"https?://[^\s<>\"']+|"
    r"(?:javascript|data|vbscript):[^\s<>\"']+",
    re.IGNORECASE,
)
_CODE_BLOCK_PATTERN = re.compile(
    r"```(?:python|bash|sh|javascript|js|typescript|ts|ruby|perl|php|"
    r"powershell|cmd|shell|sql|exec|eval)\b[^`]*```",
    re.IGNORECASE | re.DOTALL,
)

_DANGEROUS_SCHEMES = {"javascript", "data", "vbscript", "file"}


class OutputSanitizationTool(OutputTool):
    """
    Sanitizes LLM response data by removing potentially dangerous content.

    Args:
        strip_html: Remove HTML tags and script content from string values.
        validate_urls: Check URLs for dangerous schemes.
        allowed_url_schemes: Set of allowed URL schemes (default: {"http", "https"}).
        strip_code_blocks: Remove fenced code blocks with executable languages.
        allowed_domains: Optional set of allowed URL domains. If set, URLs
                         with other domains are replaced with [URL REMOVED].
    """

    def __init__(
        self,
        strip_html: bool = True,
        validate_urls: bool = True,
        allowed_url_schemes: set[str] | None = None,
        strip_code_blocks: bool = False,
        allowed_domains: set[str] | None = None,
    ):
        self.strip_html = strip_html
        self.validate_urls = validate_urls
        self.allowed_url_schemes = allowed_url_schemes or {"http", "https"}
        self.strip_code_blocks = strip_code_blocks
        self.allowed_domains = allowed_domains

    def _sanitize_string(self, value: str) -> str:
        """Sanitize a single string value."""
        result = value

        if self.strip_html:
            # Remove script tags and their content first
            result = _SCRIPT_TAG_PATTERN.sub("", result)
            # Remove style tags and their content
            result = _STYLE_TAG_PATTERN.sub("", result)
            # Remove event handlers (onclick, onload, etc.)
            result = _EVENT_HANDLER_PATTERN.sub("", result)
            # Remove remaining HTML tags
            result = _HTML_TAG_PATTERN.sub("", result)

        if self.validate_urls:

            def _check_url(match: re.Match[str]) -> str:
                url = match.group(0)
                try:
                    parsed = urlparse(url)
                    scheme = parsed.scheme.lower()

                    # Block dangerous schemes
                    if scheme in _DANGEROUS_SCHEMES:
                        logger.warning(f"Blocked dangerous URL scheme: {scheme}://...")
                        return "[URL REMOVED]"

                    # Check against allowed schemes
                    if scheme and scheme not in self.allowed_url_schemes:
                        logger.warning(f"Blocked disallowed URL scheme: {scheme}://...")
                        return "[URL REMOVED]"

                    # Check against allowed domains
                    if self.allowed_domains and parsed.hostname:
                        if parsed.hostname not in self.allowed_domains:
                            logger.warning(
                                f"Blocked URL with disallowed domain: {parsed.hostname}"
                            )
                            return "[URL REMOVED]"

                except Exception:
                    return "[URL REMOVED]"

                return url

            result = _URL_PATTERN.sub(_check_url, result)

        if self.strip_code_blocks:
            result = _CODE_BLOCK_PATTERN.sub("[CODE BLOCK REMOVED]", result)

        return result

    def _sanitize_value(self, value: Any) -> Any:
        """Recursively sanitize a value (string, dict, list, or other)."""
        if isinstance(value, str):
            return self._sanitize_string(value)
        elif isinstance(value, dict):
            return {k: self._sanitize_value(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._sanitize_value(item) for item in value]
        return value

    def run(self, response: LLMResponse, **kwargs: Any) -> LLMResponse:
        """
        Sanitize all string values in the response data.

        Returns a new LLMResponse with sanitized data and updated metadata.
        """
        sanitized_data = self._sanitize_value(response.data)

        updated_metadata = {**response.metadata, "sanitization_applied": True}

        return response.model_copy(
            update={"data": sanitized_data, "metadata": updated_metadata}
        )
