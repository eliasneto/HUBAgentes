from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.fields import EncryptedCharField, EncryptedTextField
from apps.core.models import SoftDeleteModel, TimestampedModel, UserStampedModel
from apps.integracoes.services.google_drive import (
    GoogleDriveServiceError,
    extract_folder_id_from_url,
)


class IntegrationStatus(models.TextChoices):
    ATIVA = "ativa", "Ativa"
    INATIVA = "inativa", "Inativa"
    ERRO = "erro", "Erro"


class AIProviderType(models.TextChoices):
    OPENAI = "openai", "OpenAI"
    ANTHROPIC = "anthropic", "Anthropic"
    GEMINI = "gemini", "Gemini"


class FolderItemType(models.TextChoices):
    PASTA = "pasta", "Pasta"
    PDF = "pdf", "PDF"
    OUTRO = "outro", "Outro"


class LocalStorageIntegration(SoftDeleteModel, UserStampedModel):
    nome = models.CharField(max_length=120, unique=True)
    status = models.CharField(
        max_length=20,
        choices=IntegrationStatus.choices,
        default=IntegrationStatus.INATIVA,
    )
    base_path = models.CharField(max_length=500)
    allowed_extensions = models.JSONField(default=list, blank=True)
    recursive_scan = models.BooleanField(default=False)
    last_validated_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        verbose_name = "Conexao de pasta local"
        verbose_name_plural = "Conexoes de pasta local"
        indexes = [
            models.Index(fields=["status"]),
        ]

    def clean(self):
        super().clean()
        if not self.allowed_extensions:
            self.allowed_extensions = ["pdf"]
        normalized_extensions = [str(extension).lower().lstrip(".") for extension in self.allowed_extensions]
        if any(extension != "pdf" for extension in normalized_extensions):
            raise ValidationError(
                {
                    "allowed_extensions": (
                        "No escopo atual, a integracao local aceita apenas arquivos PDF."
                    )
                }
            )
        self.allowed_extensions = normalized_extensions

        base_path = Path(self.base_path).expanduser()
        if not base_path.is_absolute():
            raise ValidationError(
                {"base_path": "Informe um caminho absoluto para a raiz autorizada. Use /app/entradas/ ou C:\\HubAgentes\\."}
            )

    def __str__(self):
        return self.nome


class GoogleDriveIntegration(SoftDeleteModel, UserStampedModel):
    nome = models.CharField(max_length=120, unique=True)
    status = models.CharField(
        max_length=20,
        choices=IntegrationStatus.choices,
        default=IntegrationStatus.INATIVA,
    )
    auth_mode = models.CharField(max_length=30, default="service_account")
    drive_folder_id = models.CharField(max_length=255, blank=True)
    # U1: criptografado em repouso — nunca armazenado em texto puro.
    credentials_json = EncryptedTextField()
    service_account_email = models.EmailField()
    allowed_extensions = models.JSONField(default=list, blank=True)
    last_connection_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        verbose_name = "Integracao Google Drive"
        verbose_name_plural = "Integracoes Google Drive"
        indexes = [
            models.Index(fields=["status"]),
        ]

    def clean(self):
        super().clean()
        if not self.allowed_extensions:
            self.allowed_extensions = ["pdf"]
        if any(extension.lower() != "pdf" for extension in self.allowed_extensions):
            raise ValidationError(
                {"allowed_extensions": "O MVP da Sprint 1 aceita apenas arquivos PDF."}
            )

    def __str__(self):
        return self.nome


class GoogleDriveFolderSource(UserStampedModel):
    nome = models.CharField(max_length=120)
    status = models.CharField(
        max_length=20,
        choices=IntegrationStatus.choices,
        default=IntegrationStatus.ATIVA,
    )
    google_drive_integration = models.ForeignKey(
        GoogleDriveIntegration,
        on_delete=models.PROTECT,
        related_name="folder_sources",
    )
    folder_url = models.URLField()
    folder_id = models.CharField(max_length=255, editable=False)
    folder_display_name = models.CharField(max_length=255, blank=True)
    last_validated_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        verbose_name = "Origem de pasta Google Drive"
        verbose_name_plural = "Origens de pasta Google Drive"
        constraints = [
            models.UniqueConstraint(
                fields=["google_drive_integration", "folder_id"],
                name="unique_folder_source_by_integration",
            )
        ]
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["folder_id"]),
        ]

    def clean(self):
        super().clean()
        try:
            self.folder_id = extract_folder_id_from_url(self.folder_url)
        except GoogleDriveServiceError as exc:
            raise ValidationError({"folder_url": str(exc)}) from exc

        if self.google_drive_integration.status != IntegrationStatus.ATIVA:
            raise ValidationError(
                {
                    "google_drive_integration": (
                        "A credencial tecnica do Google Drive precisa estar ativa."
                    )
                }
            )

    def __str__(self):
        return self.nome


