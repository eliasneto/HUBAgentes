import base64

from .base import AIProviderExecutionResult, BaseAIProviderAdapter

_IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
_TEXT_MIME_TYPES = {"text/plain", "text/html", "text/markdown", "text/csv", "application/csv"}


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

    # ── Execução sem documento ────────────────────────────────────

    def execute_prompt_without_document(self, *, prompt, execution_params, model_name):
        url = self.build_url()
        params = execution_params or {}
        content = self._maybe_add_json_hint(prompt, params)
        payload = {"model": model_name or self.integration.default_model, "input": content}
        self._apply_params(payload, params)
        return self._call(url, payload, params)

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
            {"type": "input_text", "text": prompt_text},
        ]
        payload = {
            "model": model_name or self.integration.default_model,
            "input": [{"role": "user", "content": content}],
        }
        self._apply_params(payload, params)
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
        for doc in documents or []:
            doc_bytes = doc.get("document_bytes", b"")
            doc_mime = doc.get("document_mime_type", "application/pdf")
            doc_name = doc.get("document_name", "documento.pdf")
            content.append(self._document_part(doc_bytes, doc_mime, doc_name))
        prompt_text = self._maybe_add_json_hint(prompt, params)
        content.append({"type": "input_text", "text": prompt_text})
        payload = {
            "model": model_name or self.integration.default_model,
            "input": [{"role": "user", "content": content}],
        }
        self._apply_params(payload, params)
        return self._call(url, payload, params)

    # ── Helpers ───────────────────────────────────────────────────

    def _document_part(self, document_bytes, document_mime_type, document_name):
        if document_mime_type in _IMAGE_MIME_TYPES:
            return {
                "type": "input_image",
                "image_url": f"data:{document_mime_type};base64,{base64.b64encode(document_bytes).decode('utf-8')}",
            }
        if document_mime_type in _TEXT_MIME_TYPES or document_mime_type.startswith("text/"):
            try:
                text_content = document_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text_content = document_bytes.decode("latin-1", errors="replace")
            return {"type": "input_text", "text": f"[Arquivo: {document_name}]\n{text_content}"}
        # PDFs e demais binários: inline_data via data URL
        return {
            "type": "input_file",
            "filename": document_name,
            "file_data": f"data:{document_mime_type};base64,{base64.b64encode(document_bytes).decode('utf-8')}",
        }

    def _apply_params(self, payload, params):
        if not isinstance(params, dict):
            return
        if params.get("temperature") is not None:
            payload["temperature"] = params["temperature"]
        if params.get("top_p") is not None:
            payload["top_p"] = params["top_p"]
        if params.get("max_output_tokens"):
            payload["max_output_tokens"] = params["max_output_tokens"]

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
            http_error_prefix="OpenAI HTTP {code}: {body}",
            connection_error_prefix="Falha de conexao com OpenAI: {reason}",
            invalid_json_message="OpenAI retornou resposta invalida.",
        )
        output_text = response_payload.get("output_text", "")
        usage = response_payload.get("usage", {})
        usage_metadata = {
            "promptTokenCount": usage.get("input_tokens"),
            "candidatesTokenCount": usage.get("output_tokens"),
            "totalTokenCount": usage.get("total_tokens"),
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
