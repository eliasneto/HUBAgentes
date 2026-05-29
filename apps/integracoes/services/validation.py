from dataclasses import dataclass

from django.utils import timezone

from apps.integracoes.models import IntegrationStatus
from apps.integracoes.services.ai_providers import (
    AIProviderServiceError,
    get_ai_provider_adapter,
)
from apps.integracoes.services.google_drive import (
    GoogleDriveServiceError,
    build_drive_service,
)
from apps.integracoes.services.local_storage import (
    LocalStorageServiceError,
    validate_local_storage_integration,
)

MAX_LAST_ERROR_LENGTH = 12000
MAX_PORTAL_ERROR_LENGTH = 900


@dataclass(frozen=True)
class IntegrationValidationResult:
    success: bool
    message: str


def validate_ai_provider_integration(integration) -> IntegrationValidationResult:
    try:
        adapter = get_ai_provider_adapter(integration)
        validation_result = adapter.validate_connection()
    except AIProviderServiceError as exc:
        error_str = str(exc)
        if _eh_indisponibilidade_temporaria(error_str):
            return _mark_ai_provider_unavailable(integration, error_str)
        return _mark_ai_provider_error(integration, error_str)
    except Exception as exc:  # pragma: no cover
        return _mark_ai_provider_error(
            integration,
            f"Falha inesperada ao validar a integracao de IA: {exc}",
            user_message=(
                "falha tecnica ao validar a integracao. "
                "Contate o administrador do sistema."
            ),
        )

    integration.last_validated_at = timezone.now()
    integration.last_connection_at = integration.last_validated_at
    integration.last_error = ""
    integration.last_validation_summary = validation_result.summary
    if integration.status == IntegrationStatus.ERRO:
        integration.status = IntegrationStatus.ATIVA
    integration.save(
        update_fields=[
            "last_validated_at",
            "last_connection_at",
            "last_error",
            "last_validation_summary",
            "status",
            "updated_at",
        ]
    )
    return IntegrationValidationResult(
        True,
        f"{integration.nome}: integracao de IA validada com sucesso.",
    )


def _eh_indisponibilidade_temporaria(error_message: str) -> bool:
    normalized = error_message.lower()
    return (
        "503" in normalized
        or "unavailable" in normalized
        or "high demand" in normalized
        or "try again later" in normalized
        or "overloaded" in normalized
        or "service unavailable" in normalized
    )


def _mark_ai_provider_unavailable(integration, error_message) -> IntegrationValidationResult:
    """503 e indisponibilidade temporaria — nao altera o status da integracao."""
    integration.last_validated_at = timezone.now()
    integration.last_error = _truncate_error(error_message, MAX_LAST_ERROR_LENGTH)
    integration.last_validation_summary = ""
    integration.save(
        update_fields=[
            "last_validated_at",
            "last_error",
            "last_validation_summary",
            "updated_at",
        ]
    )
    return IntegrationValidationResult(
        False,
        (
            f"{integration.nome}: provedor temporariamente indisponivel (503). "
            "O status da integracao nao foi alterado. Tente validar novamente em alguns minutos."
        ),
    )


def _mark_ai_provider_error(integration, error_message, user_message=None):
    integration.last_validated_at = timezone.now()
    integration.last_error = _truncate_error(error_message, MAX_LAST_ERROR_LENGTH)
    integration.last_validation_summary = ""
    if integration.status == IntegrationStatus.ATIVA:
        integration.status = IntegrationStatus.ERRO
    integration.save(
        update_fields=[
            "last_validated_at",
            "last_error",
            "last_validation_summary",
            "status",
            "updated_at",
        ]
    )
    return IntegrationValidationResult(
        False,
        f"{integration.nome}: {user_message or _build_ai_provider_user_message(error_message)}",
    )


def _build_ai_provider_user_message(error_message):
    normalized_error = error_message.lower()
    if "503" in normalized_error or "unavailable" in normalized_error:
        return (
            "provedor temporariamente indisponivel. Aguarde alguns minutos e tente novamente."
        )
    if "429" in normalized_error or "resource_exhausted" in normalized_error:
        return (
            "cota do provedor excedida. Verifique o plano, billing ou limites "
            "do projeto no provedor de IA."
        )
    if "403" in normalized_error or "permission_denied" in normalized_error:
        return (
            "acesso negado pelo provedor. Verifique se a chave, o projeto e "
            "as permissoes estao liberados."
        )
    if "404" in normalized_error or "not_found" in normalized_error:
        return (
            "modelo nao encontrado ou nao suportado pelo provedor. Verifique "
            "o campo Modelo padrao."
        )
    if "modelo padrao" in normalized_error or "credencial principal" in normalized_error:
        return _truncate_error(error_message, MAX_PORTAL_ERROR_LENGTH)
    return (
        "falha ao validar a integracao. O erro tecnico foi salvo no cadastro "
        "para consulta do administrador."
    )


def _truncate_error(error_message, limit):
    if not error_message:
        return ""
    if len(error_message) <= limit:
        return error_message
    return f"{error_message[: limit - 3]}..."


def validate_google_drive_integration(integration) -> IntegrationValidationResult:
    try:
        service = build_drive_service(integration)
        service.about().get(fields="user").execute()
    except GoogleDriveServiceError as exc:
        return _mark_google_drive_error(integration, str(exc))
    except Exception as exc:  # pragma: no cover
        return _mark_google_drive_error(
            integration,
            f"Falha ao validar a credencial do Google Drive: {exc}",
        )

    integration.last_connection_at = timezone.now()
    integration.last_error = ""
    if integration.status == IntegrationStatus.ERRO:
        integration.status = IntegrationStatus.ATIVA
    integration.save(
        update_fields=[
            "last_connection_at",
            "last_error",
            "status",
            "updated_at",
        ]
    )
    return IntegrationValidationResult(
        True,
        f"{integration.nome}: credencial do Google Drive validada com sucesso.",
    )


def validate_local_storage(integration) -> IntegrationValidationResult:
    try:
        resolved_path = validate_local_storage_integration(integration)
    except LocalStorageServiceError as exc:
        integration.last_validated_at = timezone.now()
        integration.last_error = str(exc)
        if integration.status == IntegrationStatus.ATIVA:
            integration.status = IntegrationStatus.ERRO
        integration.save(
            update_fields=[
                "last_validated_at",
                "last_error",
                "status",
                "updated_at",
            ]
        )
        return IntegrationValidationResult(False, f"{integration.nome}: {exc}")

    integration.last_validated_at = timezone.now()
    integration.last_error = ""
    if integration.status == IntegrationStatus.ERRO:
        integration.status = IntegrationStatus.ATIVA
    integration.save(
        update_fields=[
            "last_validated_at",
            "last_error",
            "status",
            "updated_at",
        ]
    )
    return IntegrationValidationResult(
        True,
        f"{integration.nome}: pasta local validada em {resolved_path}.",
    )


def _mark_google_drive_error(integration, error_message):
    integration.last_error = error_message
    if integration.status == IntegrationStatus.ATIVA:
        integration.status = IntegrationStatus.ERRO
    integration.save(update_fields=["last_error", "status", "updated_at"])
    return IntegrationValidationResult(False, f"{integration.nome}: {error_message}")
