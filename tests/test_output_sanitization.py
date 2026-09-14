import pytest

from smart_llm.base import LLMResponse
from smart_llm.security.output_sanitization import OutputSanitizationTool


@pytest.fixture
def make_response():
    """Helper to create LLMResponse with arbitrary data."""

    def _make(data, provider="openai", metadata=None):
        return LLMResponse(data=data, provider=provider, metadata=metadata or {})

    return _make


class TestHTMLStripping:
    def test_strips_script_tags(self, make_response):
        tool = OutputSanitizationTool(strip_html=True)
        resp = make_response({"text": "Hello <script>alert('xss')</script> world"})
        result = tool.run(resp)
        assert "<script>" not in result.data["text"]
        assert "alert" not in result.data["text"]
        assert "Hello" in result.data["text"]
        assert "world" in result.data["text"]

    def test_strips_style_tags(self, make_response):
        tool = OutputSanitizationTool(strip_html=True)
        resp = make_response({"text": "Hello <style>body{display:none}</style> world"})
        result = tool.run(resp)
        assert "<style>" not in result.data["text"]

    def test_strips_html_tags(self, make_response):
        tool = OutputSanitizationTool(strip_html=True)
        resp = make_response({"text": "<b>Bold</b> and <i>italic</i>"})
        result = tool.run(resp)
        assert "<b>" not in result.data["text"]
        assert "Bold" in result.data["text"]

    def test_strips_event_handlers(self, make_response):
        tool = OutputSanitizationTool(strip_html=True)
        resp = make_response({"text": '<img onerror="alert(1)" src="x">'})
        result = tool.run(resp)
        assert "onerror" not in result.data["text"]

    def test_no_strip_when_disabled(self, make_response):
        tool = OutputSanitizationTool(strip_html=False, validate_urls=False)
        resp = make_response({"text": "<b>Bold</b>"})
        result = tool.run(resp)
        assert "<b>Bold</b>" in result.data["text"]


class TestURLValidation:
    def test_allows_https_urls(self, make_response):
        tool = OutputSanitizationTool(validate_urls=True)
        resp = make_response({"link": "https://example.com/page"})
        result = tool.run(resp)
        assert result.data["link"] == "https://example.com/page"

    def test_blocks_javascript_urls(self, make_response):
        tool = OutputSanitizationTool(validate_urls=True)
        resp = make_response({"link": "javascript:alert(1)"})
        result = tool.run(resp)
        assert "[URL REMOVED]" in result.data["link"]

    def test_blocks_data_urls(self, make_response):
        tool = OutputSanitizationTool(validate_urls=True)
        resp = make_response({"link": "data:text/html,<script>alert(1)</script>"})
        result = tool.run(resp)
        assert "[URL REMOVED]" in result.data["link"]

    def test_allowed_domains(self, make_response):
        tool = OutputSanitizationTool(
            validate_urls=True,
            allowed_domains={"trusted.com"},
        )
        resp = make_response({"link": "https://evil.com/phish"})
        result = tool.run(resp)
        assert "[URL REMOVED]" in result.data["link"]

    def test_allowed_domains_passes_trusted(self, make_response):
        tool = OutputSanitizationTool(
            validate_urls=True,
            allowed_domains={"trusted.com"},
        )
        resp = make_response({"link": "https://trusted.com/page"})
        result = tool.run(resp)
        assert result.data["link"] == "https://trusted.com/page"


class TestCodeBlockStripping:
    def test_strips_python_code_blocks(self, make_response):
        tool = OutputSanitizationTool(strip_code_blocks=True)
        resp = make_response(
            {
                "text": "Here is code:\n```python\nimport os\nos.system('rm -rf /')\n```\nEnd."
            }
        )
        result = tool.run(resp)
        assert "[CODE BLOCK REMOVED]" in result.data["text"]
        assert "os.system" not in result.data["text"]

    def test_preserves_non_executable_code_blocks(self, make_response):
        tool = OutputSanitizationTool(strip_code_blocks=True)
        resp = make_response({"text": '```json\n{"key": "value"}\n```'})
        result = tool.run(resp)
        # json is not in the executable list, should be preserved
        assert '{"key": "value"}' in result.data["text"]


class TestNestedTraversal:
    def test_sanitizes_nested_dicts(self, make_response):
        tool = OutputSanitizationTool(strip_html=True)
        resp = make_response({"outer": {"inner": "<script>bad</script>clean"}})
        result = tool.run(resp)
        assert "<script>" not in result.data["outer"]["inner"]
        assert "clean" in result.data["outer"]["inner"]

    def test_sanitizes_lists(self, make_response):
        tool = OutputSanitizationTool(strip_html=True)
        resp = make_response({"items": ["<b>one</b>", "<i>two</i>", "three"]})
        result = tool.run(resp)
        assert "<b>" not in result.data["items"][0]
        assert "one" in result.data["items"][0]

    def test_leaves_non_strings_alone(self, make_response):
        tool = OutputSanitizationTool(strip_html=True)
        resp = make_response(
            {
                "count": 42,
                "active": True,
                "tags": None,
            }
        )
        result = tool.run(resp)
        assert result.data["count"] == 42
        assert result.data["active"] is True


class TestMetadata:
    def test_sets_sanitization_flag(self, make_response):
        tool = OutputSanitizationTool()
        resp = make_response({"text": "hello"})
        result = tool.run(resp)
        assert result.metadata["sanitization_applied"] is True

    def test_preserves_existing_metadata(self, make_response):
        tool = OutputSanitizationTool()
        resp = make_response({"text": "hello"}, metadata={"agent_name": "test"})
        result = tool.run(resp)
        assert result.metadata["agent_name"] == "test"
        assert result.metadata["sanitization_applied"] is True
