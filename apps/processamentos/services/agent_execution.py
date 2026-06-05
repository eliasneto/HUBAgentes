import json
from pathlib import Path
from collections.abc import Iterable

from django.apps import apps as django_apps
from django.core.files.base import ContentFile
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.agentes_ia.models import AgentDocumentExecutionMode, AgentOutputAssemblyMode
from apps.agentes_ia.services import (
    obter_ou_criar_configuracao_operacional,
    renderizar_prompt_com_parametros,
)
from apps.integracoes.services.ai_providers import (
    AIProviderServiceError,
    get_ai_provider_adapter,
)
from apps.integracoes.services.google_drive import GoogleDriveServiceError
from apps.integracoes.services.local_storage import LocalStorageServiceError
from apps.processamentos.models import (
    AIExecutionStatus,
    DocumentoSaidaProcessamento,
    DocumentStatus,
    ExecutionScopeType,
    OutputDocumentStatus,
    ProcessamentoExecucaoIA,
    ProcessingInputSourceType,
    ProcessingOutputFormat,
    ProcessingStatus,
)
from apps.processamentos.services.document_sources import (
    DocumentSourcePreparationError,
    load_document_bytes,
    prepare_documentos,
)
from apps.custos.selectors import (
    calcular_custo_com_cache,
    calcular_custo_processamento,
    obter_cotacao_dolar,
    obter_precificacao_modelo,
)
from apps.processamentos.services.error_handling import normalizar_erro_processamento
from apps.processamentos.services.output_packaging import (
    OutputPackagingError,
    publicar_saida_final,
)
from apps.processamentos.services.output_renderers import (
    OutputRendererError,
    render_output_file,
)


class ProcessamentoExecutionError(Exception):
    def __init__(self, message, *, technical_message=""):
        super().__init__(message)
        self.technical_message = technical_message


AI_DEFINED_OUTPUT_INSTRUCTION_MARKER = "FORMATO DE SAIDA DEFINIDO PELA IA"
SUPPORTED_AI_DEFINED_OUTPUT_FORMATS = {
    ProcessingOutputFormat.JSON,
    ProcessingOutputFormat.XLSX,
    ProcessingOutputFormat.CSV,
    ProcessingOutputFormat.PDF,
    ProcessingOutputFormat.TXT,
}
AI_DEFINED_OUTPUT_ALIASES = {
    "json": ProcessingOutputFormat.JSON,
    "xlsx": ProcessingOutputFormat.XLSX,
    "excel": ProcessingOutputFormat.XLSX,
    "xls": ProcessingOutputFormat.XLSX,
    "csv": ProcessingOutputFormat.CSV,
    "pdf": ProcessingOutputFormat.PDF,
    "txt": ProcessingOutputFormat.TXT,
    "texto": ProcessingOutputFormat.TXT,
}


def _registrar_atividade_processamento(
    processamento,
    *,
    etapa_atual,
    documento_atual_nome="",
):
    processamento.etapa_atual = etapa_atual
    processamento.documento_atual_nome = documento_atual_nome
    processamento.ultima_atividade_em = timezone.now()


def execute_processing(processamento, actor):
    integration = (
        processamento.ai_provider_integration_snapshot
        or processamento.agente.ai_provider_integration
    )
    if integration is None:
        raise ProcessamentoExecutionError(
            "O processamento nao possui uma integracao de IA valida vinculada."
        )

    model_name = processamento.modelo_snapshot or integration.default_model
    if not model_name:
        raise ProcessamentoExecutionError(
            "Defina um modelo na integracao de IA ou no agente antes de executar."
        )

    execution_params = _build_execution_params(processamento)
    if not processamento.ai_provider_integration_snapshot_id:
        processamento.ai_provider_integration_snapshot = integration
    if _deve_reconstruir_prompt_snapshot(processamento):
        processamento.prompt_snapshot = _build_prompt_snapshot(processamento)
    if not processamento.modelo_snapshot:
        processamento.modelo_snapshot = model_name

    prepare_documentos(processamento)
    documentos = list(_select_documentos(processamento))
    if processamento.input_source_type == ProcessingInputSourceType.NONE:
        return _execute_without_document(
            processamento=processamento,
            integration=integration,
            model_name=model_name,
            execution_params=execution_params,
            actor=actor,
        )
    if not documentos:
        raise ProcessamentoExecutionError(
            "Nenhum PDF pendente foi encontrado para execucao nesse processamento."
        )

    batch_started_at = timezone.now()
    _start_processing_batch(
        processamento=processamento,
        batch_started_at=batch_started_at,
        integration=integration,
        model_name=model_name,
    )

    if _usa_execucao_individual(processamento):
        batch_result = _execute_documents_individually(
            processamento=processamento,
            documentos=documentos,
            integration=integration,
            model_name=model_name,
            execution_params=execution_params,
            actor=actor,
        )
    elif _usa_execucao_por_pasta(processamento):
        batch_result = _execute_documents_by_folder(
            processamento=processamento,
            documentos=documentos,
            integration=integration,
            model_name=model_name,
            execution_params=execution_params,
            actor=actor,
        )
    else:
        batch_result = _execute_documents_as_group(
            processamento=processamento,
            documentos=documentos,
            integration=integration,
            model_name=model_name,
            execution_params=execution_params,
            actor=actor,
        )

    finished_at = timezone.now()
    telemetry = _aggregate_processing_telemetry(processamento)

    with transaction.atomic():
        processamento.total_documentos = processamento.documentos.count()
        processamento.total_processados = processamento.documentos.filter(
            status=DocumentStatus.PROCESSADO
        ).count()
        processamento.execucao_iniciada_em = batch_started_at
        processamento.execucao_finalizada_em = finished_at
        processamento.duracao_processamento_ms = max(
            int((finished_at - batch_started_at).total_seconds() * 1000),
            0,
        )
        processamento.input_tokens = telemetry["input_tokens"]
        processamento.processing_tokens = telemetry["processing_tokens"]
        processamento.output_tokens = telemetry["output_tokens"]
        processamento.total_tokens = telemetry["total_tokens"]
        processamento.custo_usd = telemetry.get("custo_usd")
        processamento.custo_brl = telemetry.get("custo_brl")
        processamento.finalizado_em = finished_at
        if batch_result["total_errors"]:
            processamento.status = ProcessingStatus.CONCLUIDO_ERRO
            processamento.mensagem_erro = (
                batch_result["last_error_message"]
                or "Uma ou mais execucoes terminaram com erro."
            )
            processamento.mensagem_erro_tecnico = (
                batch_result["last_technical_error_message"]
            )
        else:
            processamento.status = ProcessingStatus.CONCLUIDO_SUCESSO
            processamento.mensagem_erro = ""
            processamento.mensagem_erro_tecnico = ""
        _registrar_atividade_processamento(
            processamento,
            etapa_atual=(
                "Processamento concluido com erro"
                if batch_result["total_errors"]
                else "Processamento concluido com sucesso"
            ),
        )

        if batch_result["output_records"]:
            publicar_saida_final(
                processamento=processamento,
                output_records=batch_result["output_records"],
                output_packaging_mode=processamento.output_packaging_mode_snapshot,
                output_assembly_mode=processamento.output_assembly_mode_snapshot,
                source_document_count=len(documentos),
            )

        processamento.save()

    return {
        "documentos_processados": batch_result["total_success"],
        "documentos_com_erro": batch_result["total_errors"],
        "saidas_geradas": len(batch_result["output_records"]),
        "formato_saida": processamento.output_format,
        "batch_started_at": batch_started_at,
    }


