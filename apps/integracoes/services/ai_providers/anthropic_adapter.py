import base64

from .base import AIProviderExecutionResult, BaseAIProviderAdapter

_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_TEXT_MIME_TYPES = {"text/plain", "text/html", "text/markdown", "text/csv", "application/csv"}
_DEFAULT_MAX_TOKENS = 8192


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

    # ── Execução sem documento ────────────────────────────────────

    def execute_prompt_without_document(self, *, prompt, execution_params, model_name):
        url = self.build_url()
        payload = self._text_payload(model_name, prompt, execution_params)
        return self._call(url, payload, execution_params)

    # ── Execução com 1 documento ──────────────────────────────────

    def execute_prompt_with_document(
        self,
        *,
        prompt,
        document_bytes,
        document_mime_type,
        document_name,
        execution_params,
        model_name,
    ):
        url = self.build_url()
        params = execution_params or {}
        prompt_text = self._maybe_add_json_hint(prompt, params)
        content = [
            self._document_part(document_bytes, document_mime_type, document_name),
            {"type": "text", "text": f"{prompt_text}\n\nArquivo analisado: {document_name}"},
        ]
        payload = self._messages_payload(model_name, content, params)
        return self._call(url, payload, params)

    # ── Execução com N documentos ─────────────────────────────────

    def execute_prompt_with_documents(
        self,
        *,
        prompt,
        documents,
        execution_params,
        model_name,
    ):
        url = self.build_url()
        params = execution_params or {}
        content = []
        doc_names = []
        for doc in documents or []:
            doc_bytes = doc.get("document_bytes", b"")
            doc_mime = doc.get("document_mime_type", "application/pdf")
            doc_name = doc.get("document_name", "documento.pdf")
            doc_names.append(doc_name)
            content.append(self._document_part(doc_bytes, doc_mime, doc_name))
        prompt_text = self._maybe_add_json_hint(prompt, params)
        suffix = f"\n\nArquivos analisados: {', '.join(doc_names)}" if doc_names else ""
        content.append({"type": "text", "text": prompt_text + suffix})
        payload = self._messages_payload(model_name, content, params)
        return self._call(url, payload, params)

    # ── Helpers ───────────────────────────────────────────────────

    def _document_part(self, document_bytes, document_mime_type, document_name):
        if document_mime_type in _IMAGE_MIME_TYPES:
            return {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": document_mime_type,
                    "data": base64.b64encode(document_bytes).decode("utf-8"),
                },
            }
        if document_mime_type == "application/pdf":
            return {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.b64encode(document_bytes).decode("utf-8"),
                },
            }
        # Texto simples (TXT, CSV, HTML, MD) e demais: inclui como texto
        if document_mime_type in _TEXT_MIME_TYPES or document_mime_type.startswith("text/"):
            try:
                text_content = document_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text_content = document_bytes.decode("latin-1", errors="replace")
            return {"type": "text", "text": f"[Arquivo: {document_name}]\n{text_content}"}
        # Fallback genérico: tenta decodificar como texto
        try:
            text_content = document_bytes.decode("utf-8")
        except UnicodeDecodeError:
            text_content = document_bytes.decode("latin-1", errors="replace")
        return {"type": "text", "text": f"[Arquivo: {document_name}]\n{text_content}"}

    def _text_payload(self, model_name, prompt, execution_params):
        params = execution_params or {}
        content = self._maybe_add_json_hint(prompt, params)
        return self._messages_payload(model_name, content, params)

    def _messages_payload(self, model_name, content, params):
        payload = {
            "model": model_name or self.integration.default_model,
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "messages": [{"role": "user", "content": content}],
        }
        if not isinstance(params, dict):
            return payload
        if params.get("max_output_tokens"):
            payload["max_tokens"] = params["max_output_tokens"]
        if params.get("temperature") is not None:
            payload["temperature"] = params["temperature"]
        if params.get("top_p") is not None:
            payload["top_p"] = params["top_p"]
        if params.get("top_k") is not None:
            payload["top_k"] = params["top_k"]
        if params.get("stop_sequences"):
            payload["stop_sequences"] = params["stop_sequences"]
        return payload

    @staticmethod
    def _maybe_add_json_hint(prompt, params):
        if isinstance(params, dict) and params.get("response_mime_type") == "application/json":
            return (
                prompt
                + "\n\nIMPORTANTE: Responda APENAS com JSON valido, sem texto adicional antes ou depois."
            )
        return prompt

    def _call(self, url, payload, execution_params):
        response_payload, _ = self._post_json_request(
            url,
            payload,
            http_error_prefix="Anthropic HTTP {code}: {body}",
            connection_error_prefix="Falha de conexao com Anthropic: {reason}",
            invalid_json_message="Anthropic retornou resposta invalida.",
        )
        output_text = self._extract_output_text(response_payload)
        usage = response_payload.get("usage", {})
        input_tokens = usage.get("input_tokens") or 0
        output_tokens = usage.get("output_tokens") or 0
        usage_metadata = {
            "promptTokenCount": input_tokens,
            "candidatesTokenCount": output_tokens,
            "totalTokenCount": input_tokens + output_tokens,
        }
        params = execution_params or {}
        response_mime_type = (
            params.get("response_mime_type") if isinstance(params, dict) else ""
        ) or "text/plain"
        return AIProviderExecutionResult(
            output_text=output_text,
            response_payload=response_payload,
            usage_metadata=usage_metadata,
            request_url=url,
            response_mime_type=response_mime_type,
            summary=self.extract_summary(response_payload),
        )

    def _extract_output_text(self, response_payload):
        texts = []
        for item in response_payload.get("content", []):
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(t for t in texts if t).strip()
