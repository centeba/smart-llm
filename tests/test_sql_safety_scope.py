"""SEC C1 — tenant-scope predicate must be a mandatory top-level AND-conjunct.

A substring match on the WHERE clause is not an isolation control: it can be
neutralised with a top-level OR, a parens-hidden filter, or a negation. These
tests pin the hardened behaviour of ``validate_scoped_sql`` /
``_has_scope_predicate``.
"""

import uuid

import pytest

from smart_llm.sql_safety import SqlSafetyError, validate_scoped_sql

MINE = uuid.UUID("11111111-1111-1111-1111-111111111111")
OTHER = "22222222-2222-2222-2222-222222222222"


def _ok(sql: str) -> bool:
    try:
        validate_scoped_sql(sql, MINE)
        return True
    except SqlSafetyError:
        return False


# ── Legitimate scoped SELECTs pass ───────────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        f"SELECT * FROM invoices WHERE company_id = '{MINE}'",
        f"SELECT id FROM invoices WHERE company_id = '{MINE}' AND status = 'open'",
        f"SELECT * FROM invoices WHERE company_id = '{MINE}' AND (status='a' OR status='b')",
        f"SELECT * FROM invoices WHERE status='a' AND company_id = '{MINE}'",
    ],
)
def test_legitimate_scoped_queries_pass(sql):
    assert _ok(sql) is True


# ── Bypass attempts are rejected ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        # top-level OR widens the result to every tenant (the reported exploit)
        f"SELECT * FROM invoices WHERE company_id = '{MINE}' OR 1=1",
        f"SELECT * FROM invoices WHERE 1=1 OR company_id = '{MINE}'",
        # the binding filter hidden inside a parenthesised OR
        f"SELECT * FROM invoices WHERE status='a' AND (company_id = '{MINE}' OR 1=1)",
        # negated tenant filter
        f"SELECT * FROM invoices WHERE NOT company_id = '{MINE}'",
        # sole predicate parenthesised (fails safe — not a top-level conjunct)
        f"SELECT * FROM invoices WHERE (company_id = '{MINE}')",
        # a different tenant's id
        f"SELECT * FROM invoices WHERE company_id = '{OTHER}'",
        # no scope at all
        "SELECT * FROM invoices WHERE 1=1",
    ],
)
def test_scope_bypasses_are_rejected(sql):
    assert _ok(sql) is False


# ── Structural checks still hold (defence in depth) ──────────────────────────


@pytest.mark.parametrize(
    "sql",
    [
        f"SELECT * FROM a JOIN b ON a.id=b.id WHERE company_id = '{MINE}'",
        f"SELECT * FROM invoices WHERE company_id = '{MINE}' UNION SELECT * FROM secrets",
        f"SELECT * FROM invoices WHERE company_id = '{MINE}' AND id IN (SELECT id FROM other)",
        f"DELETE FROM invoices WHERE company_id = '{MINE}'",
    ],
)
def test_structural_violations_still_rejected(sql):
    assert _ok(sql) is False


# ── The no-tenant MCP path keeps structural-only validation ──────────────────


def test_no_company_path_skips_scope_but_keeps_structure():
    # require_scope=False (company_id is None) → structural checks only.
    validate_scoped_sql("SELECT * FROM invoices", None, require_scope=False)
    with pytest.raises(SqlSafetyError):
        validate_scoped_sql(
            "SELECT * FROM a JOIN b ON a.id=b.id", None, require_scope=False
        )