def _start_processing_batch(*, processamento, batch_started_at, integration, model_name):
    with transaction.atomic():
        processamento.status = ProcessingStatus.EM_PROCESSAMENTO
        processamento.mensagem_erro = ""
        processamento.mensagem_erro_tecnico = ""
        processamento.finalizado_em = None
        processamento.total_documentos = processamento.documentos.count()
        processamento.execucao_iniciada_em = batch_started_at
        processamento.execucao_finalizada_em = None
        processamento.duracao_processamento_ms = None
        processamento.input_tokens = None
        processamento.processing_tokens = None
        processamento.output_tokens = None
        processamento.total_tokens = None
        processamento.arquivo_saida = None
        processamento.arquivo_saida_nome = ""
        processamento.arquivo_saida_liberado_em = None
        _registrar_atividade_processamento(
            processamento,
            etapa_atual="Preparando execucao do lote",
        )
        if not processamento.ai_provider_integration_snapshot_id:
            processamento.ai_provider_integration_snapshot = integration
        if not processamento.prompt_snapshot:
            processamento.prompt_snapshot = processamento.agente.prompt_base
        if not processamento.modelo_snapshot:
            processamento.modelo_snapshot = model_name
        processamento.save(
            update_fields=[
                "status",
                "mensagem_erro",
                "mensagem_erro_tecnico",
                "finalizado_em",
                "total_documentos",
                "execucao_iniciada_em",
                "execucao_finalizada_em",
                "duracao_processamento_ms",
                "input_tokens",
                "processing_tokens",
                "output_tokens",
                "total_tokens",
                "arquivo_saida",
                "arquivo_saida_nome",
                "arquivo_saida_liberado_em",
                "etapa_atual",
                "documento_atual_nome",
                "ultima_atividade_em",
                "ai_provider_integration_snapshot",
                "prompt_snapshot",
                "modelo_snapshot",
                "updated_at",
            ]
        )


def _usa_execucao_individual(processamento):
    return (
        processamento.document_execution_mode_snapshot
        == AgentDocumentExecutionMode.INDIVIDUAL
        or processamento.output_assembly_mode_snapshot
        == AgentOutputAssemblyMode.UMA_POR_ENTRADA
    )


def _usa_execucao_por_pasta(processamento):
    return (
        processamento.document_execution_mode_snapshot
        == AgentDocumentExecutionMode.LOTE_POR_PASTA
        and processamento.output_assembly_mode_snapshot
        == AgentOutputAssemblyMode.UMA_SAIDA_FINAL
    )


def _build_prompt_snapshot(processamento):
    configuracao = obter_ou_criar_configuracao_operacional(processamento.agente)
    prompt = renderizar_prompt_com_parametros(
        processamento.agente.prompt_base,
        configuracao.prompt_parameters,
    )
    if processamento.output_format == ProcessingOutputFormat.AI_DEFINED:
        prompt = _adicionar_instrucao_formato_definido_pela_ia(prompt)
    return prompt


def _deve_reconstruir_prompt_snapshot(processamento):
    if not processamento.prompt_snapshot:
        return True
    if processamento.prompt_snapshot == processamento.agente.prompt_base:
        return True
    return (
        processamento.output_format == ProcessingOutputFormat.AI_DEFINED
        and AI_DEFINED_OUTPUT_INSTRUCTION_MARKER not in processamento.prompt_snapshot
    )


def _adicionar_instrucao_formato_definido_pela_ia(prompt):
    if AI_DEFINED_OUTPUT_INSTRUCTION_MARKER in prompt:
        return prompt
    return (
        f"{prompt.rstrip()}\n\n"
        f"{AI_DEFINED_OUTPUT_INSTRUCTION_MARKER}:\n"
        "- Como o formato de saida esta configurado como definido pela IA, "
        "responda obrigatoriamente com um JSON valido contendo o campo "
        '"formato_saida".\n'
        '- O campo "formato_saida" deve ser exatamente um destes valores: '
        '"json", "xlsx", "csv", "pdf" ou "txt".\n'
        "- O conteudo a ser convertido pelo sistema deve ficar no campo "
        '"dados".\n'
        "- Nao use outros formatos e nao gere arquivo diretamente; o sistema "
        "validara o formato e criara o arquivo final."
    )


def _build_execution_params(processamento):
    execution_params = dict(processamento.agente.parametros_execucao or {})
    # O sistema sempre precisa de JSON para renderizar JSON/Excel/CSV/PDF/TXT
    # com rastreabilidade; provedores que suportam esse parametro tendem a
    # obedecer melhor do que apenas com instrucao no prompt.
    execution_params.setdefault("response_mime_type", "application/json")
    return execution_params


def _execute_documents_individually(
    *,
    processamento,
    documentos,
    integration,
    model_name,
    execution_params,
    actor,
):
    output_records = []
    total_success = 0
    total_errors = 0
    last_error_message = ""
    last_technical_error_message = ""
    _custo_cache: dict = {}  # cache de precificacao/cotacao para o batch

    for documento in documentos:
        execution_started_at = timezone.now()
        try:
            execution_result = _execute_document(
                processamento=processamento,
                documento=documento,
                integration=integration,
                model_name=model_name,
                execution_params=execution_params,
                actor=actor,
            )
        except (
            GoogleDriveServiceError,
            LocalStorageServiceError,
            DocumentSourcePreparationError,
            AIProviderServiceError,
            OutputRendererError,
            ProcessamentoExecutionError,
            OutputPackagingError,
        ) as exc:
            mensagem_operacional, mensagem_tecnica = normalizar_erro_processamento(exc)
            total_errors += 1
            last_error_message = mensagem_operacional
            if mensagem_tecnica:
                last_technical_error_message = mensagem_tecnica
            _mark_document_error(
                processamento=processamento,
                documento=documento,
                message=mensagem_operacional,
                integration=integration,
                model_name=model_name,
                execution_started_at=execution_started_at,
            )
            _log_execution_error(
                actor=actor,
                processamento=processamento,
                documento=documento,
                integration=integration,
                model_name=model_name,
                error_message=str(exc),
            )
            continue

        total_success += 1
        output_records.append(execution_result["output_record"])

    return {
        "output_records": output_records,
        "total_success": total_success,
        "total_errors": total_errors,
        "last_error_message": last_error_message,
        "last_technical_error_message": last_technical_error_message,
    }


