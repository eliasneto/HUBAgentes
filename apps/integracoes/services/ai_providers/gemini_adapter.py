from urllib.parse import urlencode

import base64

from .base import AIProviderExecutionResult, BaseAIProviderAdapter


class GeminiProviderAdapter(BaseAIProviderAdapter):
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

    def build_url(self):
        base_url = (self.integration.api_base_url or self.default_base_url).rstrip("/")
        if "{model}" in base_url:
            endpoint = base_url.format(model=self.integration.default_model)
        elif base_url.endswith(":generateContent"):
            endpoint = base_url
        else:
            endpoint = (
                f"{base_url}/models/{self.integration.default_model}:generateContent"
            )
        query_string = urlencode({"key": self.integration.api_key})
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}{query_string}"

    def build_headers(self):
        return {
            "Content-Type": "application/json",
        }

    def build_payload(self):
        return {
            "contents": [
                {
                    "parts": [
                        {
                            "text": "Responda apenas com OK para validar a integracao."
                        }
                    ]
                }
            ]
        }

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
        request_url = self._build_execution_url(model_name)
        payload = self._build_execution_payload(
            prompt=prompt,
            document_bytes=document_bytes,
            document_mime_type=document_mime_type,
            document_name=document_name,
            execution_params=execution_params or {},
        )
        response_payload = self._post_json(request_url, payload)
        output_text = self._extract_output_text(response_payload)
        response_mime_type = (
            execution_params.get("response_mime_type")
            if isinstance(execution_params, dict)
            else ""
        ) or "text/plain"
        return AIProviderExecutionResult(
            output_text=output_text,
            response_payload=response_payload,
            usage_metadata=response_payload.get("usageMetadata", {}),
            request_url=request_url,
            response_mime_type=response_mime_type,
            summary=self.extract_summary(response_payload),
        )

    def execute_prompt_without_document(
        self,
        *,
        prompt,
        execution_params,
        model_name,
    ):
        request_url = self._build_execution_url(model_name)
        payload = self._build_text_execution_payload(
            prompt=prompt,
            execution_params=execution_params or {},
        )
        response_payload = self._post_json(request_url, payload)
        output_text = self._extract_output_text(response_payload)
        response_mime_type = (
            execution_params.get("response_mime_type")
            if isinstance(execution_params, dict)
            else ""
        ) or "text/plain"
        return AIProviderExecutionResult(
            output_text=output_text,
            response_payload=response_payload,
            usage_metadata=response_payload.get("usageMetadata", {}),
            request_url=request_url,
            response_mime_type=response_mime_type,
            summary=self.extract_summary(response_payload),
        )

    def execute_prompt_with_documents(
        self,
        *,
        prompt,
        documents,
        execution_params,
        model_name,
    ):
        request_url = self._build_execution_url(model_name)
        payload = self._build_multi_document_execution_payload(
            prompt=prompt,
            documents=documents or [],
            execution_params=execution_params or {},
        )
        response_payload = self._post_json(request_url, payload)
        output_text = self._extract_output_text(response_payload)
        response_mime_type = (
            execution_params.get("response_mime_type")
            if isinstance(execution_params, dict)
            else ""
        ) or "text/plain"
        return AIProviderExecutionResult(
            output_text=output_text,
            response_payload=response_payload,
            usage_metadata=response_payload.get("usageMetadata", {}),
            request_url=request_url,
            response_mime_type=response_mime_type,
            summary=self.extract_summary(response_payload),
        )

    def extract_summary(self, response_payload):
        candidates = response_payload.get("candidates", [])
        texts = []
        for candidate in candidates:
            parts = (
                candidate.get("content", {}).get("parts", [])
                if isinstance(candidate.get("content"), dict)
                else []
            )
            for part in parts:
                if "text" in part:
                    texts.append(part["text"])
        response_text = self._truncate(" ".join(texts))
        return (
            f"Resposta recebida do modelo {self.integration.default_model}. "
            f"Trecho: {response_text or 'sem texto retornado'}"
        )

    def _build_execution_url(self, model_name):
        base_url = (self.integration.api_base_url or self.default_base_url).rstrip("/")
        if "{model}" in base_url:
            endpoint = base_url.format(model=model_name)
        elif base_url.endswith(":generateContent"):
            endpoint = base_url
        else:
            endpoint = f"{base_url}/models/{model_name}:generateContent"
        query_string = urlencode({"key": self.integration.api_key})
        separator = "&" if "?" in endpoint else "?"
        return f"{endpoint}{separator}{query_string}"

    def _build_execution_payload(
        self,
        *,
        prompt,
        document_bytes,
        document_mime_type,
        document_name,
        execution_params,
    ):
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": document_mime_type,
                                "data": base64.b64encode(document_bytes).decode("utf-8"),
                            }
                        },
                        {
                            "text": f"{prompt}\n\nArquivo analisado: {document_name}",
                        },
                    ]
                }
            ]
        }
        generation_config = self._build_generation_config(execution_params)
        if generation_config:
            payload["generationConfig"] = generation_config
        return payload

    def _build_text_execution_payload(
        self,
        *,
        prompt,
        execution_params,
    ):
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt,
                        },
                    ]
                }
            ]
        }
        generation_config = self._build_generation_config(execution_params)
        if generation_config:
            payload["generationConfig"] = generation_config
        return payload

    def _build_multi_document_execution_payload(
        self,
        *,
        prompt,
        documents,
        execution_params,
    ):
        parts = []
        document_names = []
        for document in documents:
            document_bytes = document.get("document_bytes", b"")
            document_mime_type = document.get("document_mime_type", "application/pdf")
            document_name = document.get("document_name", "documento.pdf")
            document_names.append(document_name)
            parts.append(
                {
                    "inline_data": {
                        "mime_type": document_mime_type,
                        "data": base64.b64encode(document_bytes).decode("utf-8"),
                    }
                }
            )
        joined_names = ", ".join(document_names)
        parts.append(
            {
                "text": (
                    f"{prompt}\n\nArquivos analisados em conjunto: {joined_names}"
                    if joined_names
                    else prompt
                )
            }
        )
        payload = {"contents": [{"parts": parts}]}
        generation_config = self._build_generation_config(execution_params)
        if generation_config:
            payload["generationConfig"] = generation_config
        return payload

    def _build_generation_config(self, execution_params):
        if not isinstance(execution_params, dict):
            return {}
        generation_config = {}
        field_map = {
            "temperature": "temperature",
            "top_p": "topP",
            "top_k": "topK",
            "max_output_tokens": "maxOutputTokens",
            "candidate_count": "candidateCount",
            "stop_sequences": "stopSequences",
            "response_mime_type": "responseMimeType",
            "response_json_schema": "responseJsonSchema",
        }
        for source_field, target_field in field_map.items():
            value = execution_params.get(source_field)
            if value not in (None, "", [], {}):
                generation_config[target_field] = value
        return generation_config

    def _post_json(self, request_url, payload):
        response_payload, _ = self._post_json_request(
            request_url,
            payload,
            http_error_prefix="Falha HTTP {code} ao executar o agente no provedor: {body}",
            connection_error_prefix="Falha de conexao ao executar o agente no provedor: {reason}",
            invalid_json_message="O provedor retornou uma resposta invalida para a execucao.",
        )
        return response_payload

    def _extract_output_text(self, response_payload):
        texts = []
        for candidate in response_payload.get("candidates", []):
            content = candidate.get("content", {})
            parts = content.get("parts", []) if isinstance(content, dict) else []
            for part in parts:
                if "text" in part:
                    texts.append(part["text"])
        return "\n".join(text for text in texts if text).strip()
