import json
from dataclasses import dataclass
from urllib import error, request


class AIProviderServiceError(Exception):
    pass


@dataclass
class AIProviderValidationResult:
    summary: str
    response_payload: dict
    request_url: str


@dataclass
class AIProviderExecutionResult:
    output_text: str
    response_payload: dict
    usage_metadata: dict
    request_url: str
    response_mime_type: str
    summary: str


class BaseAIProviderAdapter:
    default_timeout_seconds = 120

    def __init__(self, integration):
        self.integration = integration

    def validate_connection(self):
        response_payload, request_url = self._perform_request(self.build_payload())
        return AIProviderValidationResult(
            summary=self.extract_summary(response_payload),
            response_payload=response_payload,
            request_url=request_url,
        )

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
        raise AIProviderServiceError(
            f"O provedor '{self.integration.provider_type}' ainda nao suporta execucao de documento neste backend."
        )

    def execute_prompt_without_document(
        self,
        *,
        prompt,
        execution_params,
        model_name,
    ):
        raise AIProviderServiceError(
            f"O provedor '{self.integration.provider_type}' ainda nao suporta execucao sem documento neste backend."
        )

    def execute_prompt_with_documents(
        self,
        *,
        prompt,
        documents,
        execution_params,
        model_name,
    ):
        raise AIProviderServiceError(
            f"O provedor '{self.integration.provider_type}' ainda nao suporta execucao agrupada de documentos neste backend."
        )

    def build_url(self):
        raise NotImplementedError

    def build_headers(self):
        raise NotImplementedError

    def build_payload(self):
        raise NotImplementedError

    def extract_summary(self, response_payload):
        raise NotImplementedError

    def _perform_request(self, payload):
        if not self.integration.default_model:
            raise AIProviderServiceError(
                "Informe o modelo padrao antes de validar a integracao de IA."
            )
        if not self.integration.api_key:
            raise AIProviderServiceError(
                "Informe a credencial principal do provedor antes de validar."
            )

        request_url = self.build_url()
        return self._post_json_request(
            request_url,
            payload,
            http_error_prefix="Falha HTTP {code} ao validar o provedor: {body}",
            connection_error_prefix="Falha de conexao ao validar o provedor: {reason}",
            invalid_json_message="O provedor retornou uma resposta invalida para a validacao.",
        )

    def _post_json_request(
        self,
        request_url,
        payload,
        *,
        http_error_prefix,
        connection_error_prefix,
        invalid_json_message,
    ):
        raw_payload = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            request_url,
            data=raw_payload,
            headers=self.build_headers(),
            method="POST",
        )
        try:
            with request.urlopen(
                http_request,
                timeout=self.integration.timeout_seconds or self.default_timeout_seconds,
            ) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise AIProviderServiceError(
                http_error_prefix.format(code=exc.code, body=error_body)
            ) from exc
        except error.URLError as exc:
            raise AIProviderServiceError(
                connection_error_prefix.format(reason=exc.reason)
            ) from exc

        try:
            return json.loads(raw_body), request_url
        except json.JSONDecodeError as exc:
            raise AIProviderServiceError(invalid_json_message) from exc

    def _truncate(self, value, limit=180):
        if not value:
            return ""
        if len(value) <= limit:
            return value
        return f"{value[: limit - 3]}..."
