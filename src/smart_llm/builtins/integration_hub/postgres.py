"""Postgres adapters — list_tables / describe_table / run_query.

The actual SQL + safety rails live in
``integration_hub_backend.api.services.postgres_service.PostgresService``;
the SELECT-only guard and result-set ``LIMIT 50`` cap are intentionally
kept there so the MCP transport and the agent runtime share the same
guardrails.

For ``postgres_run_query`` specifically, an additional AST-based tenant
isolation check runs here (before dispatch) whenever ``company_id`` is
present in the args. The ``company_id`` is injected by the ``/ai-tools/run``
route from the caller's JWT. MCP server calls do not set ``company_id`` and
therefore skip this extra check (the keyword guard in PostgresService is
their defence).
"""

from __future__ import annotations

from typing import Any, cast

from integration_hub_backend.mcp.tools import (
    PostgresDescribeTableArgs,
    PostgresListTablesArgs,
    PostgresRunQueryArgs,
)
from pydantic import BaseModel

from smart_llm.base import ActionTool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool
from smart_llm.sql_safety import SqlSafetyError, validate_scoped_sql

from ._dispatch import dispatch


class PostgresListTablesSkill(ActionTool):
    args_model = PostgresListTablesArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        rows = await dispatch("postgres_list_tables", args, db_session=db_session)
        return {"tables": rows}


class PostgresDescribeTableSkill(ActionTool):
    args_model = PostgresDescribeTableArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        rows = await dispatch("postgres_describe_table", args, db_session=db_session)
        return {"columns": rows}


class PostgresRunQuerySkill(ActionTool):
    args_model = PostgresRunQueryArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        query_args = cast(PostgresRunQueryArgs, args)
        # Tenant isolation (M2). With a company_id (the /ai-tools/run JWT path)
        # we require the tenant-scope predicate. The MCP / no-company_id path has
        # no tenant to scope to, but must STILL pass the structural AST checks
        # (single SELECT; no CTE/UNION/subquery/JOIN) — previously this block was
        # skipped entirely, leaving only PostgresService's keyword guard.
        company_id = getattr(args, "company_id", None)
        try:
            validate_scoped_sql(
                query_args.sql_query, company_id, require_scope=company_id is not None
            )
        except SqlSafetyError as exc:
            return {"error": f"SQL safety check failed: {exc}"}
        rows = await dispatch("postgres_run_query", args, db_session=db_session)
        return {"rows": rows}


register_tool(
    "postgres_list_tables",
    PostgresListTablesSkill,
    label="Postgres: List Tables",
    description="List all tables in the Postgres public schema.",
    modality=MODALITY_TEXT,
    risk="read",
)
register_tool(
    "postgres_describe_table",
    PostgresDescribeTableSkill,
    label="Postgres: Describe Table",
    description="Retrieve the column names and data types of a specific table.",
    modality=MODALITY_TEXT,
    risk="read",
)
register_tool(
    "postgres_run_query",
    PostgresRunQuerySkill,
    label="Postgres: Run Query",
    description="Run a raw SQL query against Postgres. SELECT only; auto-LIMIT 50.",
    modality=MODALITY_TEXT,
    risk="read",
)
