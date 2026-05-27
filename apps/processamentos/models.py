from pathlib import Path

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.agentes_ia.models import AgenteIA, AgentStatus
from apps.agentes_ia.models import (
    AgentDocumentExecutionMode,
    AgentOutputAssemblyMode,
    AgentOutputPackagingMode,
)
from apps.core.models import TimestampedModel
from apps.integracoes.models import (
    AIProviderIntegration,
    GoogleDriveFolderSource,
    GoogleDriveIntegration,
    IntegrationStatus,
    LocalStorageIntegration,
)


def processamento_output_path(instance, filename):
    return f"processamentos/{instance.codigo}/{filename}"


def processamento_input_upload_path(instance, filename):
    return f"processamentos/{instance.codigo}/uploads/{filename}"


def documento_entrada_upload_path(instance, filename):
    return f"processamentos/{instance.processamento.codigo}/entradas/{filename}"


def documento_saida_output_path(instance, filename):
    return f"processamentos/{instance.processamento.codigo}/saidas/{filename}"


class ProcessingStatus(models.TextChoices):
    CRIADO = "criado", "Criado"
    EM_FILA = "em_fila", "Em fila"
    EM_PROCESSAMENTO = "em_processamento", "Em processamento"
    CONCLUIDO_SUCESSO = "concluido_sucesso", "Concluido com sucesso"
    CONCLUIDO_ERRO = "concluido_erro", "Concluido com erro"
    CANCELADO = "cancelado", "Cancelado"


class DocumentStatus(models.TextChoices):
    PENDENTE = "pendente", "Pendente"
    EM_PROCESSAMENTO = "em_processamento", "Em processamento"
    PROCESSADO = "processado", "Processado"
    ERRO = "erro", "Erro"


class AIExecutionStatus(models.TextChoices):
    SUCESSO = "sucesso", "Sucesso"
    ERRO = "erro", "Erro"


class ProcessingInputSourceType(models.TextChoices):
    GOOGLE_DRIVE_FOLDER = "google_drive_folder", "Google Drive - pasta"
    LOCAL_FOLDER = "local_folder", "Pasta local"
    LOCAL_FILE = "local_file", "Arquivo local fixo"
    UPLOAD_AT_EXECUTION = "upload_at_execution", "Arquivo informado na execucao"
    NONE = "none", "Sem origem documental"


class ProcessingOutputFormat(models.TextChoices):
    AI_DEFINED = "ai_defined", "Definido pela IA"
    JSON = "json", "JSON"
    XLSX = "xlsx", "Excel"
    CSV = "csv", "CSV"
    PDF = "pdf", "PDF"
    TXT = "txt", "TXT"
    ZIP = "zip", "ZIP"


class OutputDocumentStatus(models.TextChoices):
    GERADO = "gerado", "Gerado"
    ERRO = "erro", "Erro"


class ExecutionScopeType(models.TextChoices):
    SEM_DOCUMENTO = "sem_documento", "Sem documento"
    INDIVIDUAL = "individual", "Individual"
    GRUPO = "grupo", "Grupo"


