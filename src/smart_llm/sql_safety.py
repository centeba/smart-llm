"""Shared SQL AST safety validator.

Used by:
- :mod:`integration_hub_backend.api.services.ai_search_service` (entity-specific:
  restricts FROM to one known table, validates scope predicate).
- :class:`smart_llm.builtins.integration_hub.postgres.PostgresRunQuerySkill`
  (generic: any SELECT, but must include ``scope_column = '<company_id>'``
  in the WHERE clause).

The validator is intentionally conservative — it rejects anything it cannot
confidently parse rather than allowing uncertain cases through.
"""

import re
import uuid
from collections.abc import Iterator
from typing import Any

import sqlparse
from sqlparse.sql import Identifier, IdentifierList, Parenthesis, Where
from sqlparse.tokens import DML, Keyword, Whitespace


class SqlSafetyError(ValueError):
    """Raised when SQL fails the AST safety check.

    Safe to return to the caller — the message never includes raw user data.
    """


def validate_scoped_sql(
    sql: str,
    company_id: uuid.UUID | None,
    *,
    allowed_table: str | None = None,
    allowed_schema: str | None = None,
    scope_column: str = "company_id",
    require_scope: bool = True,
) -> None:
    """Validate that *sql* is a safe, tenant-scoped SELECT statement.

    Args:
        sql: The SQL string to validate.
        company_id: Expected tenant UUID that must appear literally in the
            WHERE clause as ``scope_column = '<company_id>'``.
        allowed_table: If given, FROM may only reference this table (with or
            without the schema prefix). ``None`` permits any table.
        allowed_schema: Schema qualifying *allowed_table* (e.g. ``"public"``).
            Ignored when *allowed_table* is ``None``.
        scope_column: Column name that must equal *company_id* in the WHERE
            clause. Defaults to ``"company_id"``.

    Raises:
        SqlSafetyError: on any safety violation.
    """
    statements = [s for s in sqlparse.parse(sql) if str(s).strip()]
    if len(statements) != 1:
        raise SqlSafetyError(
            f"Expected exactly one SQL statement, got {len(statements)}"
        )
    stmt: Any = statements[0]

    # Must begin with SELECT.
    first = stmt.token_first(skip_ws=True, skip_cm=True)
    if first is None or first.ttype is not DML or first.value.upper() != "SELECT":
        raise SqlSafetyError("Only SELECT statements are allowed")

    # No CTEs / UNION / parenthesised subqueries.
    for tok in stmt.flatten():
        if tok.ttype is Keyword and tok.value.upper() in {
            "WITH",
            "UNION",
            "INTERSECT",
            "EXCEPT",
        }:
            raise SqlSafetyError(f"Disallowed keyword in SQL: {tok.value.upper()}")
    for tok in _walk(stmt):
        if isinstance(tok, Parenthesis) and "SELECT" in tok.value.upper():
            raise SqlSafetyError("Subqueries are not allowed")

    # Optional FROM-table restriction.
    if allowed_table is not None:
        from_tables = _extract_from_tables(stmt)
        if allowed_schema:
            allowed: set[str] = {
                allowed_table.lower(),
                f"{allowed_schema}.{allowed_table}".lower(),
            }
        else:
            allowed = {allowed_table.lower()}
        bad = [t for t in from_tables if t.lower() not in allowed]
        if bad:
            qualified = (
                f"{allowed_schema}.{allowed_table}" if allowed_schema else allowed_table
            )
            raise SqlSafetyError(
                f"FROM references disallowed table(s): {bad}. "
                f"Only {qualified} is allowed."
            )
        if not from_tables:
            raise SqlSafetyError("FROM clause is missing or unrecognised")

    # JOIN ban (defence in depth).
    for tok in stmt.flatten():
        if tok.ttype is Keyword and "JOIN" in tok.value.upper():
            raise SqlSafetyError("JOINs are not allowed")

    # Tenant scope predicate must be present (M2 — skippable for the no-tenant
    # MCP path, which keeps all the structural checks above but has no company
    # to scope to).
    if require_scope:
        if company_id is None:
            raise SqlSafetyError("company_id is required for tenant-scoped validation")
        if not _has_scope_predicate(stmt, scope_column, str(company_id)):
            raise SqlSafetyError(
                f"Missing required tenant filter "
                f"`{scope_column} = '{company_id}'` in WHERE clause"
            )


