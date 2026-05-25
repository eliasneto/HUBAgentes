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


@dataclass(frozen=True)
class IntegrationValidationResult:
    success: bool
    message: str


def validate_ai_provider_integration(integration) -> IntegrationValidationResult:
    try:
        adapter = get_ai_provider_adapter(integration)
        validation_result = adapter.validate_connection()
    except AIProviderServiceError as exc:
        integration.last_validated_at = timezone.now()
        integration.last_error = str(exc)
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
        return IntegrationValidationResult(False, f"{integration.nome}: {exc}")

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
        f"{integration.nome}: storage local validado em {resolved_path}.",
    )


def _mark_google_drive_error(integration, error_message):
    integration.last_error = error_message
    if integration.status == IntegrationStatus.ATIVA:
        integration.status = IntegrationStatus.ERRO
    integration.save(update_fields=["last_error", "status", "updated_at"])
    return IntegrationValidationResult(False, f"{integration.nome}: {error_message}")