def _execute_documents_as_group(
    *,
    processamento,
    documentos,
    integration,
    model_name,
    execution_params,
    actor,
):
    execution_started_at = timezone.now()
    try:
        group_result = _execute_document_group(
            processamento=processamento,
            documentos=documentos,
            integration=integration,
            model_name=model_name,
            execution_params=execution_params,
            actor=actor,
        )
    except (
        GoogleDriveServiceError,
        LocalStorageServiceError,
        DocumentSourcePreparationError,
        AIProviderServiceError,
        OutputRendererError,
        ProcessamentoExecutionError,
        OutputPackagingError,
    ) as exc:
        mensagem_operacional, mensagem_tecnica = normalizar_erro_processamento(exc)
        _mark_document_group_error(
            processamento=processamento,
            documentos=documentos,
            message=mensagem_operacional,
            integration=integration,
            model_name=model_name,
            execution_started_at=execution_started_at,
        )
        _log_group_execution_error(
            actor=actor,
            processamento=processamento,
            documentos=documentos,
            integration=integration,
            model_name=model_name,
            error_message=str(exc),
        )
        return {
            "output_records": [],
            "total_success": 0,
            "total_errors": len(documentos),
            "last_error_message": mensagem_operacional,
            "last_technical_error_message": mensagem_tecnica or "",
        }

    return {
        "output_records": [group_result["output_record"]],
        "total_success": len(documentos),
        "total_errors": 0,
        "last_error_message": "",
        "last_technical_error_message": "",
    }


def _execute_documents_by_folder(
    *,
    processamento,
    documentos,
    integration,
    model_name,
    execution_params,
    actor,
):


    output_records = []
    total_success = 0
    total_errors = 0
    last_error_message = ""
    last_technical_error_message = ""

    documentos_por_pasta = {}
    for documento in documentos:
        chave = documento.pasta_grupo or ""
        documentos_por_pasta.setdefault(chave, []).append(documento)

    if not documentos_por_pasta:
        return {
            "output_records": [],
            "total_success": 0,
            "total_errors": 0,
            "last_error_message": "",
            "last_technical_error_message": "",
        }

    for pasta_nome, grupo in sorted(documentos_por_pasta.items()):
        execution_started_at = timezone.now()
        try:
            group_result = _execute_document_group(
                processamento=processamento,
                documentos=grupo,
                integration=integration,
                model_name=model_name,
                execution_params=execution_params,
                actor=actor,
            )
        except (
            GoogleDriveServiceError,
            LocalStorageServiceError,
            DocumentSourcePreparationError,
            AIProviderServiceError,
            OutputRendererError,
            ProcessamentoExecutionError,
            OutputPackagingError,
        ) as exc:
            mensagem_operacional, mensagem_tecnica = normalizar_erro_processamento(exc)
            total_errors += len(grupo)
            last_error_message = mensagem_operacional
            if mensagem_tecnica:
                last_technical_error_message = mensagem_tecnica
            _mark_document_group_error(
                processamento=processamento,
                documentos=grupo,
                message=mensagem_operacional,
                integration=integration,
                model_name=model_name,
                execution_started_at=execution_started_at,
            )
            _log_group_execution_error(
                actor=actor,
                processamento=processamento,
                documentos=grupo,
                integration=integration,
                model_name=model_name,
                error_message=str(exc),
            )
            continue

        total_success += len(grupo)
        output_records.append(group_result["output_record"])

    return {
        "output_records": output_records,
        "total_success": total_success,
        "total_errors": total_errors,
        "last_error_message": last_error_message,
        "last_technical_error_message": last_technical_error_message,
    }


def _execute_without_document(
    *,
    processamento,
    integration,
    model_name,
    execution_params,
    actor,
):
    execution_started_at = timezone.now()

    with transaction.atomic():
        processamento.status = ProcessingStatus.EM_PROCESSAMENTO
        processamento.mensagem_erro = ""
        processamento.mensagem_erro_tecnico = ""
        processamento.finalizado_em = None
        processamento.total_documentos = 0
        processamento.total_processados = 0
        processamento.execucao_iniciada_em = execution_started_at
        processamento.execucao_finalizada_em = None
        processamento.duracao_processamento_ms = None
        _registrar_atividade_processamento(
            processamento,
            etapa_atual="Executando agente sem documento",
        )
        if not processamento.ai_provider_integration_snapshot_id:
            processamento.ai_provider_integration_snapshot = integration
        if not processamento.prompt_snapshot:
            processamento.prompt_snapshot = processamento.agente.prompt_base
        if not processamento.modelo_snapshot:
            processamento.modelo_snapshot = model_name
        processamento.save(
            update_fields=[
                "status",
                "mensagem_erro",
                "mensagem_erro_tecnico",
                "finalizado_em",
                "total_documentos",
                "total_processados",
                "execucao_iniciada_em",
                "execucao_finalizada_em",
                "duracao_processamento_ms",
                "etapa_atual",
                "documento_atual_nome",
                "ultima_atividade_em",
                "ai_provider_integration_snapshot",
                "prompt_snapshot",
                "modelo_snapshot",
                "updated_at",
            ]
        )

    adapter = get_ai_provider_adapter(integration)
    execution_result = adapter.execute_prompt_without_document(
        prompt=processamento.prompt_snapshot or processamento.agente.prompt_base,
        execution_params=execution_params,
        model_name=model_name,
    )
    execution_finished_at = timezone.now()
    telemetry = _build_execution_telemetry(
        execution_result.usage_metadata,
        execution_started_at=execution_started_at,
        execution_finished_at=execution_finished_at,
    )
    parsed_output = _parse_structured_output(
        execution_result.output_text,
        requested_output_format=processamento.output_format,
    )
    output_filename, output_bytes, output_format, render_payload = _render_output_file(
        parsed_output,
        processamento.output_format,
        f"{processamento.codigo}_resultado.{processamento.output_format}",
    )

    custo_usd_exec, custo_brl_exec = calcular_custo_processamento(
        nome_modelo=model_name,
        input_tokens=telemetry["input_tokens"],
        output_tokens=telemetry["output_tokens"],
        processing_tokens=telemetry["processing_tokens"],
    )

    with transaction.atomic():
        execution_record = ProcessamentoExecucaoIA.objects.create(
            processamento=processamento,
            documento=None,
            ai_provider_integration=integration,
            tentativa_numero=_next_execution_attempt_number(processamento),
            status=AIExecutionStatus.SUCESSO,
            modelo_utilizado=model_name,
            execucao_iniciada_em=execution_started_at,
            execucao_finalizada_em=execution_finished_at,
            duracao_ms=telemetry["duracao_processamento_ms"],
            input_tokens=telemetry["input_tokens"],
            processing_tokens=telemetry["processing_tokens"],
            output_tokens=telemetry["output_tokens"],
            total_tokens=telemetry["total_tokens"],
            custo_usd=custo_usd_exec,
            custo_brl=custo_brl_exec,
            usage_metadata=execution_result.usage_metadata or {},
            response_summary=execution_result.summary,
            scope_type=ExecutionScopeType.SEM_DOCUMENTO,
        )

        processamento.arquivo_saida.save(
            output_filename,
            ContentFile(output_bytes),
            save=False,
        )
        processamento.arquivo_saida_nome = output_filename
        processamento.arquivo_saida_formato = output_format
        processamento.arquivo_saida_liberado_em = timezone.now()
        processamento.execucao_finalizada_em = execution_finished_at
        processamento.duracao_processamento_ms = telemetry["duracao_processamento_ms"]
        processamento.input_tokens = telemetry["input_tokens"]
        processamento.processing_tokens = telemetry["processing_tokens"]
        processamento.output_tokens = telemetry["output_tokens"]
        processamento.total_tokens = telemetry["total_tokens"]
        processamento.custo_usd = custo_usd_exec
        processamento.custo_brl = custo_brl_exec
        processamento.total_processados = 0
        processamento.status = ProcessingStatus.CONCLUIDO_SUCESSO
        processamento.mensagem_erro = ""
        processamento.mensagem_erro_tecnico = ""
        processamento.finalizado_em = execution_finished_at
        _registrar_atividade_processamento(
            processamento,
            etapa_atual="Processamento concluido com sucesso",
        )
        processamento.save()

    _log_execution_without_document_event(
        actor=actor,
        processamento=processamento,
        integration=integration,
        model_name=model_name,
        execution_result=execution_result,
        parsed_output=parsed_output,
        render_payload=render_payload,
        telemetry=telemetry,
        execution_record=execution_record,
    )

    return {
        "documentos_processados": 0,
        "documentos_com_erro": 0,
        "saidas_geradas": 1,
        "formato_saida": output_format,
        "batch_started_at": execution_started_at,
    }


