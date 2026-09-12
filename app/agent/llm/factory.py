"""Factory provider instantiating configured LLMProvider instances."""

from app.agent.llm.base import LLMProvider
from app.agent.llm.gemini_provider import GeminiProvider
from app.agent.llm.openai_provider import OpenAIProvider
from app.core.config import SandboxSettings, settings
from app.core.exceptions import LLMProviderError


def get_llm_provider(config: SandboxSettings | None = None) -> LLMProvider:
    """Return an instantiated LLMProvider matching current platform settings."""
    cfg = config or settings
    provider_name = cfg.LLM_PROVIDER.strip().lower()

    match provider_name:
        case "gemini":
            return GeminiProvider(
                api_key=cfg.LLM_API_KEY,
                model=cfg.LLM_MODEL,
                temperature=cfg.LLM_TEMPERATURE,
            )
        case "openai":
            return OpenAIProvider(
                api_key=cfg.LLM_API_KEY,
                model=cfg.LLM_MODEL,
                base_url=cfg.LLM_BASE_URL,
                temperature=cfg.LLM_TEMPERATURE,
            )
        case _:
            raise LLMProviderError(
                f"Unsupported LLM provider: '{cfg.LLM_PROVIDER}'. Allowed: ['gemini', 'openai']",
                details={"provider": cfg.LLM_PROVIDER},
            )

