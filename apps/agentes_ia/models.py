from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.core.models import SoftDeleteModel, TimestampedModel, UserStampedModel
from apps.integracoes.models import AIProviderIntegration, IntegrationStatus


class AgentStatus(models.TextChoices):
    ATIVO = "ativo", "Ativo"
    PAUSADO = "pausado", "Pausado"
    INATIVO = "inativo", "Inativo"


class AgentType(models.TextChoices):
    CLASSIFICADOR = "classificador", "Classificador"
    EXTRATOR = "extrator", "Extrator"
    VALIDADOR = "validador", "Validador"
    ESTRUTURADOR = "estruturador", "Estruturador"
    GENERICO = "generico", "Generico"


class AgentOperationalCategory(models.TextChoices):
    LEITURA_DOCUMENTO = "leitura_documento", "Leitura de documento"
    DECISAO_DOCUMENTO = "decisao_documento", "Decisao sobre documento"
    ACAO_SISTEMA = "acao_sistema", "Acao de sistema"
    LEITURA_ARQUIVO = "leitura_arquivo", "Leitura de arquivo"
    GENERICO = "generico", "Generico"


class AgentVisibility(models.TextChoices):
    USUARIO = "usuario", "Agente para usuario"
    TECNICO = "tecnico", "Agente tecnico"


class AgentTriggerMode(models.TextChoices):
    PORTAL = "portal", "Manual no portal"
    BOTAO_CONTEXTUAL = "botao_contextual", "Botao contextual"
    EVENTO_SISTEMA = "evento_sistema", "Evento do sistema"
    AGENDADO = "agendado", "Agendado"
    INTERNO = "interno", "Interno"


class AgentInputPolicy(models.TextChoices):
    FIXA = "fixa", "Origem fixa"
    ESCOLHIDA_NA_EXECUCAO = "escolhida_na_execucao", "Escolhida na execucao"
    UPLOAD_NA_EXECUCAO = "upload_na_execucao", "Upload na execucao"
    SEM_ENTRADA = "sem_entrada", "Sem entrada documental"
    MULTIPLA = "multipla", "Multipla"


class AgentOutputPolicy(models.TextChoices):
    FIXA = "fixa", "Saida fixa"
    CONFIGURAVEL_NA_EXECUCAO = (
        "configuravel_na_execucao",
        "Configuravel na execucao",
    )


class AgentDefaultInputSourceType(models.TextChoices):
    GOOGLE_DRIVE_FOLDER = "google_drive_folder", "Google Drive - pasta"
    LOCAL_FOLDER = "local_folder", "Pasta local"
    LOCAL_FILE = "local_file", "Arquivo local fixo"
    UPLOAD_AT_EXECUTION = "upload_at_execution", "Arquivo informado na execucao"
    NONE = "none", "Sem origem documental"


class AgentDefaultOutputFormat(models.TextChoices):
    AI_DEFINED = "ai_defined", "Definida pela IA"
    LIVRE = "livre", "Definida pelo Prompt"
    JSON = "json", "JSON"
    XLSX = "xlsx", "Excel"
    CSV = "csv", "CSV"
    PDF = "pdf", "PDF"
    TXT = "txt", "TXT"


class AgentOutputDestination(models.TextChoices):
    INTERNAL_MEDIA = "internal_media", "Pasta interna do sistema"


class AgentDocumentExecutionMode(models.TextChoices):
    INDIVIDUAL = "individual", "Individual"
    GRUPO_UNICO = "grupo_unico", "Grupo unico"
    LOTE_POR_PASTA = "lote_por_pasta", "Lote por sub-pastas"


class AgentOutputAssemblyMode(models.TextChoices):
    UMA_POR_ENTRADA = "uma_por_entrada", "Uma saida por entrada"
    UMA_POR_GRUPO = "uma_por_grupo", "Uma saida por grupo"
    UMA_SAIDA_FINAL = "uma_saida_final", "Uma saida final"


