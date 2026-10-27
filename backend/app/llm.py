"""Chat-model factory. The provider is chosen by LLM_PROVIDER in .env.

Two tiers are exposed:
  * "fast"   - cheap model for intent classification
  * "strong" - better model for SQL generation, repair, optimize, debug, explain
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel

from app.config import get_settings

Tier = Literal["fast", "strong"]


class LLMConfigError(RuntimeError):
    """Raised when the LLM provider is missing or misconfigured."""


@lru_cache
def get_chat_model(tier: Tier = "strong") -> BaseChatModel:
    settings = get_settings()
    model = settings.llm_fast_model if tier == "fast" else settings.llm_strong_model
    common = {"temperature": settings.llm_temperature, "timeout": settings.llm_timeout_seconds}
    provider = settings.llm_provider.lower().strip()

    try:
        if provider == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(model=model, **common)
        if provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(model=model, **common)
        if provider == "groq":
            from langchain_groq import ChatGroq

            return ChatGroq(model=model, **common)
    except Exception as exc:  # missing key, bad model name, ...
        raise LLMConfigError(f"Could not initialise {provider} model '{model}': {exc}") from exc

    raise LLMConfigError(
        f"Unknown LLM_PROVIDER '{settings.llm_provider}'. Use openai, anthropic or groq."
    )
