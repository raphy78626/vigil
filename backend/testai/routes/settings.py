"""Settings API: /api/settings/*, /api/heal/*."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from testai import state

router = APIRouter()


class LLMUpdateRequest(BaseModel):
    provider: str
    api_key: str = ""
    model: str = ""


@router.get("/api/settings/llm")
async def get_llm_settings():
    """Return current LLM provider config + available providers."""
    from testai.llm.provider import PROVIDERS

    return {
        "current": state.llm.get_status(),
        "providers": PROVIDERS,
    }


@router.post("/api/settings/llm")
async def update_llm_settings(req: LLMUpdateRequest):
    """Update the active LLM provider."""
    result = state.llm.update_config(req.provider, req.api_key, req.model)
    return result


@router.post("/api/settings/llm/test")
async def test_llm_connection():
    """Verify current LLM provider is working."""
    return state.llm.test_connection()


@router.get("/api/heal/status")
async def heal_status():
    """Check if auto-healing is available (unified provider or Ollama)."""
    status = state.llm.get_status()
    ollama_ok = state.ollama_healer.available()
    return {
        "available": status["has_key"] or ollama_ok,
        "provider": status["provider_name"],
        "model": status["model"] if status["has_key"] else (state.ollama_healer.model or "none"),
        "has_vision": status["has_vision"],
    }
