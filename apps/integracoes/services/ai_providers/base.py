import json
import logging
import random
import time
from dataclasses import dataclass
from urllib import error, request

logger = logging.getLogger(__name__)


# Erros transitorios do provedor: vale a pena repetir a chamada.
# 408 timeout, 409 conflito momentaneo, 425 too early, 429 rate limit,
# 500/502/503/504 instabilidade do servidor, 529 overloaded (Anthropic).
_RETRYABLE_HTTP_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


class AIProviderServiceError(Exception):
    def __init__(self, message, *, technical_message="", usage_metadata=None, retryable=False):
        super().__init__(message)
        # Quando preenchido, a camada de normalizacao mostra `message` ao
        # usuario (amigavel) e guarda `technical_message` para o administrador.
        self.technical_message = technical_message
        # Tokens efetivamente consumidos quando a chamada retornou com sucesso
        # no HTTP mas o conteudo foi rejeitado (ex.: resposta truncada). O
        # provedor cobra por esses tokens, entao precisamos registra-los mesmo
        # no erro. None quando a falha nao consumiu tokens (ex.: timeout, 4xx).
        self.usage_metadata = usage_metadata
        # True apenas para falhas transitorias que se resolvem sozinhas
        # (provedor indisponivel/sobrecarregado, timeout, conexao). Erros que
        # exigem intervencao manual (4xx, documento grande demais, saida
        # invalida) mantem o padrao False e nao sao reprocessados.
        self.retryable = retryable


# Mensagem amigavel para quando o provedor esta temporariamente indisponivel
# (sobrecarregado ou com limite de uso atingido) mesmo apos as retentativas.
_PROVIDER_TEMPORARIAMENTE_INDISPONIVEL = (
    "O provedor de IA esta temporariamente indisponivel ou sobrecarregado. "
    "Aguarde alguns instantes e execute o agente novamente."
)

# Mensagem amigavel para quando o documento+prompt excede a janela de contexto
# do modelo (HTTP 400/413 com erro de "prompt too long" / context length).
_DOCUMENTO_GRANDE_DEMAIS = (
    "O documento e muito grande para este modelo de IA: o conteudo ultrapassa "
    "o limite de contexto suportado pelo modelo. Use um modelo com janela de "
    "contexto maior ou divida o documento em partes menores."
)

