"""Unified LLM provider wrapping LiteLLM.

Supports: Ollama (local/free), OpenAI, Claude, Gemini, OpenRouter, NVIDIA NIM.
Config stored at ~/.vigil/llm.json.
Fallback chain: configured provider -> Ollama -> returns None.
"""

from __future__ import annotations

import json
import logging
import os
import base64
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, List

from litellm import completion

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".vigil"
CONFIG_PATH = CONFIG_DIR / "llm.json"

PROVIDERS = {
    "ollama": {
        "name": "Ollama",
        "description": "Local, free — no API key needed",
        "needs_key": False,
        "env_var": None,
        "default_model": "ollama/qwen2.5-coder:7b",
        "models": [
            {"id": "ollama/qwen2.5-coder:7b", "name": "Qwen 2.5 Coder 7B", "vision": False},
            {"id": "ollama/qwen2.5:7b", "name": "Qwen 2.5 7B", "vision": False},
            {"id": "ollama/llama3:8b", "name": "Llama 3 8B", "vision": False},
            {"id": "ollama/codellama:7b", "name": "Code Llama 7B", "vision": False},
        ],
        "vision": False,
        "tier": "free",
    },
    "openai": {
        "name": "OpenAI",
        "description": "GPT-4o — fast, accurate, vision support",
        "needs_key": True,
        "env_var": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "models": [
            {"id": "gpt-4o", "name": "GPT-4o", "vision": True},
            {"id": "gpt-4o-mini", "name": "GPT-4o Mini (cheap)", "vision": True},
            {"id": "o1-mini", "name": "o1 Mini (reasoning)", "vision": False},
        ],
        "vision": True,
        "tier": "premium",
    },
    "anthropic": {
        "name": "Claude",
        "description": "Sonnet / Haiku — great at code, vision support",
        "needs_key": True,
        "env_var": "ANTHROPIC_API_KEY",
        "default_model": "anthropic/claude-sonnet-4-20250514",
        "models": [
            {"id": "anthropic/claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "vision": True},
            {"id": "anthropic/claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku (fast)", "vision": True},
        ],
        "vision": True,
        "tier": "premium",
    },
    "gemini": {
        "name": "Gemini",
        "description": "Flash (fast + cheap) / Pro — Google AI",
        "needs_key": True,
        "env_var": "GEMINI_API_KEY",
        "default_model": "gemini/gemini-2.0-flash",
        "models": [
            {"id": "gemini/gemini-2.0-flash", "name": "Gemini 2.0 Flash (fast)", "vision": True},
            {"id": "gemini/gemini-1.5-pro", "name": "Gemini 1.5 Pro", "vision": True},
        ],
        "vision": True,
        "tier": "cheap",
    },
    "openrouter": {
        "name": "OpenRouter",
        "description": "200+ models with one key — includes free tiers",
        "needs_key": True,
        "env_var": "OPENROUTER_API_KEY",
        "default_model": "openrouter/google/gemini-2.0-flash-exp:free",
        "models": [
            {"id": "openrouter/google/gemini-2.0-flash-exp:free", "name": "Gemini Flash (free)", "vision": True},
            {"id": "openrouter/anthropic/claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "vision": True},
            {"id": "openrouter/openai/gpt-4o-mini", "name": "GPT-4o Mini", "vision": True},
            {"id": "openrouter/meta-llama/llama-3-70b-instruct", "name": "Llama 3 70B", "vision": False},
        ],
        "vision": True,
        "tier": "varies",
    },
    "nvidia_nim": {
        "name": "NVIDIA NIM",
        "description": "NVIDIA-hosted models — Llama, Nemotron, Mistral",
        "needs_key": True,
        "env_var": "NVIDIA_NIM_API_KEY",
        "default_model": "nvidia_nim/meta/llama-3.1-8b-instruct",
        "models": [
            {"id": "nvidia_nim/meta/llama-3.1-8b-instruct", "name": "Llama 3.1 8B Instruct", "vision": False},
            {"id": "nvidia_nim/meta/llama-3.1-70b-instruct", "name": "Llama 3.1 70B Instruct", "vision": False},
            {"id": "nvidia_nim/meta/llama-3.1-405b-instruct", "name": "Llama 3.1 405B Instruct", "vision": False},
            {"id": "nvidia_nim/nvidia/nemotron-4-340b-instruct", "name": "Nemotron 4 340B", "vision": False},
            {"id": "nvidia_nim/mistralai/mistral-large-2-instruct", "name": "Mistral Large 2", "vision": False},
        ],
        "vision": False,
        "tier": "free-trial",
    },
}


@dataclass
class LLMConfig:
    provider: str = "ollama"
    api_key: str = ""
    model: str = "ollama/qwen2.5-coder:7b"
    fallback_provider: str = "ollama"
    fallback_model: str = "ollama/qwen2.5-coder:7b"


def _load_config() -> LLMConfig:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            return LLMConfig(**{k: v for k, v in data.items() if k in LLMConfig.__dataclass_fields__})
        except Exception:
            pass
    return LLMConfig()


def _save_config(cfg: LLMConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(asdict(cfg), indent=2))


def _set_env_key(provider: str, api_key: str) -> None:
    """Set the API key as an environment variable for LiteLLM."""
    info = PROVIDERS.get(provider, {})
    env_var = info.get("env_var")
    if env_var and api_key:
        os.environ[env_var] = api_key


def _model_supports_vision(model: str) -> bool:
    for prov in PROVIDERS.values():
        for m in prov["models"]:
            if m["id"] == model:
                return m.get("vision", False)
    return "gpt-4o" in model or "claude" in model or "gemini" in model


class LLMProvider:
    """Unified LLM interface for all TestAI-Pro features."""

    def __init__(self):
        self.config = _load_config()
        self._apply_key()

    def _apply_key(self):
        if self.config.api_key:
            _set_env_key(self.config.provider, self.config.api_key)

    def reload(self):
        self.config = _load_config()
        self._apply_key()

    @property
    def model(self) -> str:
        return self.config.model

    @property
    def provider_name(self) -> str:
        info = PROVIDERS.get(self.config.provider, {})
        return info.get("name", self.config.provider)

    @property
    def has_vision(self) -> bool:
        return _model_supports_vision(self.config.model)

    def get_status(self) -> dict:
        """Return provider status for the dashboard."""
        cfg = self.config
        info = PROVIDERS.get(cfg.provider, {})
        has_key = not info.get("needs_key") or bool(cfg.api_key)
        return {
            "provider": cfg.provider,
            "provider_name": info.get("name", cfg.provider),
            "model": cfg.model,
            "has_key": has_key,
            "has_vision": self.has_vision,
            "tier": info.get("tier", "unknown"),
            "fallback_model": cfg.fallback_model,
        }

    def update_config(self, provider: str, api_key: str = "", model: str = "") -> dict:
        """Update provider settings and persist."""
        info = PROVIDERS.get(provider)
        if not info:
            return {"ok": False, "error": f"Unknown provider: {provider}"}

        self.config.provider = provider
        if api_key:
            self.config.api_key = api_key
        if model:
            self.config.model = model
        else:
            self.config.model = info["default_model"]

        self._apply_key()
        _save_config(self.config)
        return {"ok": True, **self.get_status()}

    def ask(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: int = 2048,
        images: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Send a prompt to the configured LLM. Returns response text or None."""

        def _build_messages(with_images: bool = True) -> list:
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            if with_images and images and self.has_vision:
                content = [{"type": "text", "text": prompt}]
                for img_b64 in images:
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{img_b64}"},
                    })
                msgs.append({"role": "user", "content": content})
            else:
                msgs.append({"role": "user", "content": prompt})
            return msgs

        # Try primary model with images
        try:
            resp = completion(
                model=self.config.model,
                messages=_build_messages(with_images=True),
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("Primary LLM (%s) failed: %s", self.config.model, e)

        # Retry primary without images (image conversion can fail)
        if images:
            try:
                resp = completion(
                    model=self.config.model,
                    messages=_build_messages(with_images=False),
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                logger.warning("Primary LLM text-only (%s) failed: %s", self.config.model, e)

        # Try fallback (always text-only for reliability)
        if self.config.fallback_model and self.config.fallback_model != self.config.model:
            try:
                resp = completion(
                    model=self.config.fallback_model,
                    messages=_build_messages(with_images=False),
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                logger.warning("Fallback LLM (%s) failed: %s", self.config.fallback_model, e)

        return None

    def test_connection(self) -> dict:
        """Verify the configured provider works."""
        try:
            result = self.ask("Reply with exactly: OK", max_tokens=10)
            if result:
                return {"ok": True, "response": result[:50], "model": self.config.model}
            return {"ok": False, "error": "No response from model"}
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}


_instance: Optional[LLMProvider] = None


def get_provider() -> LLMProvider:
    """Get or create the singleton LLM provider."""
    global _instance
    if _instance is None:
        _instance = LLMProvider()
    return _instance
