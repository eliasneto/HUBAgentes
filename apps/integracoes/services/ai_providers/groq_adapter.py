"""
Adapter para Groq — API compatível com OpenAI, somente texto.
Modelos: llama-3.3-70b-versatile, llama-3.1-8b-instant, mixtral-8x7b-32768, etc.
Documentação: https://console.groq.com/docs/openai
"""
import json

from .base import AIProviderExecutionResult, AIProviderServiceError, BaseAIProviderAdapter

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL  = "llama-3.3-70b-versatile"

TEXT_MIME_TYPES = {"text/plain", "text/csv", "application/csv"}


class GroqProviderAdapter(BaseAIProviderAdapter):

    def build_url(self):
        base = (self.integration.api_base_url or GROQ_BASE_URL).rstrip("/")
        return f"{base}/chat/completions"

    def build_headers(self):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.integration.api_key}",
            "User-Agent": "HUBAgentes/1.3 (compatible; python-urllib)",
        }

    def build_payload(self):
        model = self.integration.default_model or DEFAULT_MODEL
        return {
            "model": model,
            "messages": [{"role": "user", "content": "Responda apenas com OK."}],
            "max_tokens": 5,
            "temperature": 0,
        }

    def extract_summary(self, response_payload):
        choices = response_payload.get("choices", [])
        text = ""
        if choices:
            text = choices[0].get("message", {}).get("content", "")
        model = response_payload.get("model", self.integration.default_model)
        return f"Conexao com Groq validada. Modelo: {model}. Resposta: {text[:80]}"

    # ── Execução sem documento ───────────────────────────────────

    def execute_prompt_without_document(self, *, prompt, execution_params, model_name):
        url     = self._url(model_name)
        payload = self._text_payload(model_name, prompt, execution_params)
        return self._call(url, payload, execution_params)

    # ── Execução com 1 documento ─────────────────────────────────

    def execute_prompt_with_document(
        self, *, prompt, document_bytes, document_mime_type,
        document_name, execution_params, model_name,
    ):
        content = self._extract_text_content(
            document_bytes, document_mime_type, document_name
        )
        full_prompt = (
            f"{prompt}\n\n--- Conteúdo do arquivo: {document_name} ---\n{content}"
        )
        url     = self._url(model_name)
        payload = self._text_payload(model_name, full_prompt, execution_params)
        return self._call(url, payload, execution_params)

    # ── Execução com N documentos ────────────────────────────────

    def execute_prompt_with_documents(
        self, *, prompt, documents, execution_params, model_name,
    ):
        parts = [prompt]
        for doc in documents or []:
            name    = doc.get("document_name", "arquivo")
            content = self._extract_text_content(
                doc.get("document_bytes", b""),
                doc.get("document_mime_type", "text/plain"),
                name,
            )
            parts.append(f"\n--- Arquivo: {name} ---\n{content}")
        full_prompt = "\n".join(parts)
        url     = self._url(model_name)
        payload = self._text_payload(model_name, full_prompt, execution_params)
        return self._call(url, payload, execution_params)

    # ── Helpers ──────────────────────────────────────────────────

    def _url(self, model_name):
        base = (self.integration.api_base_url or GROQ_BASE_URL).rstrip("/")
        return f"{base}/chat/completions"

    def _extract_text_content(self, document_bytes, document_mime_type, document_name):
        if document_mime_type in TEXT_MIME_TYPES or document_mime_type.startswith("text/"):
            try:
                return document_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return document_bytes.decode("latin-1", errors="replace")
        raise AIProviderServiceError(
            f"Groq suporta apenas arquivos de texto (TXT, CSV). "
            f"O arquivo '{document_name}' tem o tipo '{document_mime_type}', "
            f"que nao e suportado. Use o Gemini para PDFs e imagens."
        )

    def _text_payload(self, model_name, prompt, execution_params):
        model = model_name or self.integration.default_model or DEFAULT_MODEL
        params = execution_params or {}

        # Se o sistema espera JSON, instrui o modelo explicitamente
        content = prompt
        if isinstance(params, dict) and params.get("response_mime_type") == "application/json":
            content = (
                prompt
                + "\n\nIMPORTANTE: Responda APENAS com JSON válido, sem texto adicional antes ou depois."
            )

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 8000,  # suficiente para JSON detalhado sem estourar TPM
        }
        if isinstance(params, dict):
            if params.get("max_output_tokens"):
                payload["max_tokens"] = params["max_output_tokens"]
            if params.get("temperature") is not None:
                payload["temperature"] = params["temperature"]
        return payload

    def _call(self, url, payload, execution_params):
        response_payload, _ = self._post_json_request(
            url, payload,
            http_error_prefix="Groq HTTP {code}: {body}",
            connection_error_prefix="Falha de conexao com Groq: {reason}",
            invalid_json_message="Groq retornou resposta invalida.",
        )
        output_text = self._extract_text(response_payload)
        usage = response_payload.get("usage", {})
        usage_metadata = {
            "promptTokenCount":     usage.get("prompt_tokens"),
            "candidatesTokenCount": usage.get("completion_tokens"),
            "totalTokenCount":      usage.get("total_tokens"),
        }
        return AIProviderExecutionResult(
            output_text=output_text,
            response_payload=response_payload,
            usage_metadata=usage_metadata,
            request_url=url,
            response_mime_type="text/plain",
            summary=f"Resposta Groq ({payload.get('model')}): {output_text[:120]}",
        )

    def _extract_text(self, response_payload):
        choices = response_payload.get("choices", [])
        texts = []
        for choice in choices:
            msg = choice.get("message", {})
            if msg.get("content"):
                texts.append(msg["content"])
        return "\n".join(texts).strip()
