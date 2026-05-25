from secrets import token_hex

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.agentes_ia.services import calcular_disponibilidade_agente
from apps.agentes_ia.services import obter_ou_criar_configuracao_operacional
from apps.agentes_ia.services import renderizar_prompt_com_parametros
from apps.integracoes.services.ai_providers import AIProviderServiceError
from apps.integracoes.services.google_drive import GoogleDriveServiceError
from apps.integracoes.services.local_storage import LocalStorageServiceError
from apps.processamentos.models import (
    Processamento,
    ProcessingInputSourceType,
    ProcessingStatus,
)
from apps.processamentos.services.agent_execution import (
    ProcessamentoExecutionError,
    execute_processing,
)
from apps.processamentos.services.document_sources import DocumentSourcePreparationError
from apps.processamentos.services.error_handling import normalizar_erro_processamento


class OperationalExecutionError(Exception):
    pass


def criar_e_iniciar_processamento_para_agente(*, agente, actor, cleaned_data):
    disponibilidade = calcular_disponibilidade_agente(agente)
    if not disponibilidade.pode_executar:
        raise OperationalExecutionError(disponibilidade.motivo)

    processamento = _criar_processamento(
        agente=agente,
        actor=actor,
        cleaned_data=cleaned_data,
    )

    processamento.status = ProcessingStatus.EM_FILA
    processamento.mensagem_erro = ""
    processamento.mensagem_erro_tecnico = ""
    processamento.etapa_atual = "Aguardando inicio da execucao"
    processamento.documento_atual_nome = ""
    processamento.ultima_atividade_em = timezone.now()
    processamento.save(
        update_fields=[
            "status",
            "mensagem_erro",
            "mensagem_erro_tecnico",
            "etapa_atual",
            "documento_atual_nome",
            "ultima_atividade_em",
            "updated_at",
        ]
    )

    try:
        execute_processing(processamento, actor)
    except (
        AIProviderServiceError,
        GoogleDriveServiceError,
        LocalStorageServiceError,
        DocumentSourcePreparationError,
        ProcessamentoExecutionError,
    ) as exc:
        mensagem_operacional, mensagem_tecnica = normalizar_erro_processamento(exc)
        processamento.refresh_from_db()
        processamento.status = ProcessingStatus.CONCLUIDO_ERRO
        processamento.mensagem_erro = mensagem_operacional
        processamento.mensagem_erro_tecnico = mensagem_tecnica
        processamento.finalizado_em = timezone.now()
        processamento.etapa_atual = "Falha ao iniciar processamento"
        processamento.documento_atual_nome = ""
        processamento.ultima_atividade_em = timezone.now()
        processamento.save(
            update_fields=[
                "status",
                "mensagem_erro",
                "mensagem_erro_tecnico",
                "finalizado_em",
                "etapa_atual",
                "documento_atual_nome",
                "ultima_atividade_em",
                "updated_at",
            ]
        )
        raise OperationalExecutionError(mensagem_operacional) from exc

    processamento.refresh_from_db()
    return processamento


def _criar_processamento(*, agente, actor, cleaned_data):
    configuracao = obter_ou_criar_configuracao_operacional(agente)
    source_type = cleaned_data["input_source_type"]

    processamento = Processamento(
        codigo=_gerar_codigo_processamento(),
        status=ProcessingStatus.CRIADO,
        iniciado_por=actor,
        agente=agente,
        input_source_type=source_type,
        output_format=cleaned_data.get("output_format")
        or configuracao.default_output_format,
        arquivo_saida_formato=cleaned_data.get("output_format")
        or configuracao.default_output_format,
        prompt_snapshot=renderizar_prompt_com_parametros(
            agente.prompt_base,
            configuracao.prompt_parameters,
        ),
        document_execution_mode_snapshot=configuracao.document_execution_mode,
        output_assembly_mode_snapshot=configuracao.output_assembly_mode,
        output_packaging_mode_snapshot=configuracao.output_packaging_mode,
    )

    if source_type == ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER:
        processamento.folder_source = (
            cleaned_data.get("folder_source")
            or configuracao.default_folder_source
        )
    elif source_type in {
        ProcessingInputSourceType.LOCAL_FOLDER,
        ProcessingInputSourceType.LOCAL_FILE,
    }:
        processamento.local_storage_integration = cleaned_data[
            "local_storage_integration"
        ] or configuracao.default_local_storage_integration
        processamento.local_relative_input_path = cleaned_data[
            "local_relative_input_path"
        ] or configuracao.default_local_relative_input_path
    elif source_type == ProcessingInputSourceType.UPLOAD_AT_EXECUTION:
        upload_file = cleaned_data.get("arquivo_execucao_upload")
        if not upload_file:
            raise OperationalExecutionError(
                "Escolha um arquivo PDF antes de executar este agente."
            )
        processamento.arquivo_execucao_upload = upload_file

    try:
        with transaction.atomic():
            processamento.full_clean()
            processamento.save()
    except ValidationError as exc:
        raise OperationalExecutionError(_format_validation_error(exc)) from exc

    return processamento


def _gerar_codigo_processamento():
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    return f"PROC-{timestamp}-{token_hex(2).upper()}"


def _format_validation_error(exc):
    if hasattr(exc, "message_dict"):
        messages = []
        for field_messages in exc.message_dict.values():
            messages.extend(field_messages)
        return " ".join(messages)
    return " ".join(exc.messages)
