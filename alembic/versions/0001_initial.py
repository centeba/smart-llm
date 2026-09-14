"""initial smart-llm schema (agents, skills, grants, runs, llm keys, usage ledger)

Creates every table from the unified metadata in ``smart_llm.db.schema``. This is
a "create everything" baseline; subsequent revisions can use normal autogenerate.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-14
"""

from alembic import op
from smart_llm.db.schema import metadata

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind())


def downgrade() -> None:
    metadata.drop_all(op.get_bind())
