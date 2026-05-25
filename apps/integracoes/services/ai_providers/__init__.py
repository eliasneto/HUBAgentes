from apps.integracoes.models import AIProviderType

from .anthropic_adapter import AnthropicProviderAdapter
from .base import AIProviderServiceError
from .gemini_adapter import GeminiProviderAdapter
from .openai_adapter import OpenAIProviderAdapter


def get_ai_provider_adapter(integration):
    adapters = {
        AIProviderType.OPENAI: OpenAIProviderAdapter,
        AIProviderType.ANTHROPIC: AnthropicProviderAdapter,
        AIProviderType.GEMINI: GeminiProviderAdapter,
    }
    adapter_class = adapters.get(integration.provider_type)
    if adapter_class is None:
        raise AIProviderServiceError(
            f"Provedor '{integration.provider_type}' ainda nao suportado."
        )
    return adapter_class(integration)


__all__ = ["AIProviderServiceError", "get_ai_provider_adapter"]
