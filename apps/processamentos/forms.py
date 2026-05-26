from django import forms

from apps.agentes_ia.models import (
    AgentDefaultInputSourceType,
    AgentInputPolicy,
    AgentOutputPolicy,
)
from apps.agentes_ia.services import obter_ou_criar_configuracao_operacional
from apps.integracoes.models import (
    GoogleDriveFolderSource,
    IntegrationStatus,
    LocalStorageIntegration,
)
from apps.processamentos.models import (
    ProcessingInputSourceType,
    ProcessingOutputFormat,
)


class AgenteExecucaoForm(forms.Form):
    OUTPUT_DESTINATION_INTERNAL = "internal_media"

    input_source_type = forms.ChoiceField(
        label="Origem do documento",
        choices=ProcessingInputSourceType.choices,
        required=False,
    )
    folder_source = forms.ModelChoiceField(
        label="Pasta do Google Drive",
        queryset=GoogleDriveFolderSource.objects.none(),
        required=False,
    )
    local_storage_integration = forms.ModelChoiceField(
        label="Storage local autorizado",
        queryset=LocalStorageIntegration.objects.none(),
        required=False,
    )
    local_relative_input_path = forms.CharField(
        label="Caminho relativo local",
        max_length=500,
        required=False,
    )
    arquivo_execucao_upload = forms.FileField(
        label="Arquivo PDF",
        required=False,
    )
    output_format = forms.ChoiceField(
        label="Formato de saida",
        choices=(
            (ProcessingOutputFormat.AI_DEFINED, "Definido pela IA"),
            (ProcessingOutputFormat.JSON, "JSON"),
            (ProcessingOutputFormat.XLSX, "Excel"),
            (ProcessingOutputFormat.CSV, "CSV"),
            (ProcessingOutputFormat.PDF, "PDF"),
            (ProcessingOutputFormat.TXT, "TXT"),
        ),
        initial=ProcessingOutputFormat.JSON,
        required=False,
    )
    output_destination = forms.ChoiceField(
        label="Local de salvamento da saida",
        choices=((OUTPUT_DESTINATION_INTERNAL, "Storage interno do sistema"),),
        initial=OUTPUT_DESTINATION_INTERNAL,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        self.agente = kwargs.pop("agente", None)
        super().__init__(*args, **kwargs)
        self.configuracao_operacional = (
            obter_ou_criar_configuracao_operacional(self.agente)
            if self.agente is not None
            else None
        )
        self.fields["folder_source"].queryset = (
            GoogleDriveFolderSource.objects.select_related("google_drive_integration")
            .filter(
                status=IntegrationStatus.ATIVA,
                google_drive_integration__status=IntegrationStatus.ATIVA,
            )
            .order_by("nome")
        )
        self._apply_agent_defaults()

    @property
    def runtime_fields_schema(self):
        if self.configuracao_operacional is None:
            return {}
        schema = dict(self.configuracao_operacional.runtime_fields_schema or {})
        schema.setdefault(
            "input_policy",
            self.configuracao_operacional.input_policy,
        )
        schema.setdefault(
            "output_policy",
            self.configuracao_operacional.output_policy,
        )
        schema.setdefault(
            "show_input_source_type",
            self.configuracao_operacional.allow_runtime_input_choice,
        )
        schema.setdefault(
            "show_file_upload",
            self.configuracao_operacional.allow_runtime_file_upload,
        )
        schema.setdefault(
            "show_output_format",
            self.configuracao_operacional.allow_runtime_output_override,
        )
        return schema

    def _apply_agent_defaults(self):
        configuracao = self.configuracao_operacional
        if configuracao is None:
            return

        if configuracao.default_input_source_type != AgentDefaultInputSourceType.NONE:
            self.fields["input_source_type"].initial = (
                configuracao.default_input_source_type
            )
        self.fields["folder_source"].initial = configuracao.default_folder_source
        self.fields["local_storage_integration"].initial = (
            configuracao.default_local_storage_integration
        )
        self.fields["local_relative_input_path"].initial = (
            configuracao.default_local_relative_input_path
        )
        self.fields["output_format"].initial = configuracao.default_output_format
        self.fields["local_storage_integration"].queryset = (
            LocalStorageIntegration.objects.filter(status=IntegrationStatus.ATIVA)
            .order_by("nome")
        )

    def clean_arquivo_execucao_upload(self):
        arquivo = self.cleaned_data.get("arquivo_execucao_upload")
        if arquivo:
            extension = arquivo.name.lower().rsplit(".", 1)[-1]
            allowed_extensions = (
                self.configuracao_operacional.allowed_input_extensions
                if self.configuracao_operacional is not None
                else ["pdf"]
            )
            if extension not in allowed_extensions:
                raise forms.ValidationError(
                    "Envie um arquivo com extensao permitida para este agente."
                )
        return arquivo

    def clean(self):
        cleaned_data = super().clean()
        configuracao = self.configuracao_operacional
        source_type = self._resolve_source_type(cleaned_data)
        cleaned_data["input_source_type"] = source_type
        cleaned_data["output_format"] = self._resolve_output_format(cleaned_data)

        if source_type == AgentDefaultInputSourceType.NONE:
            return cleaned_data

        if source_type == ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER:
            if not cleaned_data.get("folder_source") and not (
                configuracao and configuracao.default_folder_source_id
            ):
                self.add_error(
                    "folder_source",
                    "Selecione a pasta do Google Drive.",
                )
        elif source_type in {
            ProcessingInputSourceType.LOCAL_FOLDER,
            ProcessingInputSourceType.LOCAL_FILE,
        }:
            if not cleaned_data.get("local_storage_integration") and not (
                configuracao and configuracao.default_local_storage_integration_id
            ):
                self.add_error(
                    "local_storage_integration",
                    "Selecione o storage local autorizado.",
                )
            if not cleaned_data.get("local_relative_input_path") and not (
                configuracao and configuracao.default_local_relative_input_path
            ):
                self.add_error(
                    "local_relative_input_path",
                    "Informe o caminho relativo.",
                )
        elif source_type == ProcessingInputSourceType.UPLOAD_AT_EXECUTION:
            upload_required = (
                configuracao is None
                or configuracao.input_policy == AgentInputPolicy.UPLOAD_NA_EXECUCAO
                or configuracao.allow_runtime_file_upload
            )
            if upload_required and not cleaned_data.get("arquivo_execucao_upload"):
                self.add_error(
                    "arquivo_execucao_upload",
                    "Escolha um arquivo antes de executar este agente.",
                )
        else:
            self.add_error("input_source_type", "Origem documental invalida.")

        return cleaned_data

    def _resolve_source_type(self, cleaned_data):
        configuracao = self.configuracao_operacional
        if configuracao is None:
            return cleaned_data.get("input_source_type")

        if configuracao.input_policy == AgentInputPolicy.FIXA:
            return configuracao.default_input_source_type

        if configuracao.input_policy == AgentInputPolicy.UPLOAD_NA_EXECUCAO:
            return ProcessingInputSourceType.UPLOAD_AT_EXECUTION

        if configuracao.input_policy == AgentInputPolicy.SEM_ENTRADA:
            return AgentDefaultInputSourceType.NONE

        return (
            cleaned_data.get("input_source_type")
            or configuracao.default_input_source_type
        )

    def _resolve_output_format(self, cleaned_data):
        configuracao = self.configuracao_operacional
        if configuracao is None:
            return cleaned_data.get("output_format") or ProcessingOutputFormat.JSON

        if configuracao.output_policy == AgentOutputPolicy.FIXA:
            return configuracao.default_output_format

        return (
            cleaned_data.get("output_format")
            or configuracao.default_output_format
            or ProcessingOutputFormat.JSON
        )