# Trechos que identificam erro de contexto/tamanho excedido no corpo de um 400.
# Cobre as variacoes dos provedores: Anthropic ("prompt is too long"),
# OpenAI ("context_length_exceeded"/"maximum context length") e Gemini
# ("input token count ... exceeds the maximum").
_CONTEXT_LENGTH_ERROR_PATTERNS = (
    "prompt is too long",
    "maximum context length",
    "context length",
    "context_length_exceeded",
    "input token count",
    "exceeds the maximum number of tokens",
    "too many tokens",
    "input is too long",
    "request entity too large",
)


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
    # Timeout de validacao e menor que o de execucao para nao ultrapassar
    # o timeout do proxy reverso (OpenResty/nginx tipicamente 60s).
    validation_timeout_seconds = 25
    # Tentativas extras quando a API responde com erro transitorio
    # (429 rate limit, 5xx, 529 overloaded) ou falha de conexao/timeout.
    # Erros transitorios costumam responder rapido, entao repetir com um
    # backoff curto resolve a maioria das falhas intermitentes sem que o
    # usuario perceba. Erros definitivos (401/403/400) nao sao repetidos.
    max_transient_retries = 3
    retry_base_delay_seconds = 1.5
    retry_max_delay_seconds = 12.0

    def __init__(self, integration):
        self.integration = integration

    def validate_connection(self):
        response_payload, request_url = self._perform_request(
            self.build_payload(), timeout=self.validation_timeout_seconds
        )
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

    def _perform_request(self, payload, timeout=None):
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
            timeout=timeout,
        )

    def _post_json_request(
        self,
        request_url,
        payload,
        *,
        http_error_prefix,
        connection_error_prefix,
        invalid_json_message,
        timeout=None,
    ):
        raw_payload = json.dumps(payload).encode("utf-8")
        effective_timeout = timeout or self.integration.timeout_seconds or self.default_timeout_seconds

        attempt = 0
        while True:
            # Reconstroi o Request a cada tentativa: o corpo de um Request ja
            # consumido nao pode ser reenviado.
            http_request = request.Request(
                request_url,
                data=raw_payload,
                headers=self.build_headers(),
                method="POST",
            )
            try:
                with request.urlopen(
                    http_request,
                    timeout=effective_timeout,
                ) as response:
                    raw_body = response.read().decode("utf-8")
                break
            except error.HTTPError as exc:
                is_retryable = exc.code in _RETRYABLE_HTTP_STATUS
                if is_retryable and attempt < self.max_transient_retries:
                    delay = self._retry_delay_seconds(attempt, http_error=exc)
                    self._log_retry(request_url, attempt, f"HTTP {exc.code}", delay)
                    time.sleep(delay)
                    attempt += 1
                    continue
                error_body = exc.read().decode("utf-8", errors="replace")
                detalhe_tecnico = http_error_prefix.format(code=exc.code, body=error_body)
                if is_retryable:
                    # Esgotou as retentativas e o erro era transitorio: o
                    # provedor segue indisponivel. Mostra mensagem amigavel
                    # de "tente novamente" em vez do erro tecnico cru.
                    # retryable=True: condicao transitoria, pode reprocessar.
                    raise AIProviderServiceError(
                        _PROVIDER_TEMPORARIAMENTE_INDISPONIVEL,
                        technical_message=detalhe_tecnico,
                        retryable=True,
                    ) from exc
                if self._eh_erro_contexto_excedido(exc.code, error_body):
                    # Documento+prompt maior que a janela do modelo: erro claro
                    # e acionavel em vez do tecnico generico mascarado.
                    raise AIProviderServiceError(
                        _DOCUMENTO_GRANDE_DEMAIS,
                        technical_message=detalhe_tecnico,
                    ) from exc
                raise AIProviderServiceError(detalhe_tecnico) from exc
            except (error.URLError, TimeoutError) as exc:
                # URLError cobre falhas de conexao/DNS; TimeoutError cobre
                # estouro do timeout da requisicao. Ambos sao transitorios.
                reason = getattr(exc, "reason", exc)
                if attempt < self.max_transient_retries:
                    delay = self._retry_delay_seconds(attempt)
                    self._log_retry(request_url, attempt, f"conexao: {reason}", delay)
                    time.sleep(delay)
                    attempt += 1
                    continue
                # retryable=True: falha de conexao/timeout e transitoria.
                raise AIProviderServiceError(
                    _PROVIDER_TEMPORARIAMENTE_INDISPONIVEL,
                    technical_message=connection_error_prefix.format(reason=reason),
                    retryable=True,
                ) from exc

        try:
            return json.loads(raw_body), request_url
        except json.JSONDecodeError as exc:
            raise AIProviderServiceError(invalid_json_message) from exc

    def _retry_delay_seconds(self, attempt, *, http_error=None):
        """Backoff exponencial com jitter; respeita Retry-After quando presente."""
        if http_error is not None:
            retry_after = self._parse_retry_after(http_error)
            if retry_after is not None:
                return min(retry_after, self.retry_max_delay_seconds)
        delay = self.retry_base_delay_seconds * (2 ** attempt)
        delay = min(delay, self.retry_max_delay_seconds)
        # Jitter evita que varias execucoes simultaneas repitam em sincronia.
        return delay + random.uniform(0, 0.5)

    @staticmethod
    def _parse_retry_after(http_error):
        """Le o cabecalho Retry-After (em segundos) de uma resposta de erro."""
        try:
            header_value = http_error.headers.get("Retry-After")
        except AttributeError:
            return None
        if not header_value:
            return None
        try:
            return max(float(header_value), 0.0)
        except (TypeError, ValueError):
            # Retry-After pode vir como data HTTP; nesse caso ignoramos e
            # usamos o backoff exponencial padrao.
            return None

    @staticmethod
    def _eh_erro_contexto_excedido(code, body):
        """True quando o 400/413 indica documento+prompt acima do contexto."""
        if code not in (400, 413):
            return False
        normalized = (body or "").lower()
        return any(pattern in normalized for pattern in _CONTEXT_LENGTH_ERROR_PATTERNS)

    def _log_retry(self, request_url, attempt, reason, delay):
        logger.warning(
            "Erro transitorio do provedor %s (%s) em %s. "
            "Tentativa %d de %d; repetindo em %.1fs.",
            getattr(self.integration, "provider_type", "?"),
            reason,
            request_url,
            attempt + 1,
            self.max_transient_retries,
            delay,
        )

    def _truncate(self, value, limit=180):
        if not value:
            return ""
        if len(value) <= limit:
            return value
        return f"{value[: limit - 3]}..."
