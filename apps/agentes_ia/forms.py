import json

from django import forms

from apps.agentes_ia.models import (
    AgenteConfiguracaoOperacional,
    AgentDefaultInputSourceType,
    AgentDefaultOutputFormat,
    AgentInputPolicy,
    AgentDocumentExecutionMode,
    AgentOutputAssemblyMode,
    AgentOutputDestination,
    AgentOutputPackagingMode,
    AgentStatus,
)
from apps.agentes_ia.services import (
    atualizar_agente_portal,
    criar_agente_portal,
    normalizar_parametros_prompt,
)
from apps.integracoes.models import (
    AIProviderIntegration,
    GoogleDriveFolderSource,
    IntegrationStatus,
    LocalStorageIntegration,
)


class AgentePortalCreateForm(forms.Form):
    nome = forms.CharField(label="Nome do agente", max_length=120)
    status = forms.ChoiceField(
        label="Status",
        choices=(
            (AgentStatus.ATIVO, "Ativo"),
            (AgentStatus.INATIVO, "Inativo"),
        ),
        initial=AgentStatus.INATIVO,
    )
    prompt_base = forms.CharField(
        label="Prompt base",
        widget=forms.Textarea(attrs={"rows": 8}),
    )
    prompt_parameters = forms.CharField(
        required=False,
        widget=forms.HiddenInput,
    )
    ai_provider_integration = forms.ModelChoiceField(
        label="Integracao de IA",
        queryset=AIProviderIntegration.objects.none(),
    )
    modelo_preferencial = forms.CharField(
        label="Modelo preferencial",
        max_length=120,
        required=False,
    )
    _CHOICES_PADRAO = (
        (AgentDefaultInputSourceType.GOOGLE_DRIVE_FOLDER, "Google Drive - pasta"),
        (AgentDefaultInputSourceType.LOCAL_FOLDER, "Pasta local"),
        (AgentDefaultInputSourceType.NONE, "Sem origem documental"),
    )
    _CHOICES_COM_LOCAL_FILE = _CHOICES_PADRAO + (
        (AgentDefaultInputSourceType.LOCAL_FILE, "Arquivo local fixo (legado)"),
    )

    default_input_source_type = forms.ChoiceField(
        label="Origem padrao",
        choices=_CHOICES_PADRAO,
        initial=AgentDefaultInputSourceType.GOOGLE_DRIVE_FOLDER,
    )

    default_folder_source = forms.ModelChoiceField(
        label="Pasta padrao do Google Drive",
        queryset=GoogleDriveFolderSource.objects.none(),
        required=False,
    )
    default_local_storage_integration = forms.ModelChoiceField(
        label="Pasta local padrao",
        queryset=LocalStorageIntegration.objects.none(),
        required=False,
    )
    default_local_relative_input_path = forms.CharField(
        label="Caminho relativo padrao",
        max_length=500,
        required=False,
    )
    permitir_upload_na_execucao = forms.BooleanField(
        label="Permitir documento na execucao",
        required=False,
        help_text=(
            "Use quando o agente normalmente nao possui origem fixa, mas o usuario "
            "pode anexar um documento no momento de executar."
        ),
    )
    default_output_format = forms.ChoiceField(
        label="Formato padrao de saida",
        choices=AgentDefaultOutputFormat.choices,
        initial=AgentDefaultOutputFormat.JSON,
    )
    document_execution_mode = forms.ChoiceField(
        label="Modo de entrada",
        choices=AgentDocumentExecutionMode.choices,
        initial=AgentDocumentExecutionMode.INDIVIDUAL,
    )
    output_assembly_mode = forms.ChoiceField(
        label="Modo de saida",
        choices=AgentOutputAssemblyMode.choices,
        initial=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
    )
    output_packaging_mode = forms.ChoiceField(
        label="Empacotamento da saida",
        choices=AgentOutputPackagingMode.choices,
        initial=AgentOutputPackagingMode.ZIP_SE_MULTIPLOS,
    )
    max_tentativas = forms.IntegerField(
        label="Maximo de tentativas por documento",
        min_value=0,
        initial=3,
        required=False,
        help_text=(
            "Numero maximo de execucoes por documento. Ao reprocessar, documentos "
            "que ja atingiram o limite sao ignorados. Use 0 para sem limite."
        ),
    )

    def __init__(self, *args, **kwargs):
        self.actor = kwargs.pop("actor", None)
        self.instance = kwargs.pop("instance", None)
        self.configuracao_instance = kwargs.pop("configuracao_instance", None)
        super().__init__(*args, **kwargs)
        self.fields["ai_provider_integration"].queryset = (
            AIProviderIntegration.objects.filter(status=IntegrationStatus.ATIVA)
            .order_by("nome")
        )
        self.fields["default_folder_source"].queryset = (
            GoogleDriveFolderSource.objects.select_related("google_drive_integration")
            .filter(
                status=IntegrationStatus.ATIVA,
                google_drive_integration__status=IntegrationStatus.ATIVA,
            )
            .order_by("nome")
        )
        self.fields["default_local_storage_integration"].queryset = (
            LocalStorageIntegration.objects.filter(status=IntegrationStatus.ATIVA)
            .order_by("nome")
        )
        # Preserva LOCAL_FILE nas choices se o agente já usa esse tipo (legado)
        if self.instance is not None:
            try:
                config = self.instance.configuracao_operacional
                if (
                    getattr(config, "input_policy", None) == "local_file"
                    or getattr(config, "default_input_source_type", None)
                    == AgentDefaultInputSourceType.LOCAL_FILE
                ):
                    self.fields["default_input_source_type"].choices = (
                        self._CHOICES_COM_LOCAL_FILE
                    )
            except Exception:
                pass

        if self.instance is not None and not self.is_bound:
            self._apply_initial_from_instance()

    def _apply_initial_from_instance(self):
        configuracao = self.configuracao_instance
        if configuracao is None:
            try:
                configuracao = self.instance.configuracao_operacional
            except AgenteConfiguracaoOperacional.DoesNotExist:
                configuracao = None

        initial_data = {
            "nome": self.instance.nome,
            "status": self.instance.status,
            "prompt_base": self.instance.prompt_base,
            "ai_provider_integration": self.instance.ai_provider_integration,
            "modelo_preferencial": self.instance.modelo_preferencial,
        }

        if configuracao is not None:
            permitir_upload_na_execucao = (
                configuracao.input_policy == AgentInputPolicy.UPLOAD_NA_EXECUCAO
                or configuracao.allow_runtime_file_upload
            )
            initial_data.update(
                {
                    "default_input_source_type": (
                        configuracao.default_input_source_type
                    ),
                    "default_folder_source": configuracao.default_folder_source,
                    "default_local_storage_integration": (
                        configuracao.default_local_storage_integration
                    ),
                    "default_local_relative_input_path": (
                        configuracao.default_local_relative_input_path
                    ),
                    "permitir_upload_na_execucao": permitir_upload_na_execucao,
                    "default_output_format": configuracao.default_output_format,
                    "document_execution_mode": (
                        configuracao.document_execution_mode
                    ),
                    "output_assembly_mode": configuracao.output_assembly_mode,
                    "output_packaging_mode": configuracao.output_packaging_mode,
                    "max_tentativas": configuracao.max_tentativas,
                    "prompt_parameters": json.dumps(
                        configuracao.prompt_parameters or [],
                        ensure_ascii=False,
                    ),
                }
            )

        self.initial.update(initial_data)

    def clean_max_tentativas(self):
        value = self.cleaned_data.get("max_tentativas")
        if value is None:
            return 3
        return value

    def clean_prompt_parameters(self):
        raw_value = self.cleaned_data.get("prompt_parameters") or "[]"
        try:
            parsed_value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise forms.ValidationError(
                "Os parametros do prompt nao vieram em formato valido."
            ) from exc

        return normalizar_parametros_prompt(parsed_value)

    def clean(self):
        cleaned_data = super().clean()
        source_type = cleaned_data.get("default_input_source_type")

        if source_type == AgentDefaultInputSourceType.GOOGLE_DRIVE_FOLDER:
            if not cleaned_data.get("default_folder_source"):
                self.add_error(
                    "default_folder_source",
                    "Selecione a pasta padrao do Google Drive para este agente.",
                )
        elif source_type in {
            AgentDefaultInputSourceType.LOCAL_FOLDER,
            AgentDefaultInputSourceType.LOCAL_FILE,
        }:
            if not cleaned_data.get("default_local_storage_integration"):
                self.add_error(
                    "default_local_storage_integration",
                    "Selecione a pasta local padrao para este agente.",
                )
            # Caminho relativo vazio = raiz da pasta (comportamento válido)

        document_execution_mode = cleaned_data.get("document_execution_mode")
        output_assembly_mode = cleaned_data.get("output_assembly_mode")
        output_packaging_mode = cleaned_data.get("output_packaging_mode")

        if (
            output_assembly_mode == AgentOutputAssemblyMode.UMA_POR_ENTRADA
            and document_execution_mode == AgentDocumentExecutionMode.GRUPO_UNICO
        ):
            self.add_error(
                "output_assembly_mode",
                "Saida por entrada nao combina com execucao em grupo unico.",
            )

        if (
            output_assembly_mode == AgentOutputAssemblyMode.UMA_SAIDA_FINAL
            and document_execution_mode == AgentDocumentExecutionMode.INDIVIDUAL
        ):
            self.add_error(
                "document_execution_mode",
                "Uma saida final exige grupo unico ou lote por pasta.",
            )

        if (
            output_assembly_mode == AgentOutputAssemblyMode.UMA_POR_ENTRADA
            and output_packaging_mode == AgentOutputPackagingMode.ARQUIVO_UNICO
        ):
            self.add_error(
                "output_packaging_mode",
                "Para saida por entrada, use ZIP se multiplos ou Sempre ZIP.",
            )

        return cleaned_data

    def save(self):
        if not self.is_valid():
            raise ValueError("Use save() apenas com o formulario valido.")
        if self.actor is None:
            raise ValueError("O ator autenticado e obrigatorio para salvar o agente.")

        service_kwargs = {
            "actor": self.actor,
            "nome": self.cleaned_data["nome"],
            "status": self.cleaned_data["status"],
            "prompt_base": self.cleaned_data["prompt_base"],
            "ai_provider_integration": self.cleaned_data["ai_provider_integration"],
            "modelo_preferencial": self.cleaned_data["modelo_preferencial"],
            "default_input_source_type": self.cleaned_data["default_input_source_type"],
            "default_folder_source": self.cleaned_data.get("default_folder_source"),
            "default_local_storage_integration": self.cleaned_data.get(
                "default_local_storage_integration"
            ),
            "default_local_relative_input_path": self.cleaned_data.get(
                "default_local_relative_input_path", ""
            ),
            "permitir_upload_na_execucao": self.cleaned_data.get(
                "permitir_upload_na_execucao", False
            ),
            "default_output_format": self.cleaned_data["default_output_format"],
            "default_output_destination": AgentOutputDestination.INTERNAL_MEDIA,
            "document_execution_mode": self.cleaned_data["document_execution_mode"],
            "output_assembly_mode": self.cleaned_data["output_assembly_mode"],
            "output_packaging_mode": self.cleaned_data["output_packaging_mode"],
            "max_tentativas": self.cleaned_data["max_tentativas"],
            "prompt_parameters": self.cleaned_data["prompt_parameters"],
        }

        if self.instance is not None:
            return atualizar_agente_portal(agente=self.instance, **service_kwargs)

        return criar_agente_portal(**service_kwargs)