class AgentOutputPackagingMode(models.TextChoices):
    ARQUIVO_UNICO = "arquivo_unico", "Arquivo unico"
    ZIP_SE_MULTIPLOS = "zip_se_multiplos", "ZIP se multiplos"
    SEMPRE_ZIP = "sempre_zip", "Sempre ZIP"


def default_allowed_input_extensions():
    return ["pdf", "txt", "csv", "png", "jpg", "jpeg", "xlsx"]


def default_concurrency_policy():
    return {"block_parallel_per_agent": True}


def default_prompt_parameters():
    return []


# Schema minimo esperado para concurrency_policy.
_CONCURRENCY_POLICY_REQUIRED_KEY = "block_parallel_per_agent"


def _validate_concurrency_policy(value):
    if not isinstance(value, dict):
        raise ValidationError(
            {"concurrency_policy": "concurrency_policy deve ser um objeto JSON."}
        )
    if _CONCURRENCY_POLICY_REQUIRED_KEY not in value:
        raise ValidationError(
            {
                "concurrency_policy": (
                    f"concurrency_policy deve conter a chave '{_CONCURRENCY_POLICY_REQUIRED_KEY}'."
                )
            }
        )
    if not isinstance(value[_CONCURRENCY_POLICY_REQUIRED_KEY], bool):
        raise ValidationError(
            {
                "concurrency_policy": (
                    f"'{_CONCURRENCY_POLICY_REQUIRED_KEY}' deve ser um booleano."
                )
            }
        )


def _validate_fields_schema(value):
    """Valida que runtime_fields_schema e builder_schema sao objetos JSON validos."""
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValidationError("O schema de campos deve ser um objeto JSON.")


