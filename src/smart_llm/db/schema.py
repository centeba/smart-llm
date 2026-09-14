"""Optional batteries-included schema: one declarative ``Base`` carrying every
smart-llm table, plus ``create_all`` — so usage/budgets and the agent/skill/key
tables work out of the box.

Import this ONLY if you want smart-llm to own the schema (the standalone default).
A host that manages its own ``Base`` + migrations should instead call
``make_ai_models(host_base)`` / ``make_usage_model(host_base)`` with its own Base
and NOT import this module — importing it registers the tables on smart-llm's own
Base, which is exactly what the standalone path wants but would double-register if
mixed with a host Base.

    from sqlalchemy import create_engine
    from smart_llm.db.schema import create_all

    create_all(create_engine("postgresql+psycopg://user:pw@host/db"))

Or manage it with the bundled Alembic baseline (see ``alembic/`` + ``alembic.ini``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from smart_llm.db.models import make_ai_models
from smart_llm.models import Base
from smart_llm.usage import make_usage_model

if TYPE_CHECKING:
    from sqlalchemy import MetaData
    from sqlalchemy.engine import Engine

# Register the factory-built models onto smart-llm's own declarative Base so a
# single MetaData carries every table: ``llm_api_keys`` (already on Base) + the
# agent/skill tables + the ``ai_usage_events`` ledger that powers usage/budgets.
ai_models: dict[str, type] = make_ai_models(Base)
AIUsageEvent: type = make_usage_model(Base)

#: The unified metadata Alembic (``alembic/env.py``) targets.
metadata: MetaData = Base.metadata


def create_all(engine: Engine) -> None:
    """Create every smart-llm table on *engine* (idempotent)."""
    metadata.create_all(engine)


def drop_all(engine: Engine) -> None:
    """Drop every smart-llm table on *engine*."""
    metadata.drop_all(engine)


__all__ = ["AIUsageEvent", "ai_models", "create_all", "drop_all", "metadata"]
