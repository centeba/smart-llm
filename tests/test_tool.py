from smart_llm.tool import ContextPruningTool, PIIFilterTool


def test_context_pruning_tool():
    """Verify tool correctly truncates long text."""
    tool = ContextPruningTool(max_chars=10)

    # Under limit
    assert tool.run("hello") == "hello"

    # Over limit
    result = tool.run("this is a very long string")
    assert result.startswith("this is a ")
    assert "[TRUNCATED]" in result
    assert len(result) > 10  # because of the suffix


def test_pii_filter_tool():
    """Verify tool redacts credit-card-like numbers."""
    tool = PIIFilterTool()
    input_text = "My card number is 1234-5678-9012-3456."
    expected = "My card number is [REDACTED CARD]."
    assert tool.run(input_text) == expected


def test_pii_filter_tool_no_matches():
    """Verify tool returns original text if no PII found."""
    tool = PIIFilterTool()
    input_text = "Hello world!"
    assert tool.run(input_text) == "Hello world!"
