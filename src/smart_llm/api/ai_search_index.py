"""Phase M — Elasticsearch indexing for AI Admin (Tech-debt #2).

Single index ``ai_admin_v1`` with one document per
``(entity_type, entity_id)`` tuple. Supports cross-tenant search
for ``system_admin``/``platform_admin`` and per-tenant filtering
otherwise.

Why a thin httpx wrapper and not the official ``elasticsearch``
client: the existing observability service already uses httpx
against the same ``SENTINEL_ES_HOST``; introducing the official
client just for this module would double the dep surface for no
real benefit at this dataset size.

Operational contract:
- ``ensure_index`` is idempotent and safe to call at startup.
- ``index_doc`` / ``delete_doc`` are fire-and-forget at the call
  site — errors log and swallow so the user-facing CRUD never
  fails because ES is unavailable. The next reindex run rebuilds
  the missing rows.
- ``search`` returns an empty list when ES is unreachable so the
  UI gracefully falls back to its in-memory filter.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

INDEX_NAME = "ai_admin_v1"
DEFAULT_TIMEOUT = 5.0


def _es_host() -> str:
    """Resolved at call time (not import) so tests can override via
    ``monkeypatch.setenv``."""
    return os.environ.get("SENTINEL_ES_HOST", "http://elasticsearch:9200").rstrip("/")


# ── Mappings ────────────────────────────────────────────────────────────────


_INDEX_MAPPING: dict[str, Any] = {
    "settings": {
        "analysis": {
            "analyzer": {
                "edge_ngram_analyzer": {
                    "type": "custom",
                    "tokenizer": "standard",
                    "filter": ["lowercase", "edge_ngram_filter"],
                },
            },
            "filter": {
                "edge_ngram_filter": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                },
            },
        },
    },
    "mappings": {
        "properties": {
            "type": {"type": "keyword"},
            "id": {"type": "keyword"},
            "company_id": {"type": "keyword"},
            # Searchable + prefix.
            "name": {
                "type": "text",
                "fields": {
                    "raw": {"type": "keyword"},
                    "prefix": {
                        "type": "text",
                        "analyzer": "edge_ngram_analyzer",
                        "search_analyzer": "standard",
                    },
                },
            },
            "label": {"type": "text"},
            "description": {"type": "text"},
            "kind": {"type": "keyword"},
            "modality": {"type": "keyword"},
            # For python_tool / action_node entities — names + descriptions
            # of their args. Lets the user find ``postgres_run_query`` by
            # typing "sql".
            "schema_keys": {"type": "text"},
            "schema_descriptions": {"type": "text"},
        },
    },
}


# ── Index lifecycle ─────────────────────────────────────────────────────────


async def ensure_index() -> bool:
    """Create the index with mappings if it doesn't exist.

    Returns ``True`` on success (or already-exists), ``False`` if ES
    is unreachable. Safe to call at every app startup.
    """
    host = _es_host()
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            check = await client.head(f"{host}/{INDEX_NAME}")
            if check.status_code == 200:
                return True
            if check.status_code != 404:
                logger.warning(
                    "ai_search_index: HEAD %s returned %s — skipping create",
                    INDEX_NAME,
                    check.status_code,
                )
                return False
            create = await client.put(f"{host}/{INDEX_NAME}", json=_INDEX_MAPPING)
            if create.is_error:
                logger.warning(
                    "ai_search_index: failed to create %s: %s %s",
                    INDEX_NAME,
                    create.status_code,
                    create.text,
                )
                return False
            return True
    except (httpx.HTTPError, OSError) as e:
        logger.warning("ai_search_index: ES unreachable (%s) — index disabled", e)
        return False


# ── Document upsert / delete ────────────────────────────────────────────────


def _doc_id(entity_type: str, entity_id: str) -> str:
    return f"{entity_type}:{entity_id}"


async def index_doc(entity_type: str, entity_id: str, source: dict[str, Any]) -> None:
    """Upsert one document. Fire-and-forget — errors log only."""
    host = _es_host()
    doc_id = _doc_id(entity_type, entity_id)
    body = {**source, "type": entity_type, "id": entity_id}
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.put(
                f"{host}/{INDEX_NAME}/_doc/{doc_id}",
                json=body,
            )
            if resp.is_error:
                logger.warning(
                    "ai_search_index: index %s failed: %s %s",
                    doc_id,
                    resp.status_code,
                    resp.text,
                )
    except (httpx.HTTPError, OSError) as e:
        logger.warning("ai_search_index: index %s skipped (%s)", doc_id, e)


async def delete_doc(entity_type: str, entity_id: str) -> None:
    """Delete one document. Fire-and-forget."""
    host = _es_host()
    doc_id = _doc_id(entity_type, entity_id)
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.delete(f"{host}/{INDEX_NAME}/_doc/{doc_id}")
            # 404 is fine — already gone.
            if resp.is_error and resp.status_code != 404:
                logger.warning(
                    "ai_search_index: delete %s failed: %s %s",
                    doc_id,
                    resp.status_code,
                    resp.text,
                )
    except (httpx.HTTPError, OSError) as e:
        logger.warning("ai_search_index: delete %s skipped (%s)", doc_id, e)


async def bulk_index(docs: Iterable[tuple[str, str, dict[str, Any]]]) -> int:
    """Bulk upsert. ``docs`` is an iterable of
    ``(entity_type, entity_id, source)`` tuples. Returns the number
    of successfully indexed docs (0 if ES unreachable)."""
    host = _es_host()
    lines: list[str] = []
    import json

    docs_list = list(docs)
    for entity_type, entity_id, source in docs_list:
        doc_id = _doc_id(entity_type, entity_id)
        lines.append(json.dumps({"index": {"_index": INDEX_NAME, "_id": doc_id}}))
        body = {**source, "type": entity_type, "id": entity_id}
        lines.append(json.dumps(body))
    payload = "\n".join(lines) + "\n"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT * 6) as client:
            resp = await client.post(
                f"{host}/_bulk",
                content=payload,
                headers={"Content-Type": "application/x-ndjson"},
            )
            if resp.is_error:
                logger.warning(
                    "ai_search_index: bulk index failed: %s %s",
                    resp.status_code,
                    resp.text,
                )
                return 0
            body_json = resp.json()
            errors = body_json.get("errors", False)
            if errors:
                # Count individual failures but report aggregate.
                items = body_json.get("items", [])
                ok = sum(1 for it in items if not it.get("index", {}).get("error"))
                logger.warning(
                    "ai_search_index: bulk index had partial failures (%d/%d ok)",
                    ok,
                    len(items),
                )
                return ok
            return len(docs_list)
    except (httpx.HTTPError, OSError) as e:
        logger.warning("ai_search_index: bulk skipped (%s)", e)
        return 0


# ── Search ──────────────────────────────────────────────────────────────────


async def search(
    q: str,
    *,
    company_id: str | None = None,
    type_filter: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Multi-match search across name/label/description/schema fields.

    - ``company_id=None`` → cross-tenant (system_admin/platform_admin).
    - ``type_filter`` ∈ {"agent","skill","tool"} narrows by entity type.
    - Falls back to ``[]`` when ES is unreachable so the UI degrades
      gracefully to its in-memory filter.
    """
    host = _es_host()
    if not q.strip():
        return []

    must: list[dict[str, Any]] = [
        {
            "multi_match": {
                "query": q,
                "fields": [
                    "name^3",
                    "name.prefix^2",
                    "label^2",
                    "description",
                    "schema_keys^2",
                    "schema_descriptions",
                ],
                "type": "best_fields",
                "fuzziness": "AUTO",
            },
        },
    ]
    filters: list[dict[str, Any]] = []
    if company_id:
        # Match per-tenant OR global (platform-scope rows have
        # company_id=null and we want admin-of-A to see them too).
        filters.append(
            {
                "bool": {
                    "should": [
                        {"term": {"company_id": company_id}},
                        {"bool": {"must_not": {"exists": {"field": "company_id"}}}},
                    ],
                    "minimum_should_match": 1,
                },
            }
        )
    if type_filter:
        filters.append({"term": {"type": type_filter}})

    body = {
        "size": max(1, min(limit, 100)),
        "query": {
            "bool": {
                "must": must,
                "filter": filters,
            },
        },
        "highlight": {
            "fields": {
                "name": {},
                "label": {},
                "description": {},
            },
        },
    }
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            resp = await client.post(
                f"{host}/{INDEX_NAME}/_search",
                json=body,
            )
            if resp.is_error:
                logger.warning(
                    "ai_search_index: search failed: %s %s",
                    resp.status_code,
                    resp.text,
                )
                return []
            hits = resp.json().get("hits", {}).get("hits", [])
            return [
                {
                    **h.get("_source", {}),
                    "_score": h.get("_score"),
                    "_highlight": h.get("highlight", {}),
                }
                for h in hits
            ]
    except (httpx.HTTPError, OSError) as e:
        logger.warning("ai_search_index: search skipped (%s)", e)
        return []