class Processamento(TimestampedModel):
    codigo = models.CharField(max_length=40, unique=True)
    status = models.CharField(
        max_length=30,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.CRIADO,
    )
    iniciado_por = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        related_name="processamentos_iniciados",
    )
    agente = models.ForeignKey(
        AgenteIA,
        on_delete=models.PROTECT,
        related_name="processamentos",
    )
    input_source_type = models.CharField(
        max_length=30,
        choices=ProcessingInputSourceType.choices,
        default=ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
    )
    google_drive_integration = models.ForeignKey(
        GoogleDriveIntegration,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="processamentos",
    )
    folder_source = models.ForeignKey(
        GoogleDriveFolderSource,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="processamentos",
    )
    local_storage_integration = models.ForeignKey(
        LocalStorageIntegration,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="processamentos",
    )
    local_relative_input_path = models.CharField(max_length=500, blank=True)
    arquivo_execucao_upload = models.FileField(
        upload_to=processamento_input_upload_path,
        null=True,
        blank=True,
    )
    drive_folder_id_escolhida = models.CharField(max_length=255, blank=True)
    drive_folder_nome_escolhida = models.CharField(max_length=255, blank=True)
    drive_folder_url_escolhida = models.URLField(blank=True)
    output_format = models.CharField(
        max_length=20,
        choices=ProcessingOutputFormat.choices,
        default=ProcessingOutputFormat.JSON,
    )
    document_execution_mode_snapshot = models.CharField(
        max_length=30,
        choices=AgentDocumentExecutionMode.choices,
        default=AgentDocumentExecutionMode.INDIVIDUAL,
    )
    output_assembly_mode_snapshot = models.CharField(
        max_length=30,
        choices=AgentOutputAssemblyMode.choices,
        default=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
    )
    output_packaging_mode_snapshot = models.CharField(
        max_length=30,
        choices=AgentOutputPackagingMode.choices,
        default=AgentOutputPackagingMode.ZIP_SE_MULTIPLOS,
    )
    ai_provider_integration_snapshot = models.ForeignKey(
        AIProviderIntegration,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="processamentos_snapshot",
    )
    prompt_snapshot = models.TextField(blank=True)
    modelo_snapshot = models.CharField(max_length=120, blank=True)
    mensagem_erro = models.TextField(blank=True)
    mensagem_erro_tecnico = models.TextField(blank=True)
    total_documentos = models.PositiveIntegerField(default=0)
    total_processados = models.PositiveIntegerField(default=0)
    arquivo_saida = models.FileField(
        upload_to=processamento_output_path,
        null=True,
        blank=True,
    )
    arquivo_saida_nome = models.CharField(max_length=255, blank=True)
    arquivo_saida_formato = models.CharField(max_length=20, default="xlsx")
    arquivo_saida_liberado_em = models.DateTimeField(null=True, blank=True)
    iniciado_em = models.DateTimeField(default=timezone.now)
    finalizado_em = models.DateTimeField(null=True, blank=True)
    execucao_iniciada_em = models.DateTimeField(null=True, blank=True)
    execucao_finalizada_em = models.DateTimeField(null=True, blank=True)
    etapa_atual = models.CharField(max_length=120, blank=True)
    documento_atual_nome = models.CharField(max_length=255, blank=True)
    ultima_atividade_em = models.DateTimeField(null=True, blank=True)
    duracao_processamento_ms = models.PositiveIntegerField(null=True, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    processing_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    total_tokens = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        verbose_name = "Processamento"
        verbose_name_plural = "Processamentos"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["iniciado_por"]),
            models.Index(fields=["agente"]),
            models.Index(fields=["input_source_type"]),
            models.Index(fields=["google_drive_integration"]),
            models.Index(fields=["local_storage_integration"]),
            models.Index(fields=["iniciado_em"]),
        ]

    def clean(self):
        super().clean()
        if self.agente_id and self.agente.status != AgentStatus.ATIVO:
            raise ValidationError(
                {"agente": "Somente agentes ativos podem ser usados em um processamento."}
            )
        if (
            self.input_source_type == ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER
            and self.folder_source_id
        ):
            self.google_drive_integration = self.folder_source.google_drive_integration
            self.drive_folder_id_escolhida = self.folder_source.folder_id
            self.drive_folder_nome_escolhida = (
                self.folder_source.folder_display_name or self.folder_source.nome
            )
            self.drive_folder_url_escolhida = self.folder_source.folder_url
        if (
            self.agente_id
            and self.agente.ai_provider_integration.status != IntegrationStatus.ATIVA
        ):
            raise ValidationError(
                {"agente": "A integracao de IA do agente precisa estar ativa."}
            )
        if self.input_source_type == ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER:
            if not self.folder_source_id:
                raise ValidationError(
                    {"folder_source": "Selecione a pasta do Google Drive para este processamento."}
                )
            if (
                self.google_drive_integration_id
                and self.google_drive_integration.status != IntegrationStatus.ATIVA
            ):
                raise ValidationError(
                    {
                        "google_drive_integration": (
                            "A integracao Google Drive precisa estar ativa."
                        )
                    }
                )
        elif self.input_source_type in {
            ProcessingInputSourceType.LOCAL_FOLDER,
            ProcessingInputSourceType.LOCAL_FILE,
        }:
            if not self.local_storage_integration_id:
                raise ValidationError(
                    {
                        "local_storage_integration": (
                            "Selecione a integracao local autorizada para esta origem."
                        )
                    }
                )
            if not self.local_relative_input_path:
                raise ValidationError(
                    {
                        "local_relative_input_path": (
                            "Informe o caminho relativo da pasta ou do arquivo local."
                        )
                    }
                )
            if self.local_storage_integration.status != IntegrationStatus.ATIVA:
                raise ValidationError(
                    {
                            "local_storage_integration": (
                            "A integracao de pasta local precisa estar ativa."
                            )
                        }
                    )
        elif self.input_source_type == ProcessingInputSourceType.UPLOAD_AT_EXECUTION:
            if self.arquivo_execucao_upload and not self.arquivo_execucao_upload.name.lower().endswith(".pdf"):
                raise ValidationError(
                    {
                        "arquivo_execucao_upload": (
                            "No modo de upload em execucao, informe um arquivo PDF."
                        )
                    }
                )

        if self.output_format not in set(ProcessingOutputFormat.values):
            raise ValidationError(
                {"output_format": "Selecione um formato de saida valido para o processamento."}
            )
        if self.arquivo_saida_formato not in set(ProcessingOutputFormat.values):
            raise ValidationError(
                {
                    "arquivo_saida_formato": (
                        "O resumo operacional precisa usar um formato de saida suportado."
                    )
                }
            )

    def save(self, *args, **kwargs):
        if (
            self.input_source_type == ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER
            and self.folder_source_id
        ):
            self.google_drive_integration = self.folder_source.google_drive_integration
            self.drive_folder_id_escolhida = self.folder_source.folder_id
            self.drive_folder_nome_escolhida = (
                self.folder_source.folder_display_name or self.folder_source.nome
            )
            self.drive_folder_url_escolhida = self.folder_source.folder_url
        elif self.input_source_type != ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER:
            self.google_drive_integration = None
            self.folder_source = None
            self.drive_folder_id_escolhida = ""
            self.drive_folder_nome_escolhida = ""
            self.drive_folder_url_escolhida = ""
        if (not self.pk or not self.arquivo_saida) and self.output_format:
            self.arquivo_saida_formato = self.output_format
        if not self.ai_provider_integration_snapshot_id and self.agente_id:
            self.ai_provider_integration_snapshot = self.agente.ai_provider_integration
        if not self.prompt_snapshot and self.agente_id:
            self.prompt_snapshot = self.agente.prompt_base
        if not self.modelo_snapshot and self.agente_id:
            self.modelo_snapshot = (
                self.agente.modelo_preferencial
                or self.agente.ai_provider_integration.default_model
            )
        if self.status == ProcessingStatus.CONCLUIDO_SUCESSO:
            if self.arquivo_saida and not self.arquivo_saida_nome:
                self.arquivo_saida_nome = Path(self.arquivo_saida.name).name
            if self.arquivo_saida and not self.arquivo_saida_liberado_em:
                self.arquivo_saida_liberado_em = timezone.now()
            if not self.finalizado_em:
                self.finalizado_em = timezone.now()
        elif self.status in {
            ProcessingStatus.CONCLUIDO_ERRO,
            ProcessingStatus.CANCELADO,
        } and not self.finalizado_em:
            self.finalizado_em = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.codigo

    @property
    def openai_integration_snapshot(self):
        return self.ai_provider_integration_snapshot

    @openai_integration_snapshot.setter
    def openai_integration_snapshot(self, value):
        self.ai_provider_integration_snapshot = value