class GoogleDriveFolderSourceItem(TimestampedModel):
    folder_source = models.ForeignKey(
        GoogleDriveFolderSource,
        on_delete=models.CASCADE,
        related_name="synced_items",
    )
    drive_item_id = models.CharField(max_length=255)
    nome = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120, blank=True)
    item_type = models.CharField(
        max_length=20,
        choices=FolderItemType.choices,
        default=FolderItemType.OUTRO,
    )
    parent_drive_id = models.CharField(max_length=255, blank=True)
    web_view_link = models.URLField(blank=True)
    checksum = models.CharField(max_length=128, blank=True)
    modified_at = models.DateTimeField(null=True, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    disponivel_para_ia = models.BooleanField(default=False)
    sincronizado_em = models.DateTimeField()

    class Meta:
        verbose_name = "Item sincronizado da origem Google Drive"
        verbose_name_plural = "Itens sincronizados da origem Google Drive"
        constraints = [
            models.UniqueConstraint(
                fields=["folder_source", "drive_item_id"],
                name="unique_folder_source_drive_item",
            )
        ]
        indexes = [
            models.Index(fields=["folder_source"]),
            models.Index(fields=["drive_item_id"]),
            models.Index(fields=["folder_source", "item_type"]),
            models.Index(fields=["folder_source", "disponivel_para_ia"]),
        ]
        ordering = ["item_type", "nome"]

    def __str__(self):
        return f"{self.nome} ({self.get_item_type_display()})"


class OpenAIIntegration(SoftDeleteModel, UserStampedModel):
    """
    Integracao com provedores de IA (OpenAI, Anthropic, Gemini).
    Mantido como classe principal para compatibilidade com migrations historicas.
    Use AIProviderIntegration (proxy formal abaixo) no codigo de producao.
    """

    nome = models.CharField(max_length=120, unique=True)
    provider_type = models.CharField(
        max_length=40,
        choices=AIProviderType.choices,
        default=AIProviderType.OPENAI,
    )
    status = models.CharField(
        max_length=20,
        choices=IntegrationStatus.choices,
        default=IntegrationStatus.INATIVA,
    )
    # U2: criptografado em repouso — nunca armazenado em texto puro.
    api_key = EncryptedCharField()
    api_base_url = models.URLField(blank=True)
    organization_id = models.CharField(max_length=120, blank=True)
    project_id = models.CharField(max_length=120, blank=True)
    default_model = models.CharField(max_length=120, blank=True)
    timeout_seconds = models.PositiveIntegerField(default=120)
    last_validated_at = models.DateTimeField(null=True, blank=True)
    last_connection_at = models.DateTimeField(null=True, blank=True)
    last_validation_summary = models.TextField(blank=True)
    last_error = models.TextField(blank=True)

    class Meta:
        verbose_name = "Integracao de IA"
        verbose_name_plural = "Integracoes de IA"
        indexes = [
            models.Index(
                fields=["provider_type", "status"],
                name="integ_ai_prov_status_idx",
            ),
            models.Index(fields=["status"], name="integracoes_status_716391_idx"),
        ]

    def clean(self):
        super().clean()
        if self.status == IntegrationStatus.ATIVA and not self.default_model:
            raise ValidationError(
                {
                    "default_model": (
                        "Informe o modelo padrao para uma integracao de IA ativa."
                    )
                }
            )
        if self.provider_type in {
            AIProviderType.OPENAI,
            AIProviderType.ANTHROPIC,
            AIProviderType.GEMINI,
        } and not self.api_key:
            raise ValidationError(
                {
                    "api_key": (
                        "Informe a credencial principal do provedor para esta integracao."
                    )
                }
            )

    def __str__(self):
        return f"{self.nome} ({self.get_provider_type_display()})"


class AIProviderIntegration(OpenAIIntegration):
    """
    A4: proxy formal do modelo OpenAIIntegration.
    Compartilha a mesma tabela; use este nome em todo codigo novo.
    O nome OpenAIIntegration sobrevive apenas nas migrations historicas.
    """

    class Meta:
        proxy = True
        verbose_name = "Integracao de IA"
        verbose_name_plural = "Integracoes de IA"
