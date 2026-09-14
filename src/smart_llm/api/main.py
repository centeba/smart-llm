import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, field_validator

from smart_llm import Agent, AgentManager, EnvKeyStore, KeyManager
from smart_llm.api.middleware import RateLimitMiddleware, require_api_key
from smart_llm.security import (
    ModerationError,
    ModerationUnavailableError,
    OffTopicError,
    PromptInjectionError,
    SchemaValidationError,
)

# Load environment variables, e.g. from .env file
load_dotenv()

logger = logging.getLogger(__name__)

manager = AgentManager()
km = KeyManager(key_store=EnvKeyStore())
_has_agent = False

MAX_INPUT_LENGTH = int(os.getenv("SMART_LLM_MAX_INPUT_LENGTH", "50000"))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _has_agent

    # Load keys from environment into KeyManager
    await km.load_from_store()

    # Create agents from available keys
    providers = [
        ("gemini", "gemini_primary"),
        ("openai", "openai_fallback"),
        ("anthropic", "anthropic_fallback"),
    ]
    for provider_type, agent_name in providers:
        key = km.get_key(provider_type)
        if key:
            agent = Agent(
                name=agent_name,
                provider_type=provider_type,
                system_prompt="You are a helpful and intelligent AI assistant.",
                api_key=key,
            )
            manager.register_agent(agent)
            _has_agent = True

    yield


app = FastAPI(
    title="Smart-LLM API",
    description="Agentic wrapper endpoint for local and Railway deployment",
    lifespan=lifespan,
)

# Register rate limiting middleware
app.add_middleware(RateLimitMiddleware)


class AnalyzeRequest(BaseModel):
    input_text: str
    context: str | None = None

    @field_validator("input_text")
    @classmethod
    def validate_input_length(cls, v: str) -> str:
        if len(v) > MAX_INPUT_LENGTH:
            raise ValueError(
                f"input_text exceeds maximum length of {MAX_INPUT_LENGTH} characters"
            )
        if not v.strip():
            raise ValueError("input_text must not be empty or whitespace only")
        return v


@app.get("/health")
def health_check() -> dict[str, Any]:
    """
    Standard health check endpoint for monitoring setups like Railway.
    No authentication required.
    """
    return {
        "status": "ok",
        "ready": _has_agent,
        "registered_agents": manager.failover_sequence,
    }


@app.post("/analyze")
async def analyze_text(
    request: AnalyzeRequest,
    api_key: str = Depends(require_api_key),
) -> dict[str, Any]:
    """
    Accepts text and optional context, returning the LLM processed result.
    Applies the stateful failure mitigation pattern transparently.
    Requires a valid API key when SMART_LLM_API_KEYS is configured.
    """
    if not _has_agent:
        raise HTTPException(
            status_code=503,
            detail="Service unavailable: no AI agents configured",
        )

    try:
        response = await manager.analyze(request.input_text, request.context)
        return {
            "data": response.data,
            "metadata": response.metadata,
        }
    except (PromptInjectionError, ModerationError, OffTopicError):
        # Content-safety rejection — generic message, no detail leak. The
        # specific category/reason is logged server-side by the guard.
        raise HTTPException(
            status_code=400,
            detail="Request rejected: potentially harmful or disallowed content detected",
        )
    except ModerationUnavailableError:
        # Fail-closed: moderation could not run, so we refuse rather than
        # process unscreened content.
        raise HTTPException(
            status_code=503,
            detail="Content safety service unavailable; request not processed",
        )
    except SchemaValidationError:
        raise HTTPException(
            status_code=502,
            detail="Response validation failed",
        )
    except Exception:
        # Log the full exception internally for debugging
        logger.exception("Unexpected error during analysis")
        # Return a generic message — never expose internal details
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        )