class DocumentoEntrada(TimestampedModel):
    processamento = models.ForeignKey(
        Processamento,
        on_delete=models.CASCADE,
        related_name="documentos",
    )
    nome_arquivo = models.CharField(max_length=255)
    drive_file_id = models.CharField(max_length=255, blank=True)
    drive_path = models.CharField(max_length=500, blank=True)
    source_type = models.CharField(
        max_length=30,
        choices=ProcessingInputSourceType.choices,
        default=ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
    )
    source_reference = models.CharField(max_length=500, blank=True)
    uploaded_file = models.FileField(
        upload_to=documento_entrada_upload_path,
        null=True,
        blank=True,
    )
    mime_type = models.CharField(max_length=120, blank=True)
    checksum = models.CharField(max_length=128, blank=True)
    status = models.CharField(
        max_length=20,
        choices=DocumentStatus.choices,
        default=DocumentStatus.PENDENTE,
    )
    mensagem_erro = models.TextField(blank=True)
    processado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Documento de entrada"
        verbose_name_plural = "Documentos de entrada"
        indexes = [
            models.Index(fields=["processamento"]),
            models.Index(fields=["drive_file_id"]),
            models.Index(fields=["processamento", "status"]),
            models.Index(fields=["processamento", "source_type"]),
        ]

    def clean(self):
        super().clean()
        if not self.nome_arquivo.lower().endswith(".pdf"):
            raise ValidationError(
                {"nome_arquivo": "No MVP, somente arquivos PDF sao aceitos como entrada."}
            )
        if (
            self.source_type == ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER
            and not self.drive_file_id
        ):
            raise ValidationError(
                {"drive_file_id": "Documentos vindos do Google Drive precisam do drive_file_id."}
            )
        if self.source_type in {
            ProcessingInputSourceType.LOCAL_FOLDER,
            ProcessingInputSourceType.LOCAL_FILE,
        } and not self.source_reference:
            raise ValidationError(
                {
                    "source_reference": (
                        "Documentos locais precisam da referencia relativa para rastreabilidade."
                    )
                }
            )
        if (
            self.source_type == ProcessingInputSourceType.UPLOAD_AT_EXECUTION
            and not self.uploaded_file
        ):
            raise ValidationError(
                {
                    "uploaded_file": (
                        "Documentos enviados na execucao precisam do arquivo persistido."
                    )
                }
            )

    def __str__(self):
        return self.nome_arquivo


