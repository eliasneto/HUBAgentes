from .base import BaseAIProviderAdapter


class AnthropicProviderAdapter(BaseAIProviderAdapter):
    default_base_url = "https://api.anthropic.com/v1"
    api_version = "2023-06-01"

    def build_url(self):
        base_url = (self.integration.api_base_url or self.default_base_url).rstrip("/")
        if base_url.endswith("/messages"):
            return base_url
        return f"{base_url}/messages"

    def build_headers(self):
        return {
            "x-api-key": self.integration.api_key,
            "anthropic-version": self.api_version,
            "Content-Type": "application/json",
        }

    def build_payload(self):
        return {
            "model": self.integration.default_model,
            "max_tokens": 32,
            "messages": [
                {
                    "role": "user",
                    "content": "Responda apenas com OK para validar a integracao.",
                }
            ],
        }

    def extract_summary(self, response_payload):
        text_items = []
        for item in response_payload.get("content", []):
            if item.get("type") == "text":
                text_items.append(item.get("text", ""))
        response_text = self._truncate(" ".join(part for part in text_items if part))
        response_id = response_payload.get("id", "-")
        model = response_payload.get("model", self.integration.default_model)
        return (
            f"Resposta recebida do modelo {model}. "
            f"Request ID: {response_id}. Trecho: {response_text or 'sem texto retornado'}"
        )