# ── private helpers ──────────────────────────────────────────────────────────


def _walk(token: Any) -> Iterator[Any]:
    """Recursively yield every grouped token under *token*."""
    yield token
    for child in getattr(token, "tokens", []) or []:
        yield from _walk(child)


def _extract_from_tables(stmt: Any) -> list[str]:
    """Return the table names referenced in FROM (JOINs are banned separately)."""
    out: list[str] = []
    seen_from = False
    for tok in stmt.tokens:
        if tok.ttype is Keyword and tok.value.upper() == "FROM":
            seen_from = True
            continue
        if not seen_from:
            continue
        if tok.ttype is Whitespace:
            continue
        if isinstance(tok, Where):
            break
        if tok.ttype is Keyword and tok.value.upper() in {
            "WHERE",
            "GROUP",
            "ORDER",
            "LIMIT",
            "HAVING",
        }:
            break
        if isinstance(tok, IdentifierList):
            tok_any: Any = tok
            out.extend(_identifier_name(i) for i in tok_any.get_identifiers())
            seen_from = False
        elif isinstance(tok, Identifier):
            out.append(_identifier_name(tok))
            seen_from = False
        elif tok.ttype is None and hasattr(tok, "tokens"):
            # Unwrapped grouping
            out.append(tok.value.strip())
            seen_from = False
    return [t for t in out if t]


def _identifier_name(ident: Any) -> str:
    """Return ``schema.table`` or ``table`` for an Identifier token."""
    real = getattr(ident, "get_real_name", lambda: None)()
    parent = getattr(ident, "get_parent_name", lambda: None)()
    if parent and real:
        return f"{parent}.{real}"
    return real or str(ident).strip()


_PREDICATE_RE_TEMPLATE = r"\b{col}\s*=\s*'{val}'"


def _has_scope_predicate(stmt: Any, scope_column: str, company_id: str) -> bool:
    """Return True iff ``scope_column = '<company_id>'`` is a **mandatory
    top-level AND-conjunct** of the WHERE clause.

    A substring match is NOT sufficient as an isolation control: an attacker
    (or a prompt-injected model) can neutralise a present-but-non-binding
    filter with ``WHERE company_id = '<mine>' OR 1=1`` (top-level OR widens
    the result to every tenant) or bury it inside a parenthesised OR
    (``... AND (company_id = '<mine>' OR x)``) or negate it
    (``WHERE NOT company_id = '<mine>'``). So we:

    1. Consider only **top-level** WHERE tokens — parenthesised subexpressions
       are excluded from the predicate match, so the tenant filter must sit at
       the top level where it binds the whole result (it can't be hidden
       inside an OR group).
    2. **Reject any top-level ``OR`` / ``NOT``** — either can widen or invert
       the tenant scope. (A parenthesised OR, e.g. ``status IN (...)`` logic,
       is fine; only top-level boolean widening is refused.)
    3. Require the literal equality to appear among those top-level tokens.

    This is stricter than before by design — an unparseable-but-clever query
    is refused rather than allowed. Legitimate scoped SELECTs
    (``WHERE company_id = '<mine>' AND foo = 'bar' AND (a OR b)``) still pass.
    """
    where: Where | None = None
    for tok in stmt.tokens:
        if isinstance(tok, Where):
            where = tok
            break
    if where is None:
        return False

    # Collect only top-level (non-parenthesised) token text; refuse any
    # top-level OR / NOT that could widen or invert the tenant filter.
    top_level_parts: list[str] = []
    for tok in where.tokens:
        if isinstance(tok, Parenthesis):
            continue  # scoped locally — never contributes the binding filter
        if tok.ttype is Keyword:
            kw = tok.value.upper()
            if kw == "OR" or "NOT" in kw:
                return False
        top_level_parts.append(tok.value)

    top_level_text = "".join(top_level_parts)
    pattern = _PREDICATE_RE_TEMPLATE.format(
        col=re.escape(scope_column),
        val=re.escape(company_id),
    )
    return bool(re.search(pattern, top_level_text, re.IGNORECASE))
