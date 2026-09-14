"""SQLAlchemy models for smart-llm database-backed features.

Requires the ``db`` extras: ``pip install smart-llm[db]``
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, Column, DateTime, Index, String, Text, TypeDecorator
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import CHAR


class PortableUUID(TypeDecorator[uuid.UUID]):
    """Platform-independent UUID type.

    Uses PostgreSQL's native UUID when available, otherwise stores as CHAR(36).
    """

    impl = CHAR(36)
    cache_ok = True

    def process_bind_param(
        self, value: uuid.UUID | str | None, dialect: Dialect
    ) -> str | None:
        if value is not None:
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(uuid.UUID(value))
        return value

    def process_result_value(
        self, value: str | None, dialect: Dialect
    ) -> uuid.UUID | None:
        if value is not None:
            return uuid.UUID(value)
        return value


class Base(DeclarativeBase):
    pass


class LLMApiKey(Base):
    """Encrypted API key storage for LLM providers.

    Supports multi-tenant isolation via the optional ``scope_id`` column
    (e.g. company_id in a SaaS application).
    """

    __tablename__ = "llm_api_keys"
    __table_args__ = (
        # At most one ACTIVE key per (scope, provider) — a client bug or
        # retry storm hammering the create endpoint can only ever produce
        # one live row; everything else fails the constraint instead of
        # silently accumulating. This model is the single source of truth for
        # the table's DDL: integration-hub's Alembic migration 027_llm_api_keys
        # creates it straight from this ``__table__`` (Gate 8), and
        # ``key_store.create_tables()`` remains for standalone/test use.
        Index(
            "ix_llm_api_keys_active_scope_provider",
            "scope_id",
            "provider",
            unique=True,
            postgresql_where=Column("is_active").is_(True),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PortableUUID(),
        primary_key=True,
        default=uuid.uuid4,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    encrypted_key: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(
        PortableUUID(), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