class AgenteIA(SoftDeleteModel, UserStampedModel):
    nome = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    tipo = models.CharField(max_length=30, choices=AgentType.choices)
    categoria_operacional = models.CharField(
        max_length=40,
        choices=AgentOperationalCategory.choices,
        default=AgentOperationalCategory.LEITURA_DOCUMENTO,
    )
    visibilidade = models.CharField(
        max_length=20,
        choices=AgentVisibility.choices,
        default=AgentVisibility.USUARIO,
    )
    modo_acionamento = models.CharField(
        max_length=40,
        choices=AgentTriggerMode.choices,
        default=AgentTriggerMode.PORTAL,
    )
    objetivo = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=AgentStatus.choices,
        default=AgentStatus.INATIVO,
    )
    prompt_base = models.TextField()
    prompt_version = models.CharField(max_length=30, default="v1")
    modelo_preferencial = models.CharField(max_length=120, blank=True)
    parametros_execucao = models.JSONField(default=dict, blank=True)
    ai_provider_integration = models.ForeignKey(
        AIProviderIntegration,
        on_delete=models.PROTECT,
        related_name="agentes",
    )
    permite_execucao_manual = models.BooleanField(default=True)
    permite_clonagem = models.BooleanField(default=True)
    clonado_de = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clones",
    )

    class Meta:
        verbose_name = "Agente IA"
        verbose_name_plural = "Agentes IA"
        indexes = [
            models.Index(fields=["status", "tipo"]),
            models.Index(fields=["status", "visibilidade"]),
            models.Index(fields=["categoria_operacional"]),
            models.Index(fields=["modo_acionamento"]),
            models.Index(fields=["clonado_de"]),
            models.Index(
                fields=["ai_provider_integration"],
                name="agentes_ia_ai_provider_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.ai_provider_integration_id
            and self.status == AgentStatus.ATIVO
            and self.ai_provider_integration.status != IntegrationStatus.ATIVA
        ):
            raise ValidationError(
                {
                    "ai_provider_integration": (
                        "A integracao de IA precisa estar ativa para um agente ativo."
                    )
                }
            )

    def __str__(self):
        return self.nome

    @property
    def openai_integration(self):
        return self.ai_provider_integration

    @openai_integration.setter
    def openai_integration(self, value):
        self.ai_provider_integration = value


class AgenteConfiguracaoOperacional(UserStampedModel):
    agente = models.OneToOneField(
        AgenteIA,
        on_delete=models.CASCADE,
        related_name="configuracao_operacional",
    )
    input_policy = models.CharField(
        max_length=40,
        choices=AgentInputPolicy.choices,
        default=AgentInputPolicy.ESCOLHIDA_NA_EXECUCAO,
    )
    default_input_source_type = models.CharField(
        max_length=40,
        choices=AgentDefaultInputSourceType.choices,
        default=AgentDefaultInputSourceType.GOOGLE_DRIVE_FOLDER,
    )
    default_folder_source = models.ForeignKey(
        "integracoes.GoogleDriveFolderSource",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="agentes_configuracao_padrao",
    )
    default_local_storage_integration = models.ForeignKey(
        "integracoes.LocalStorageIntegration",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="agentes_configuracao_padrao",
    )
    default_local_relative_input_path = models.CharField(max_length=500, blank=True)
    # Lista de {id, nome} do caminho completo de subpastas do Google Drive selecionado.
    # Ex: [{"id": "drive_id_filho", "nome": "FILHO"}, {"id": "drive_id_sub", "nome": "SUB-FILHO"}]
    default_gdrive_subfolder_path = models.JSONField(default=list, blank=True)
    allowed_input_extensions = models.JSONField(
        default=default_allowed_input_extensions,
        blank=True,
    )
    allow_runtime_input_choice = models.BooleanField(default=True)
    allow_runtime_file_upload = models.BooleanField(default=True)
    output_policy = models.CharField(
        max_length=40,
        choices=AgentOutputPolicy.choices,
        default=AgentOutputPolicy.CONFIGURAVEL_NA_EXECUCAO,
    )
    default_output_format = models.CharField(
        max_length=20,
        choices=AgentDefaultOutputFormat.choices,
        default=AgentDefaultOutputFormat.JSON,
    )
    default_output_destination = models.CharField(
        max_length=40,
        choices=AgentOutputDestination.choices,
        default=AgentOutputDestination.INTERNAL_MEDIA,
    )
    allow_runtime_output_override = models.BooleanField(default=True)
    runtime_fields_schema = models.JSONField(default=dict, blank=True)
    builder_schema = models.JSONField(default=dict, blank=True)
    document_execution_mode = models.CharField(
        max_length=30,
        choices=AgentDocumentExecutionMode.choices,
        default=AgentDocumentExecutionMode.INDIVIDUAL,
    )
    output_assembly_mode = models.CharField(
        max_length=30,
        choices=AgentOutputAssemblyMode.choices,
        default=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
    )
    output_packaging_mode = models.CharField(
        max_length=30,
        choices=AgentOutputPackagingMode.choices,
        default=AgentOutputPackagingMode.ZIP_SE_MULTIPLOS,
    )
    prompt_parameters = models.JSONField(default=default_prompt_parameters, blank=True)
    concurrency_policy = models.JSONField(default=default_concurrency_policy, blank=True)
    # U3: limite de tentativas de execucao por documento. 0 = sem limite.
    max_tentativas = models.PositiveSmallIntegerField(
        default=3,
        help_text="Numero maximo de tentativas de execucao por documento. 0 = sem limite.",
    )

    class Meta:
        verbose_name = "Configuracao operacional do agente"
        verbose_name_plural = "Configuracoes operacionais dos agentes"
        indexes = [
            models.Index(fields=["input_policy"]),
            models.Index(fields=["output_policy"]),
            models.Index(
                fields=["default_input_source_type", "default_output_format"],
                name="agentes_conf_src_out_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if not self.allowed_input_extensions:
            self.allowed_input_extensions = default_allowed_input_extensions()
        self.allowed_input_extensions = [
            str(extension).lower().lstrip(".")
            for extension in self.allowed_input_extensions
        ]

        # M4: valida schema de concurrency_policy
        _validate_concurrency_policy(self.concurrency_policy)

        # M5: valida schemas de campos de runtime e builder
        try:
            _validate_fields_schema(self.runtime_fields_schema)
        except ValidationError as exc:
            raise ValidationError({"runtime_fields_schema": exc.message}) from exc
        try:
            _validate_fields_schema(self.builder_schema)
        except ValidationError as exc:
            raise ValidationError({"builder_schema": exc.message}) from exc

        if (
            self.input_policy == AgentInputPolicy.FIXA
            and self.default_input_source_type == AgentDefaultInputSourceType.NONE
        ):
            raise ValidationError(
                {
                    "default_input_source_type": (
                        "Agente com entrada fixa precisa de uma origem padrao."
                    )
                }
            )

        if (
            self.default_input_source_type
            == AgentDefaultInputSourceType.GOOGLE_DRIVE_FOLDER
            and self.input_policy == AgentInputPolicy.FIXA
            and not self.default_folder_source_id
        ):
            raise ValidationError(
                {"default_folder_source": "Selecione a pasta padrao do Google Drive."}
            )

        if self.default_input_source_type in {
            AgentDefaultInputSourceType.LOCAL_FOLDER,
            AgentDefaultInputSourceType.LOCAL_FILE,
        } and self.input_policy == AgentInputPolicy.FIXA:
            if not self.default_local_storage_integration_id:
                raise ValidationError(
                    {
                        "default_local_storage_integration": (
                            "Selecione a pasta local padrao."
                        )
                    }
                )
            # Caminho relativo vazio = raiz da pasta autorizada (comportamento válido)

        if (
            self.output_assembly_mode == AgentOutputAssemblyMode.UMA_POR_ENTRADA
            and self.document_execution_mode == AgentDocumentExecutionMode.GRUPO_UNICO
        ):
            raise ValidationError(
                {
                    "output_assembly_mode": (
                        "Saida por entrada nao e compativel com execucao em grupo unico."
                    )
                }
            )

        if (
            self.output_assembly_mode == AgentOutputAssemblyMode.UMA_SAIDA_FINAL
            and self.document_execution_mode == AgentDocumentExecutionMode.INDIVIDUAL
        ):
            raise ValidationError(
                {
                    "document_execution_mode": (
                        "Uma saida final consolidada exige execucao em grupo unico ou lote por pasta."
                    )
                }
            )

        if (
            self.output_assembly_mode == AgentOutputAssemblyMode.UMA_POR_ENTRADA
            and self.output_packaging_mode == AgentOutputPackagingMode.ARQUIVO_UNICO
        ):
            raise ValidationError(
                {
                    "output_packaging_mode": (
                        "Use ZIP se multiplos ou Sempre ZIP para saida por entrada."
                    )
                }
            )

    def __str__(self):
        return f"Configuracao operacional - {self.agente}"


class VersaoPrompt(TimestampedModel):
    """
    Historico de versoes do prompt de um agente.
    Uma nova entrada e criada automaticamente a cada alteracao de prompt_base.
    """

    agente = models.ForeignKey(
        AgenteIA,
        on_delete=models.CASCADE,
        related_name="versoes_prompt",
    )
    versao = models.CharField(max_length=30)
    prompt = models.TextField()
    criado_por = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="versoes_prompt_criadas",
    )
    nota = models.TextField(blank=True)

    class Meta:
        verbose_name = "Versao de prompt"
        verbose_name_plural = "Versoes de prompt"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["agente", "versao"],
                name="unique_versao_prompt_por_agente",
            )
        ]
        indexes = [
            models.Index(fields=["agente"]),
        ]

    def __str__(self):
        return f"{self.agente.nome} — {self.versao}"


@receiver(post_save, sender=AgenteIA)
def registrar_versao_prompt(sender, instance, created, **kwargs):
    """Cria VersaoPrompt sempre que prompt_base for salvo pela primeira vez ou alterado."""
    if not instance.prompt_base:
        return

    ultima = VersaoPrompt.objects.filter(agente=instance).order_by("-created_at").first()
    if ultima and ultima.prompt == instance.prompt_base:
        return

    versao_numero = VersaoPrompt.objects.filter(agente=instance).count() + 1
    VersaoPrompt.objects.create(
        agente=instance,
        versao=f"v{versao_numero}",
        prompt=instance.prompt_base,
        criado_por=instance.updated_by or instance.created_by,
    )