# ── ORM → doc adapters ──────────────────────────────────────────────────────


def agent_to_doc(agent: Any) -> dict[str, Any]:
    """Build the index document for an ``AIAgentConfig`` ORM row."""
    return {
        "company_id": str(agent.company_id) if agent.company_id else None,
        "name": agent.name,
        "label": getattr(agent, "label", None),
        "description": getattr(agent, "description", None),
        "kind": "agent",
        "modality": None,
        "schema_keys": [],
        "schema_descriptions": [],
    }


def skill_to_doc(skill: Any) -> dict[str, Any]:
    """Build the index document for an ``AISkill`` ORM row."""
    return {
        "company_id": str(skill.company_id) if skill.company_id else None,
        "name": skill.name,
        "label": getattr(skill, "label", None),
        "description": getattr(skill, "description", None),
        "kind": getattr(skill, "kind", "prompt"),
        "modality": getattr(skill, "modality", None),
        "schema_keys": [],
        "schema_descriptions": [],
    }


def tool_to_doc(name: str, meta: Any) -> dict[str, Any]:
    """Build the index document for a registered Python tool.

    ``meta`` is a ``ToolMeta`` from ``smart_llm.registry``. Tools are
    global (no company_id); their ``args_model.model_json_schema()``
    contributes the schema fields so users searching "sql" find
    ``postgres_run_query`` via its schema description.
    """
    schema_keys: list[str] = []
    schema_descriptions: list[str] = []
    args_model = getattr(meta.cls, "args_model", None)
    if args_model is not None:
        try:
            schema = args_model.model_json_schema()
            props = schema.get("properties", {})
            for key, defn in props.items():
                schema_keys.append(key)
                desc = defn.get("description")
                if desc:
                    schema_descriptions.append(desc)
        except Exception:  # noqa: BLE001
            # Schema generation can fail on exotic Pydantic shapes;
            # we still want the tool indexed by name + label.
            pass
    return {
        "company_id": None,  # Tools are global.
        "name": name,
        "label": getattr(meta, "label", None),
        "description": getattr(meta, "description", None),
        "kind": "python_tool",
        "modality": getattr(meta, "modality", None),
        "schema_keys": schema_keys,
        "schema_descriptions": schema_descriptions,
    }