def _execute_document(
    *,
    processamento,
    documento,
    integration,
    model_name,
    execution_params,
    actor,
):
    execution_started_at = timezone.now()
    tentativa_numero = _next_execution_attempt_number(processamento)

    with transaction.atomic():
        _registrar_atividade_processamento(
            processamento,
            etapa_atual="Lendo documento atual",
            documento_atual_nome=documento.nome_arquivo,
        )
        processamento.execucao_iniciada_em = execution_started_at
        processamento.execucao_finalizada_em = None
        processamento.duracao_processamento_ms = None
        processamento.save(
            update_fields=[
                "execucao_iniciada_em",
                "execucao_finalizada_em",
                "duracao_processamento_ms",
                "etapa_atual",
                "documento_atual_nome",
                "ultima_atividade_em",
                "updated_at",
            ]
        )
        documento.status = DocumentStatus.EM_PROCESSAMENTO
        documento.mensagem_erro = ""
        documento.save(update_fields=["status", "mensagem_erro", "updated_at"])

    document_bytes = load_document_bytes(processamento, documento)
    adapter = get_ai_provider_adapter(integration)
    execution_result = adapter.execute_prompt_with_document(
        prompt=processamento.prompt_snapshot or processamento.agente.prompt_base,
        document_bytes=document_bytes,
        document_mime_type=documento.mime_type or "application/pdf",
        document_name=documento.nome_arquivo,
        execution_params=execution_params,
        model_name=model_name,
    )
    execution_finished_at = timezone.now()
    telemetry = _build_execution_telemetry(
        execution_result.usage_metadata,
        execution_started_at=execution_started_at,
        execution_finished_at=execution_finished_at,
    )
    parsed_output = _parse_structured_output(
        execution_result.output_text,
        requested_output_format=processamento.output_format,
    )
    output_filename, output_bytes, output_format, render_payload = _render_output_file(
        parsed_output,
        processamento.output_format,
        _build_output_basename(processamento, documento, processamento.output_format),
    )

    custo_usd_exec, custo_brl_exec = calcular_custo_com_cache(
        nome_modelo=model_name,
        input_tokens=telemetry["input_tokens"],
        output_tokens=telemetry["output_tokens"],
        processing_tokens=telemetry["processing_tokens"],
        _cache=_custo_cache,
    )

    with transaction.atomic():
        execution_record = ProcessamentoExecucaoIA.objects.create(
            processamento=processamento,
            documento=documento,
            ai_provider_integration=integration,
            tentativa_numero=tentativa_numero,
            status=AIExecutionStatus.SUCESSO,
            modelo_utilizado=model_name,
            execucao_iniciada_em=execution_started_at,
            execucao_finalizada_em=execution_finished_at,
            duracao_ms=telemetry["duracao_processamento_ms"],
            input_tokens=telemetry["input_tokens"],
            processing_tokens=telemetry["processing_tokens"],
            output_tokens=telemetry["output_tokens"],
            total_tokens=telemetry["total_tokens"],
            custo_usd=custo_usd_exec,
            custo_brl=custo_brl_exec,
            usage_metadata=execution_result.usage_metadata or {},
            response_summary=execution_result.summary,
            scope_type=ExecutionScopeType.INDIVIDUAL,
        )
        execution_record.documentos_entrada.set([documento])

        output_record = DocumentoSaidaProcessamento(
            processamento=processamento,
            documento=documento,
            execucao_ia=execution_record,
            formato=output_format,
            status=OutputDocumentStatus.GERADO,
            scope_type=ExecutionScopeType.INDIVIDUAL,
        )
        output_record.arquivo.save(output_filename, ContentFile(output_bytes), save=False)
        output_record.save()
        output_record.documentos_entrada.set([documento])

        documento.status = DocumentStatus.PROCESSADO
        documento.mensagem_erro = ""
        documento.processado_em = timezone.now()
        documento.save(
            update_fields=["status", "mensagem_erro", "processado_em", "updated_at"]
        )

        processamento.execucao_iniciada_em = execution_started_at
        processamento.execucao_finalizada_em = execution_finished_at
        processamento.duracao_processamento_ms = telemetry["duracao_processamento_ms"]
        processamento.input_tokens = telemetry["input_tokens"]
        processamento.processing_tokens = telemetry["processing_tokens"]
        processamento.output_tokens = telemetry["output_tokens"]
        processamento.total_tokens = telemetry["total_tokens"]
        processamento.custo_usd = custo_usd_exec
        processamento.custo_brl = custo_brl_exec
        processamento.total_processados = processamento.documentos.filter(
            status=DocumentStatus.PROCESSADO
        ).count()
        _registrar_atividade_processamento(
            processamento,
            etapa_atual="Documento processado com sucesso",
            documento_atual_nome=documento.nome_arquivo,
        )
        processamento.save(
            update_fields=[
                "execucao_iniciada_em",
                "execucao_finalizada_em",
                "duracao_processamento_ms",
                "input_tokens",
                "processing_tokens",
                "output_tokens",
                "total_tokens",
                "custo_usd",
                "custo_brl",
                "total_processados",
                "etapa_atual",
                "documento_atual_nome",
                "ultima_atividade_em",
                "updated_at",
            ]
        )

    _log_execution_event(
        actor=actor,
        processamento=processamento,
        documento=documento,
        integration=integration,
        model_name=model_name,
        execution_result=execution_result,
        parsed_output=parsed_output,
        render_payload=render_payload,
        telemetry=telemetry,
        execution_record=execution_record,
        output_record=output_record,
    )
    return {
        "documento": documento,
        "execution_record": execution_record,
        "output_record": output_record,
    }


