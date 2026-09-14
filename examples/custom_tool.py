"""Example: add your own tool / integration to smart-llm.

smart-llm ships generic built-in tools (calculate, web_search, scraper, …) but
deliberately does NOT ship vendor-specific integration adapters (Stripe, Gmail,
…) — those belong to your own backend. There are two supported extension paths:

  1. Subclass ``ActionTool`` (shown below) — for a tool you implement in Python.
  2. Point the MCP client at a tool server — for tools exposed over the Model
     Context Protocol (see ``smart_llm.mcp.client`` and the note at the bottom).

Run:  python examples/custom_tool.py
"""

import asyncio
from typing import Any, cast

import httpx
from pydantic import BaseModel, Field

from smart_llm.base import ActionTool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool

# ── 1. A custom ActionTool ───────────────────────────────────────────────────


class GetJoke(BaseModel):
    """Typed args — the registry derives a JSON schema from this."""

    category: str = Field("Any", description="Joke category, e.g. 'Programming'.")


class JokeTool(ActionTool):
    args_model = GetJoke

    # Risk tier governs the autonomous-agent policy gate. This tool reaches an
    # external service, so mark it ``external`` (the strictest tier) — the gate
    # then requires an explicit allow before it will dispatch. A pure read of
    # your own data would use ``read``; a write would use ``write``.
    risk = "external"

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        # ``db_session`` is injected by the runtime; tools that need no DB ignore it.
        cat = cast(GetJoke, args).category
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"https://v2.jokeapi.dev/joke/{cat}?type=single"
                )
                resp.raise_for_status()
                return {"joke": resp.json().get("joke", "")}
        except Exception as exc:  # never raise into the agent loop
            return {"error": f"joke fetch failed: {exc}"}


register_tool(
    "get_joke",
    JokeTool,
    label="Get Joke",
    description="Fetch a single joke from a public API (example external tool).",
    modality=MODALITY_TEXT,
    risk="external",
)


async def main() -> None:
    tool = JokeTool()
    result = await tool.run_action(GetJoke(category="Programming"), db_session=None)
    print("effective risk:", JokeTool.effective_risk())  # -> "external"
    print(result)


# ── 2. MCP alternative ───────────────────────────────────────────────────────
# To expose tools from an external MCP server instead of writing them in Python,
# install the extra (``pip install "smart-llm[mcp]"``) and connect the client;
# each remote tool is adapted into a native ActionTool, its description sanitized,
# and its definition fingerprint-pinned so a server that swaps tools after
# approval is flagged:
#
#     from smart_llm.mcp.client import MCPToolProvider
#     provider = MCPToolProvider(http_url="https://tools.example.com/mcp")
#     tools = await provider.connect()   # -> list[ActionTool]

if __name__ == "__main__":
    asyncio.run(main())
