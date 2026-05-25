from .base import BaseAIProviderAdapter


class OpenAIProviderAdapter(BaseAIProviderAdapter):
    default_base_url = "https://api.openai.com/v1"

    def build_url(self):
        base_url = (self.integration.api_base_url or self.default_base_url).rstrip("/")
        if base_url.endswith("/responses"):
            return base_url
        return f"{base_url}/responses"

    def build_headers(self):
        headers = {
            "Authorization": f"Bearer {self.integration.api_key}",
            "Content-Type": "application/json",
        }
        if self.integration.organization_id:
            headers["OpenAI-Organization"] = self.integration.organization_id
        if self.integration.project_id:
            headers["OpenAI-Project"] = self.integration.project_id
        return headers

    def build_payload(self):
        return {
            "model": self.integration.default_model,
            "input": "Responda apenas com OK para validar a integracao.",
        }

    def extract_summary(self, response_payload):
        response_text = self._truncate(response_payload.get("output_text", ""))
        response_id = response_payload.get("id", "-")
        model = response_payload.get("model", self.integration.default_model)
        return (
            f"Resposta recebida do modelo {model}. "
            f"Request ID: {response_id}. Trecho: {response_text or 'sem texto retornado'}"
        )