def _execute_document_group(
    *,
    processamento,
    documentos,
    integration,
    model_name,
    execution_params,
    actor,
):
    execution_started_at = timezone.now()
    tentativa_numero = _next_execution_attempt_number(processamento)

    with transaction.atomic():
        _registrar_atividade_processamento(
            processamento,
            etapa_atual="Lendo grupo de documentos",
            documento_atual_nome=f"{len(documentos)} documento(s)",
        )
        processamento.execucao_iniciada_em = execution_started_at
        processamento.execucao_finalizada_em = None
        processamento.duracao_processamento_ms = None
        processamento.save(
            update_fields=[
                "execucao_iniciada_em",
                "execucao_finalizada_em",
                "duracao_processamento_ms",
                "etapa_atual",
                "documento_atual_nome",
                "ultima_atividade_em",
                "updated_at",
            ]
        )
        for documento in documentos:
            documento.status = DocumentStatus.EM_PROCESSAMENTO
            documento.mensagem_erro = ""
            documento.save(update_fields=["status", "mensagem_erro", "updated_at"])

    documents_payload = []
    for documento in documentos:
        documents_payload.append(
            {
                "document_bytes": load_document_bytes(processamento, documento),
                "document_mime_type": documento.mime_type or "application/pdf",
                "document_name": documento.nome_arquivo,
            }
        )

    adapter = get_ai_provider_adapter(integration)
    execution_result = adapter.execute_prompt_with_documents(
        prompt=processamento.prompt_snapshot or processamento.agente.prompt_base,
        documents=documents_payload,
        execution_params=execution_params,
        model_name=model_name,
    )
    execution_finished_at = timezone.now()
    telemetry = _build_execution_telemetry(
        execution_result.usage_metadata,
        execution_started_at=execution_started_at,
        execution_finished_at=execution_finished_at,
    )
    parsed_output = _parse_structured_output(
        execution_result.output_text,
        requested_output_format=processamento.output_format,
    )
    output_filename, output_bytes, output_format, render_payload = _render_output_file(
        parsed_output,
        processamento.output_format,
        f"{processamento.codigo}_grupo.{processamento.output_format}",
    )

    custo_usd_exec, custo_brl_exec = calcular_custo_processamento(
        nome_modelo=model_name,
        input_tokens=telemetry["input_tokens"],
        output_tokens=telemetry["output_tokens"],
        processing_tokens=telemetry["processing_tokens"],
    )

    with transaction.atomic():
        execution_record = ProcessamentoExecucaoIA.objects.create(
            processamento=processamento,
            documento=None,
            ai_provider_integration=integration,
            tentativa_numero=tentativa_numero,
            status=AIExecutionStatus.SUCESSO,
            modelo_utilizado=model_name,
            execucao_iniciada_em=execution_started_at,
            execucao_finalizada_em=execution_finished_at,
            duracao_ms=telemetry["duracao_processamento_ms"],
            input_tokens=telemetry["input_tokens"],
            processing_tokens=telemetry["processing_tokens"],
            output_tokens=telemetry["output_tokens"],
            total_tokens=telemetry["total_tokens"],
            custo_usd=custo_usd_exec,
            custo_brl=custo_brl_exec,
            usage_metadata=execution_result.usage_metadata or {},
            response_summary=execution_result.summary,
            scope_type=ExecutionScopeType.GRUPO,
        )
        execution_record.documentos_entrada.set(documentos)

        output_record = DocumentoSaidaProcessamento(
            processamento=processamento,
            documento=None,
            execucao_ia=execution_record,
            formato=output_format,
            status=OutputDocumentStatus.GERADO,
            scope_type=ExecutionScopeType.GRUPO,
        )
        output_record.arquivo.save(output_filename, ContentFile(output_bytes), save=False)
        output_record.save()
        output_record.documentos_entrada.set(documentos)

        processed_at = timezone.now()
        for documento in documentos:
            documento.status = DocumentStatus.PROCESSADO
            documento.mensagem_erro = ""
            documento.processado_em = processed_at
            documento.save(
                update_fields=[
                    "status",
                    "mensagem_erro",
                    "processado_em",
                    "updated_at",
                ]
            )

        processamento.execucao_iniciada_em = execution_started_at
        processamento.execucao_finalizada_em = execution_finished_at
        processamento.duracao_processamento_ms = telemetry["duracao_processamento_ms"]
        processamento.total_processados = processamento.documentos.filter(
            status=DocumentStatus.PROCESSADO
        ).count()
        _registrar_atividade_processamento(
            processamento,
            etapa_atual="Grupo processado com sucesso",
            documento_atual_nome=f"{len(documentos)} documento(s)",
        )
        processamento.save(
            update_fields=[
                "execucao_iniciada_em",
                "execucao_finalizada_em",
                "duracao_processamento_ms",
                "total_processados",
                "etapa_atual",
                "documento_atual_nome",
                "ultima_atividade_em",
                "updated_at",
            ]
        )

    _log_group_execution_event(
        actor=actor,
        processamento=processamento,
        documentos=documentos,
        integration=integration,
        model_name=model_name,
        execution_result=execution_result,
        parsed_output=parsed_output,
        render_payload=render_payload,
        telemetry=telemetry,
        execution_record=execution_record,
        output_record=output_record,
    )
    return {
        "execution_record": execution_record,
        "output_record": output_record,
    }


def _select_documentos(processamento):
    return processamento.documentos.filter(status=DocumentStatus.PENDENTE).order_by(
        "created_at"
    )


def _aggregate_processing_telemetry(processamento):
    from decimal import Decimal
    execution_records = list(processamento.execucoes_ia.all())

    custo_usd = None
    custo_brl = None
    for execucao in execution_records:
        if execucao.custo_usd is not None:
            custo_usd = (custo_usd or Decimal("0")) + execucao.custo_usd
        if execucao.custo_brl is not None:
            custo_brl = (custo_brl or Decimal("0")) + execucao.custo_brl

    return {
        "input_tokens": _sum_nullable_token_values(
            execucao.input_tokens for execucao in execution_records
        ),
        "processing_tokens": _sum_nullable_token_values(
            execucao.processing_tokens for execucao in execution_records
        ),
        "output_tokens": _sum_nullable_token_values(
            execucao.output_tokens for execucao in execution_records
        ),
        "total_tokens": _sum_nullable_token_values(
            execucao.total_tokens for execucao in execution_records
        ),
        "custo_usd": custo_usd,
        "custo_brl": custo_brl,
    }


_PLAIN_TEXT_FORMATS = {ProcessingOutputFormat.TXT, ProcessingOutputFormat.PDF}


