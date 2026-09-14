"""MCP (Model Context Protocol) client support for smart-llm.

Adapts external MCP server tools into native ``ActionTool``s so they run through
the existing agent loop and tool-policy gate. Requires ``smart-llm[mcp]``.
"""

from .client import MCPToolChangedError, MCPToolProvider

__all__ = ["MCPToolChangedError", "MCPToolProvider"]
