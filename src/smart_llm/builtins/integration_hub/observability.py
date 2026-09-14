"""Observability adapters — datadog_query_logs / elasticsearch_search."""

from __future__ import annotations

from typing import Any

from integration_hub_backend.mcp.tools import (
    DatadogQueryLogsArgs,
    ElasticsearchSearchArgs,
)
from pydantic import BaseModel

from smart_llm.base import ActionTool
from smart_llm.db.models import MODALITY_TEXT
from smart_llm.registry import register_tool

from ._dispatch import dispatch


class DatadogQueryLogsSkill(ActionTool):
    args_model = DatadogQueryLogsArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        result = await dispatch("datadog_query_logs", args, db_session=db_session)
        return {"logs": result}


class ElasticsearchSearchSkill(ActionTool):
    args_model = ElasticsearchSearchArgs

    async def run_action(self, args: BaseModel, *, db_session: Any) -> dict[str, Any]:
        result = await dispatch("elasticsearch_search", args, db_session=db_session)
        return {"hits": result}


register_tool(
    "datadog_query_logs",
    DatadogQueryLogsSkill,
    label="Datadog: Query Logs",
    description="Query logs from Datadog.",
    modality=MODALITY_TEXT,
    risk="read",
)
register_tool(
    "elasticsearch_search",
    ElasticsearchSearchSkill,
    label="Elasticsearch: Search",
    description="Search an Elasticsearch index.",
    modality=MODALITY_TEXT,
    risk="read",
)