def _parse_structured_output(output_text, requested_output_format=None):
    if not output_text:
        raise ProcessamentoExecutionError(
            "A IA nao retornou conteudo util para compor a saida."
        )

    normalized_text = output_text.strip()
    if normalized_text.startswith("```"):
        lines = normalized_text.splitlines()
        if len(lines) >= 3:
            normalized_text = "\n".join(lines[1:-1]).strip()

    try:
        return json.loads(normalized_text)
    except json.JSONDecodeError as exc:
        if requested_output_format in _PLAIN_TEXT_FORMATS:
            return normalized_text
        raw_excerpt = _truncate_error_excerpt(normalized_text)
        raise ProcessamentoExecutionError(
            "A resposta da IA nao veio em JSON valido para este processamento.",
            technical_message=(
                "Falha ao interpretar JSON retornado pela IA. "
                f"Erro: {exc}. Trecho da resposta: {raw_excerpt}"
            ),
        ) from exc


def _render_output_file(parsed_output, requested_output_format, output_basename):
    output_format, render_payload = _resolver_formato_e_payload_saida(
        parsed_output,
        requested_output_format,
    )
    output_filename, output_bytes = render_output_file(
        render_payload,
        output_format,
        output_basename,
    )
    return output_filename, output_bytes, output_format, render_payload


def _resolver_formato_e_payload_saida(parsed_output, requested_output_format):
    if requested_output_format != ProcessingOutputFormat.AI_DEFINED:
        return requested_output_format, parsed_output

    if not isinstance(parsed_output, dict):
        raise ProcessamentoExecutionError(
            (
                "Quando o formato de saida e definido pela IA, a resposta precisa "
                "ser um objeto JSON com o campo formato_saida."
            )
        )

    raw_format = (
        parsed_output.get("formato_saida")
        or parsed_output.get("output_format")
        or parsed_output.get("tipo_arquivo_saida")
    )
    output_format = _normalizar_formato_saida_definido_pela_ia(raw_format)
    render_payload = _extrair_payload_saida_definido_pela_ia(parsed_output)
    return output_format, render_payload


def _normalizar_formato_saida_definido_pela_ia(raw_format):
    normalized_format = str(raw_format or "").strip().lower().lstrip(".")
    output_format = AI_DEFINED_OUTPUT_ALIASES.get(normalized_format)
    if output_format not in SUPPORTED_AI_DEFINED_OUTPUT_FORMATS:
        allowed = ", ".join(sorted(SUPPORTED_AI_DEFINED_OUTPUT_FORMATS))
        raise ProcessamentoExecutionError(
            (
                "A IA nao informou um formato de saida permitido. "
                f"Use um destes valores em formato_saida: {allowed}."
            ),
            technical_message=(
                "Formato de saida definido pela IA invalido ou ausente: "
                f"{raw_format!r}."
            ),
        )
    return output_format


def _extrair_payload_saida_definido_pela_ia(parsed_output):
    for payload_key in ("dados", "conteudo", "resultado", "arquivo", "payload", "data"):
        if payload_key in parsed_output:
            payload = parsed_output[payload_key]
            if payload in (None, ""):
                raise ProcessamentoExecutionError(
                    (
                        "A IA informou o formato de saida, mas nao enviou dados "
                        "para gerar o arquivo."
                    )
                )
            return payload

    ignored_keys = {
        "formato_saida",
        "output_format",
        "tipo_arquivo_saida",
        "status",
        "mensagem",
    }
    payload = {
        key: value
        for key, value in parsed_output.items()
        if key not in ignored_keys
    }
    if not payload:
        raise ProcessamentoExecutionError(
            (
                "A IA informou o formato de saida, mas nao enviou conteudo "
                "estruturado para gerar o arquivo."
            )
        )
    return payload


def _truncate_error_excerpt(value, limit=1800):
    normalized_value = " ".join(str(value or "").split())
    if len(normalized_value) <= limit:
        return normalized_value
    return f"{normalized_value[: limit - 3]}..."


def _build_output_basename(processamento, documento, output_format):
    base_name = Path(documento.nome_arquivo).stem or "resultado"
    return f"{processamento.codigo}_{base_name}.{output_format}"


def _next_execution_attempt_number(processamento):
    current_max = processamento.execucoes_ia.aggregate(
        max_tentativa=Max("tentativa_numero")
    )["max_tentativa"]
    return (current_max or 0) + 1


def _mark_document_error(
    *,
    processamento,
    documento,
    message,
    integration,
    model_name,
    execution_started_at,
):
    execution_finished_at = timezone.now()
    duration_ms = max(
        int((execution_finished_at - execution_started_at).total_seconds() * 1000),
        0,
    )

    with transaction.atomic():
        documento.status = DocumentStatus.ERRO
        documento.mensagem_erro = message
        documento.save(update_fields=["status", "mensagem_erro", "updated_at"])

        tentativa_numero = _next_execution_attempt_number(processamento)
        processamento.execucao_finalizada_em = execution_finished_at
        processamento.duracao_processamento_ms = duration_ms
        processamento.total_processados = processamento.documentos.filter(
            status=DocumentStatus.PROCESSADO
        ).count()
        processamento.status = ProcessingStatus.EM_PROCESSAMENTO
        _registrar_atividade_processamento(
            processamento,
            etapa_atual="Erro ao processar documento",
            documento_atual_nome=documento.nome_arquivo,
        )
        processamento.save(
            update_fields=[
                "execucao_finalizada_em",
                "duracao_processamento_ms",
                "total_processados",
                "status",
                "etapa_atual",
                "documento_atual_nome",
                "ultima_atividade_em",
                "updated_at",
            ]
        )

        execution_record = ProcessamentoExecucaoIA.objects.create(
            processamento=processamento,
            documento=documento,
            ai_provider_integration=integration,
            tentativa_numero=tentativa_numero,
            status=AIExecutionStatus.ERRO,
            modelo_utilizado=model_name,
            execucao_iniciada_em=execution_started_at,
            execucao_finalizada_em=execution_finished_at,
            duracao_ms=duration_ms,
            input_tokens=processamento.input_tokens,
            processing_tokens=processamento.processing_tokens,
            output_tokens=processamento.output_tokens,
            total_tokens=processamento.total_tokens,
            error_message=message,
            scope_type=ExecutionScopeType.INDIVIDUAL,
        )
        execution_record.documentos_entrada.set([documento])

        saida_erro = DocumentoSaidaProcessamento.objects.create(
            processamento=processamento,
            documento=documento,
            execucao_ia=execution_record,
            formato=processamento.output_format,
            status=OutputDocumentStatus.ERRO,
            mensagem_erro=message,
            scope_type=ExecutionScopeType.INDIVIDUAL,
        )
        saida_erro.documentos_entrada.set([documento])


