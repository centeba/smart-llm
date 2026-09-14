"""Database-bound concerns for smart-llm: ORM models + Pydantic schemas
for AI agent configurations, skills, and the join table.

Smart-llm intentionally does **not** own a global declarative ``Base`` for
these tables. Each host app (integration-hub, etc.) passes its own ``Base``
into ``make_ai_models`` so the tables live in the host's metadata and are
managed by the host's Alembic. This keeps smart-llm's database concerns
lib-shaped (factory injection) consistent with the existing factory routers.
"""

from smart_llm.db.models import (
    MODALITIES,
    MODALITY_ANY,
    MODALITY_AUDIO,
    MODALITY_DOCUMENT,
    MODALITY_IMAGE,
    MODALITY_TEXT,
    MODALITY_VIDEO,
    SKILL_KIND_PROMPT,
    SKILL_KIND_PYTHON_TOOL,
    SKILL_KINDS,
    AIAgentConfigCreate,
    AIAgentConfigPublic,
    AIAgentConfigsPublic,
    AIAgentConfigUpdate,
    AIAgentSyncItem,
    AIAgentSyncRequest,
    AIAgentSyncResponse,
    AIAgentSyncResultItem,
    AISkillCreate,
    AISkillPublic,
    AISkillsPublic,
    AISkillSyncItem,
    AISkillSyncRequest,
    AISkillSyncResponse,
    AISkillSyncResultItem,
    AISkillUpdate,
    CompanyLLMApiKeyCreate,
    CompanyLLMApiKeyPublic,
    CompanyLLMApiKeysPublic,
    Message,
    make_ai_models,
)

__all__ = [
    "MODALITIES",
    "MODALITY_ANY",
    "MODALITY_AUDIO",
    "MODALITY_DOCUMENT",
    "MODALITY_IMAGE",
    "MODALITY_TEXT",
    "MODALITY_VIDEO",
    "SKILL_KINDS",
    "SKILL_KIND_PROMPT",
    "SKILL_KIND_PYTHON_TOOL",
    "AIAgentConfigCreate",
    "AIAgentConfigPublic",
    "AIAgentConfigUpdate",
    "AIAgentConfigsPublic",
    "AIAgentSyncItem",
    "AIAgentSyncRequest",
    "AIAgentSyncResponse",
    "AIAgentSyncResultItem",
    "AISkillCreate",
    "AISkillPublic",
    "AISkillSyncItem",
    "AISkillSyncRequest",
    "AISkillSyncResponse",
    "AISkillSyncResultItem",
    "AISkillUpdate",
    "AISkillsPublic",
    "CompanyLLMApiKeyCreate",
    "CompanyLLMApiKeyPublic",
    "CompanyLLMApiKeysPublic",
    "Message",
    "make_ai_models",
]
