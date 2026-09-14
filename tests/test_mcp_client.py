"""MCP client — discover + adapt external tools into governed ActionTools."""

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.shared.memory import (  # noqa: E402
    create_connected_server_and_client_session,
)

from smart_llm.mcp import MCPToolProvider  # noqa: E402
from smart_llm.mcp.client import _jsonschema_to_model, _sanitize_name  # noqa: E402


def _server() -> FastMCP:
    server = FastMCP("test-server")

    @server.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    return server


@pytest.mark.asyncio
async def test_discovers_and_adapts_tools():
    server = _server()
    async with create_connected_server_and_client_session(server) as session:
        provider = MCPToolProvider(session=session)
        await provider.connect()
        tools = provider.get_action_tools()

    names = [type(t).__name__ for t in tools]
    assert "add" in names  # class name == tool name the LLM calls

    add_tool = next(t for t in tools if type(t).__name__ == "add")
    # External side effect → governed deny-by-default by the ToolPolicyGate.
    assert type(add_tool).effective_risk() == "external"
    # args_model reproduces the server's inputSchema shape for the LLM.
    schema = add_tool.args_model.model_json_schema()
    assert set(schema.get("properties", {})) >= {"a", "b"}


@pytest.mark.asyncio
async def test_call_tool_end_to_end():
    server = _server()
    async with create_connected_server_and_client_session(server) as session:
        provider = MCPToolProvider(session=session)
        await provider.connect()
        add_tool = next(
            t for t in provider.get_action_tools() if type(t).__name__ == "add"
        )
        args = add_tool.args_model(a=2, b=3)
        result = await add_tool.run_action(args, db_session=None)

    # Normalized MCP result carries the computed value.
    assert "5" in str(result)


@pytest.mark.asyncio
async def test_async_context_manager_discovers():
    server = _server()
    async with create_connected_server_and_client_session(server) as session:
        async with MCPToolProvider(session=session) as provider:
            assert any(type(t).__name__ == "add" for t in provider.get_action_tools())


def test_requires_exactly_one_transport():
    with pytest.raises(ValueError):
        MCPToolProvider()  # none supplied


def test_jsonschema_to_model_flat():
    m = _jsonschema_to_model(
        "T",
        {
            "type": "object",
            "properties": {"a": {"type": "integer"}, "b": {"type": "string"}},
            "required": ["a"],
        },
    )
    inst = m(a=1)
    assert inst.a == 1
    props = m.model_json_schema()["properties"]
    assert props["a"]["type"] == "integer"


def test_sanitize_name():
    # dots/spaces → underscore; hyphen kept; capped at 64.
    assert _sanitize_name("weather.get-current") == "weather_get-current"
    assert len(_sanitize_name("x" * 100)) == 64