def _mark_document_group_error(
    *,
    processamento,
    documentos,
    message,
    integration,
    model_name,
    execution_started_at,
):
    execution_finished_at = timezone.now()
    duration_ms = max(
        int((execution_finished_at - execution_started_at).total_seconds() * 1000),
        0,
    )
    with transaction.atomic():
        for documento in documentos:
            documento.status = DocumentStatus.ERRO
            documento.mensagem_erro = message
            documento.save(update_fields=["status", "mensagem_erro", "updated_at"])

        tentativa_numero = _next_execution_attempt_number(processamento)
        processamento.execucao_finalizada_em = execution_finished_at
        processamento.duracao_processamento_ms = duration_ms
        processamento.total_processados = processamento.documentos.filter(
            status=DocumentStatus.PROCESSADO
        ).count()
        processamento.status = ProcessingStatus.EM_PROCESSAMENTO
        _registrar_atividade_processamento(
            processamento,
            etapa_atual="Erro ao processar grupo de documentos",
            documento_atual_nome=f"{len(documentos)} documento(s)",
        )
        processamento.save(
            update_fields=[
                "execucao_finalizada_em",
                "duracao_processamento_ms",
                "total_processados",
                "status",
                "etapa_atual",
                "documento_atual_nome",
                "ultima_atividade_em",
                "updated_at",
            ]
        )

        execution_record = ProcessamentoExecucaoIA.objects.create(
            processamento=processamento,
            documento=None,
            ai_provider_integration=integration,
            tentativa_numero=tentativa_numero,
            status=AIExecutionStatus.ERRO,
            modelo_utilizado=model_name,
            execucao_iniciada_em=execution_started_at,
            execucao_finalizada_em=execution_finished_at,
            duracao_ms=duration_ms,
            input_tokens=processamento.input_tokens,
            processing_tokens=processamento.processing_tokens,
            output_tokens=processamento.output_tokens,
            total_tokens=processamento.total_tokens,
            error_message=message,
            scope_type=ExecutionScopeType.GRUPO,
        )
        execution_record.documentos_entrada.set(documentos)

        saida_erro_grupo = DocumentoSaidaProcessamento.objects.create(
            processamento=processamento,
            documento=None,
            execucao_ia=execution_record,
            formato=processamento.output_format,
            status=OutputDocumentStatus.ERRO,
            mensagem_erro=message,
            scope_type=ExecutionScopeType.GRUPO,
        )
        saida_erro_grupo.documentos_entrada.set(documentos)


def _log_execution_event(
    *,
    actor,
    processamento,
    documento,
    integration,
    model_name,
    execution_result,
    parsed_output,
    render_payload,
    telemetry,
    execution_record,
    output_record,
):
    evento_model = django_apps.get_model("auditoria", "EventoAuditoria")
    if evento_model is None:
        return
    safe_payload = json.loads(
        json.dumps(
            {
                "documento": documento.nome_arquivo,
                "drive_file_id": documento.drive_file_id,
                "source_type": documento.source_type,
                "source_reference": documento.source_reference,
                "provider_type": integration.provider_type,
                "integration_name": integration.nome,
                "model_name": model_name,
                "request_url": execution_result.request_url,
                "execution_record_id": execution_record.pk,
                "documento_saida_id": output_record.pk,
                "tentativa_numero": execution_record.tentativa_numero,
                "summary": execution_result.summary,
                "usage_metadata": execution_result.usage_metadata,
                "execucao_iniciada_em": telemetry["execucao_iniciada_em"],
                "execucao_finalizada_em": telemetry["execucao_finalizada_em"],
                "duracao_processamento_ms": telemetry["duracao_processamento_ms"],
                "duracao_processamento_minutos": telemetry[
                    "duracao_processamento_minutos"
                ],
                "input_tokens": telemetry["input_tokens"],
                "processing_tokens": telemetry["processing_tokens"],
                "output_tokens": telemetry["output_tokens"],
                "total_tokens": telemetry["total_tokens"],
                "custo_usd": execution_record.custo_usd,
                "custo_brl": execution_record.custo_brl,
                "output_format": output_record.formato,
                "output_keys": (
                    list(render_payload.keys()) if isinstance(render_payload, dict) else []
                ),
                "raw_output_keys": (
                    list(parsed_output.keys()) if isinstance(parsed_output, dict) else []
                ),
            },
            cls=DjangoJSONEncoder,
        )
    )
    evento_model.objects.create(
        modulo="processamentos",
        acao="executar_agente_documento",
        actor=actor,
        processamento=processamento,
        objeto_tipo="Processamento",
        objeto_id=str(processamento.pk),
        descricao=(
            f"Execucao do agente {processamento.agente.nome} no documento "
            f"{documento.nome_arquivo}"
        ),
        payload=safe_payload,
    )


def _log_group_execution_event(
    *,
    actor,
    processamento,
    documentos,
    integration,
    model_name,
    execution_result,
    parsed_output,
    render_payload,
    telemetry,
    execution_record,
    output_record,
):
    evento_model = django_apps.get_model("auditoria", "EventoAuditoria")
    if evento_model is None:
        return
    safe_payload = json.loads(
        json.dumps(
            {
                "documentos": _build_document_references(documentos),
                "source_type": processamento.input_source_type,
                "provider_type": integration.provider_type,
                "integration_name": integration.nome,
                "model_name": model_name,
                "request_url": execution_result.request_url,
                "execution_record_id": execution_record.pk,
                "documento_saida_id": output_record.pk,
                "tentativa_numero": execution_record.tentativa_numero,
                "summary": execution_result.summary,
                "usage_metadata": execution_result.usage_metadata,
                "execucao_iniciada_em": telemetry["execucao_iniciada_em"],
                "execucao_finalizada_em": telemetry["execucao_finalizada_em"],
                "duracao_processamento_ms": telemetry["duracao_processamento_ms"],
                "duracao_processamento_minutos": telemetry[
                    "duracao_processamento_minutos"
                ],
                "input_tokens": telemetry["input_tokens"],
                "processing_tokens": telemetry["processing_tokens"],
                "output_tokens": telemetry["output_tokens"],
                "total_tokens": telemetry["total_tokens"],
                "custo_usd": execution_record.custo_usd,
                "custo_brl": execution_record.custo_brl,
                "output_format": output_record.formato,
                "output_keys": (
                    list(render_payload.keys()) if isinstance(render_payload, dict) else []
                ),
                "raw_output_keys": (
                    list(parsed_output.keys()) if isinstance(parsed_output, dict) else []
                ),
            },
            cls=DjangoJSONEncoder,
        )
    )
    evento_model.objects.create(
        modulo="processamentos",
        acao="executar_agente_grupo_documentos",
        actor=actor,
        processamento=processamento,
        objeto_tipo="Processamento",
        objeto_id=str(processamento.pk),
        descricao=(
            f"Execucao agrupada do agente {processamento.agente.nome} em "
            f"{len(documentos)} documento(s)"
        ),
        payload=safe_payload,
    )