class ProcessamentoExecucaoIA(TimestampedModel):
    processamento = models.ForeignKey(
        Processamento,
        on_delete=models.CASCADE,
        related_name="execucoes_ia",
    )
    documento = models.ForeignKey(
        "processamentos.DocumentoEntrada",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="execucoes_ia",
    )
    ai_provider_integration = models.ForeignKey(
        AIProviderIntegration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="execucoes_processamento",
    )
    tentativa_numero = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=AIExecutionStatus.choices,
        default=AIExecutionStatus.SUCESSO,
    )
    modelo_utilizado = models.CharField(max_length=120, blank=True)
    execucao_iniciada_em = models.DateTimeField(null=True, blank=True)
    execucao_finalizada_em = models.DateTimeField(null=True, blank=True)
    duracao_ms = models.PositiveIntegerField(null=True, blank=True)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    processing_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    total_tokens = models.PositiveIntegerField(null=True, blank=True)
    usage_metadata = models.JSONField(default=dict, blank=True)
    response_summary = models.TextField(blank=True)
    error_message = models.TextField(blank=True)
    scope_type = models.CharField(
        max_length=20,
        choices=ExecutionScopeType.choices,
        default=ExecutionScopeType.INDIVIDUAL,
    )
    documentos_referencia = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Execucao de IA do processamento"
        verbose_name_plural = "Execucoes de IA do processamento"
        indexes = [
            models.Index(
                fields=["processamento", "tentativa_numero"],
                name="processamen_process_03e92c_idx",
            ),
            models.Index(
                fields=["processamento", "status"],
                name="processamen_process_378e37_idx",
            ),
            models.Index(
                fields=["execucao_iniciada_em"],
                name="processamen_execuca_80a10b_idx",
            ),
        ]
        ordering = ["-tentativa_numero", "-created_at"]

    def __str__(self):
        return f"{self.processamento.codigo} - tentativa {self.tentativa_numero}"


class DocumentoSaidaProcessamento(TimestampedModel):
    processamento = models.ForeignKey(
        Processamento,
        on_delete=models.CASCADE,
        related_name="documentos_saida",
    )
    documento = models.ForeignKey(
        DocumentoEntrada,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="saidas",
    )
    execucao_ia = models.ForeignKey(
        ProcessamentoExecucaoIA,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documentos_saida",
    )
    formato = models.CharField(
        max_length=20,
        choices=ProcessingOutputFormat.choices,
        default=ProcessingOutputFormat.JSON,
    )
    status = models.CharField(
        max_length=20,
        choices=OutputDocumentStatus.choices,
        default=OutputDocumentStatus.GERADO,
    )
    arquivo = models.FileField(
        upload_to=documento_saida_output_path,
        null=True,
        blank=True,
    )
    arquivo_nome = models.CharField(max_length=255, blank=True)
    mensagem_erro = models.TextField(blank=True)
    liberado_em = models.DateTimeField(null=True, blank=True)
    scope_type = models.CharField(
        max_length=20,
        choices=ExecutionScopeType.choices,
        default=ExecutionScopeType.INDIVIDUAL,
    )
    documentos_referencia = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Saida de documento do processamento"
        verbose_name_plural = "Saidas de documento do processamento"
        indexes = [
            models.Index(fields=["processamento"]),
            models.Index(fields=["documento"]),
            models.Index(fields=["processamento", "status"]),
            models.Index(fields=["processamento", "formato"]),
        ]
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.arquivo and not self.arquivo_nome:
            self.arquivo_nome = Path(self.arquivo.name).name
        if self.arquivo and not self.liberado_em:
            self.liberado_em = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        documento_nome = self.documento.nome_arquivo if self.documento else "saida agrupada"
        return f"{self.processamento.codigo} - {documento_nome}"
