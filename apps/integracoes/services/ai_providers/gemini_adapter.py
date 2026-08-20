from urllib.parse import urlencode

import base64

from .base import (
    AIProviderExecutionResult,
    AIProviderServiceError,
    BaseAIProviderAdapter,
    redact_url_credentials,
)


# Erro que a Gemini devolve quando thinkingBudget=0 e enviado para um modelo
# que nao permite desligar o raciocinio interno (ex.: gemini-2.5-pro, que "so
# funciona em thinking mode" — diferente do 2.5 Flash/Flash-Lite, que aceita
# budget 0 normalmente). Ver AgenteConfiguracaoOperacional.
# enable_thinking_budget_reduction: a intencao documentada do toggle e nao
# ter efeito nenhum em modelos que nao suportam o ajuste, nunca quebrar a
# execucao — por isso, ao detectar esse erro especifico, a chamada e
# refeita sem thinkingConfig em vez de propagar a falha ao usuario.
_THINKING_BUDGET_INVALIDO_PATTERNS = (
    "budget 0 is invalid",
    "only works in thinking mode",
)


class GeminiProviderAdapter(BaseAIProviderAdapter):
    default_base_url = "https://generativelanguage.googleapis.com/v1beta"

    @staticmethod
    def _limpar_nome_modelo(nome: str) -> str:
        """Remove prefixo 'models/' caso o usuário tenha digitado por engano."""
        return nome.removeprefix("models/").strip()

    def build_url(self):
        base_url = (self.integration.api_base_url or self.default_base_url).rstrip("/")
        modelo = self._limpar_nome_modelo(self.integration.default_model)
        if "{model}" in base_url:
            endpoint = base_url.format(model=modelo)
        elif base_url.endswith(":generateContent"):
            endpoint = base_url
        else:
            endpoint = f"{base_url}/models/{modelo}:generateContent"
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
            request_url=redact_url_credentials(request_url),
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
            request_url=redact_url_credentials(request_url),
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
            request_url=redact_url_credentials(request_url),
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
        model_name = self._limpar_nome_modelo(model_name)
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
                        {"text": f"[Arquivo: {document_name}]"},
                        {
                            "inline_data": {
                                "mime_type": document_mime_type,
                                "data": base64.b64encode(document_bytes).decode("utf-8"),
                            }
                        },
                        {"text": prompt},
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
        for document in documents:
            document_bytes = document.get("document_bytes", b"")
            document_mime_type = document.get("document_mime_type", "application/pdf")
            document_name = document.get("document_name", "documento.pdf")
            parts.append({"text": f"[Arquivo: {document_name}]"})
            parts.append(
                {
                    "inline_data": {
                        "mime_type": document_mime_type,
                        "data": base64.b64encode(document_bytes).decode("utf-8"),
                    }
                }
            )
        parts.append({"text": prompt})
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
        # thinkingConfig e aninhado (nao cabe no field_map plano acima) e
        # thinkingBudget=0 (desabilita o raciocinio interno) e um valor
        # valido que a checagem `not in (None, "", [], {})` do loop acima
        # trataria como "ausente" por ser falsy — por isso checa `is not
        # None` explicitamente. Ver AgenteConfiguracaoOperacional.
        # enable_thinking_budget_reduction.
        thinking_budget = execution_params.get("thinking_budget")
        if thinking_budget is not None:
            generation_config["thinkingConfig"] = {"thinkingBudget": thinking_budget}
        return generation_config

    def _post_json(self, request_url, payload):
        try:
            response_payload, _ = self._post_json_request(
                request_url,
                payload,
                http_error_prefix="Falha HTTP {code} ao executar o agente no provedor: {body}",
                connection_error_prefix="Falha de conexao ao executar o agente no provedor: {reason}",
                invalid_json_message="O provedor retornou uma resposta invalida para a execucao.",
            )
            return response_payload
        except AIProviderServiceError as exc:
            thinking_config = payload.get("generationConfig", {}).get("thinkingConfig")
            if thinking_config is None or not self._eh_erro_thinking_budget_invalido(exc):
                raise
            # Modelo nao aceita desligar o raciocinio: refaz a chamada sem
            # thinkingConfig, para o toggle ficar sem efeito (como
            # documentado) em vez de quebrar a execucao inteira.
            payload["generationConfig"].pop("thinkingConfig", None)
            response_payload, _ = self._post_json_request(
                request_url,
                payload,
                http_error_prefix="Falha HTTP {code} ao executar o agente no provedor: {body}",
                connection_error_prefix="Falha de conexao ao executar o agente no provedor: {reason}",
                invalid_json_message="O provedor retornou uma resposta invalida para a execucao.",
            )
            return response_payload

    @staticmethod
    def _eh_erro_thinking_budget_invalido(exc):
        mensagem = str(exc).lower()
        return any(pattern in mensagem for pattern in _THINKING_BUDGET_INVALIDO_PATTERNS)

    def _extract_output_text(self, response_payload):
        texts = []
        for candidate in response_payload.get("candidates", []):
            content = candidate.get("content", {})
            parts = content.get("parts", []) if isinstance(content, dict) else []
            for part in parts:
                if "text" in part:
                    texts.append(part["text"])
        return "\n".join(text for text in texts if text).strip()