def _log_execution_without_document_event(
    *,
    actor,
    processamento,
    integration,
    model_name,
    execution_result,
    parsed_output,
    render_payload,
    telemetry,
    execution_record,
):
    evento_model = django_apps.get_model("auditoria", "EventoAuditoria")
    if evento_model is None:
        return
    safe_payload = json.loads(
        json.dumps(
            {
                "source_type": ProcessingInputSourceType.NONE,
                "provider_type": integration.provider_type,
                "integration_name": integration.nome,
                "model_name": model_name,
                "request_url": execution_result.request_url,
                "execution_record_id": execution_record.pk,
                "tentativa_numero": execution_record.tentativa_numero,
                "summary": execution_result.summary,
                "usage_metadata": execution_result.usage_metadata,
                "execucao_iniciada_em": telemetry["execucao_iniciada_em"],
                "execucao_finalizada_em": telemetry["execucao_finalizada_em"],
                "duracao_processamento_ms": telemetry["duracao_processamento_ms"],
                "duracao_processamento_minutos": telemetry[
                    "duracao_processamento_minutos"
                ],
                "input_tokens": telemetry["input_tokens"],
                "processing_tokens": telemetry["processing_tokens"],
                "output_tokens": telemetry["output_tokens"],
                "total_tokens": telemetry["total_tokens"],
                "custo_usd": execution_record.custo_usd,
                "custo_brl": execution_record.custo_brl,
                "output_format": processamento.arquivo_saida_formato,
                "output_keys": (
                    list(render_payload.keys()) if isinstance(render_payload, dict) else []
                ),
                "raw_output_keys": (
                    list(parsed_output.keys()) if isinstance(parsed_output, dict) else []
                ),
            },
            cls=DjangoJSONEncoder,
        )
    )
    evento_model.objects.create(
        modulo="processamentos",
        acao="executar_agente_sem_documento",
        actor=actor,
        processamento=processamento,
        objeto_tipo="Processamento",
        objeto_id=str(processamento.pk),
        descricao=(
            f"Execucao do agente {processamento.agente.nome} sem documento de entrada"
        ),
        payload=safe_payload,
    )


def _log_execution_error(
    *,
    actor,
    processamento,
    documento,
    integration,
    model_name,
    error_message,
):
    evento_model = django_apps.get_model("auditoria", "EventoAuditoria")
    if evento_model is None:
        return
    safe_payload = {
        "documento": documento.nome_arquivo if documento else "",
        "drive_file_id": documento.drive_file_id if documento else "",
        "source_type": documento.source_type if documento else "",
        "source_reference": documento.source_reference if documento else "",
        "provider_type": integration.provider_type if integration else "",
        "integration_name": integration.nome if integration else "",
        "model_name": model_name,
        "execucao_iniciada_em": processamento.execucao_iniciada_em.isoformat()
        if processamento.execucao_iniciada_em
        else "",
        "execucao_finalizada_em": processamento.execucao_finalizada_em.isoformat()
        if processamento.execucao_finalizada_em
        else "",
        "duracao_processamento_ms": processamento.duracao_processamento_ms,
        "duracao_processamento_minutos": _milliseconds_to_minutes(
            processamento.duracao_processamento_ms
        ),
        "input_tokens": processamento.input_tokens,
        "processing_tokens": processamento.processing_tokens,
        "output_tokens": processamento.output_tokens,
        "total_tokens": processamento.total_tokens,
        "erro": error_message,
    }
    evento_model.objects.create(
        modulo="processamentos",
        acao="erro_execucao_agente_documento",
        actor=actor,
        processamento=processamento,
        objeto_tipo="Processamento",
        objeto_id=str(processamento.pk),
        descricao=f"Falha na execucao do processamento {processamento.codigo}",
        payload=safe_payload,
    )


def _log_group_execution_error(
    *,
    actor,
    processamento,
    documentos,
    integration,
    model_name,
    error_message,
):
    evento_model = django_apps.get_model("auditoria", "EventoAuditoria")
    if evento_model is None:
        return
    safe_payload = {
        "documentos": _build_document_references(documentos),
        "source_type": processamento.input_source_type,
        "provider_type": integration.provider_type if integration else "",
        "integration_name": integration.nome if integration else "",
        "model_name": model_name,
        "execucao_iniciada_em": processamento.execucao_iniciada_em.isoformat()
        if processamento.execucao_iniciada_em
        else "",
        "execucao_finalizada_em": processamento.execucao_finalizada_em.isoformat()
        if processamento.execucao_finalizada_em
        else "",
        "duracao_processamento_ms": processamento.duracao_processamento_ms,
        "duracao_processamento_minutos": _milliseconds_to_minutes(
            processamento.duracao_processamento_ms
        ),
        "input_tokens": processamento.input_tokens,
        "processing_tokens": processamento.processing_tokens,
        "output_tokens": processamento.output_tokens,
        "total_tokens": processamento.total_tokens,
        "erro": error_message,
    }
    evento_model.objects.create(
        modulo="processamentos",
        acao="erro_execucao_agente_grupo_documentos",
        actor=actor,
        processamento=processamento,
        objeto_tipo="Processamento",
        objeto_id=str(processamento.pk),
        descricao=f"Falha na execucao agrupada do processamento {processamento.codigo}",
        payload=safe_payload,
    )


def _build_execution_telemetry(
    usage_metadata,
    *,
    execution_started_at,
    execution_finished_at,
):
    usage_metadata = usage_metadata or {}
    input_tokens = _normalize_token_value(usage_metadata.get("promptTokenCount"))
    output_tokens = _normalize_token_value(usage_metadata.get("candidatesTokenCount"))
    total_tokens = _normalize_token_value(usage_metadata.get("totalTokenCount"))
    explicit_processing = _normalize_token_value(usage_metadata.get("thoughtsTokenCount"))
    if explicit_processing is None:
        explicit_processing = _normalize_token_value(
            usage_metadata.get("toolUsePromptTokenCount")
        )
    processing_tokens = explicit_processing
    if (
        processing_tokens is None
        and total_tokens is not None
        and input_tokens is not None
        and output_tokens is not None
    ):
        processing_tokens = max(total_tokens - input_tokens - output_tokens, 0)

    duration_ms = max(
        int((execution_finished_at - execution_started_at).total_seconds() * 1000),
        0,
    )
    return {
        "execucao_iniciada_em": execution_started_at.isoformat(),
        "execucao_finalizada_em": execution_finished_at.isoformat(),
        "duracao_processamento_ms": duration_ms,
        "duracao_processamento_minutos": _milliseconds_to_minutes(duration_ms),
        "input_tokens": input_tokens,
        "processing_tokens": processing_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _normalize_token_value(value):
    if value in (None, ""):
        return None
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return None


def _milliseconds_to_minutes(value):
    if value in (None, ""):
        return None
    return round(int(value) / 60000, 2)


def _build_document_references(documentos: Iterable):
    referencias = []
    for documento in documentos:
        referencias.append(
            {
                "id": documento.pk,
                "nome_arquivo": documento.nome_arquivo,
                "source_type": documento.source_type,
                "source_reference": documento.source_reference,
            }
        )
    return referencias


def _sum_nullable_token_values(values):
    collected = [value for value in values if value is not None]
    if not collected:
        return None
    return sum(collected)
