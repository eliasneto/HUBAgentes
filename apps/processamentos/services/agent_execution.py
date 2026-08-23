import json
import logging
import threading
import time
from datetime import timedelta
from pathlib import Path
from collections.abc import Iterable

from django.apps import apps as django_apps
from django.core.files.base import ContentFile
from django.core.serializers.json import DjangoJSONEncoder
from django.db import close_old_connections, transaction
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
    suporta_reducao_de_thinking_budget,
)
from apps.integracoes.services.google_drive import GoogleDriveServiceError
from apps.integracoes.services.local_storage import LocalStorageServiceError
from apps.processamentos.models import (
    AIExecutionStatus,
    DocumentoSaidaProcessamento,
    DocumentStatus,
    ExecutionScopeType,
    OutputDocumentStatus,
    Processamento,
    ProcessamentoExecucaoIA,
    ProcessingInputSourceType,
    ProcessingOutputFormat,
    ProcessingStatus,
)
from apps.processamentos.services.document_sources import (
    DocumentSourcePreparationError,
    adotar_documentos_pendentes_de_retentativa,
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
from apps.processamentos.services.pdf_preprocessing import (
    PdfPreprocessingError,
    eh_pdf,
    pre_processar_pdf,
)
from apps.processamentos.services.output_packaging import (
    OutputPackagingError,
    publicar_saida_final,
)
from apps.processamentos.services.output_renderers import (
    OutputRendererError,
    render_output_file,
)


class ProcessamentoExecutionError(Exception):
    def __init__(
        self,
        message,
        *,
        technical_message="",
        usage_metadata=None,
        retryable=False,
        sem_trabalho=False,
    ):
        super().__init__(message)
        self.technical_message = technical_message
        # Tokens consumidos quando a IA respondeu mas o conteudo foi rejeitado
        # (ex.: JSON invalido). O provedor cobra por eles; registramos no erro.
        self.usage_metadata = usage_metadata
        # JSON invalido / saida truncada nao se resolvem sozinhos (mesmo
        # doc+prompt tende a repetir): padrao False = nao reprocessa.
        self.retryable = retryable
        # True quando NENHUM documento chegou a ser selecionado para
        # processamento (pasta vazia ou 100% ja processada antes) — nenhuma
        # chamada de IA aconteceu. Usado por operational_execution para
        # descartar (soft-delete) o Processamento em vez de deixa-lo visivel
        # no Portal como uma execucao "concluida com atencao": nada foi
        # tentado de fato, entao nao ha o que o usuario acompanhar.
        self.sem_trabalho = sem_trabalho


# Loop de retentativa automatica quando o PROVEDOR de IA esta sobrecarregado
# (nao um erro nosso) — ver Processamento.retentativa_sobrecarga_ativa e o
# management command retentar_processamentos_sobrecarga_provedor (chamado
# periodicamente pelo worker, ver docker-compose.yml). Caso real: agente
# JHS/Licitacao, 19/08/2026 — Gemini devolvendo HTTP 503 "This model is
# currently experiencing high demand" para gemini-2.5-pro.
#
# Teto reduzido de 2h para 45min (1.5.25): o backoff abaixo ja estabiliza em
# ciclos fixos de 30min a partir de ~52min, entao o teto original comprava
# pouca chance adicional de recuperacao depois disso — so alongava o tempo
# em que um documento fica "em espera" sem que nada externo (novo clique
# manual, nova rodada da rotina automatica) reconheca que ele ja esta sendo
# tratado aqui (ver _arquivo_ja_processado_em_outra_execucao, no
# document_sources.py, que agora cobre esse estado — mas quanto maior o
# teto, maior a janela em que uma execucao concorrente ainda poderia
# duplicar o processamento do mesmo arquivo antes dessa checagem existir).
LIMITE_RETENTATIVA_SOBRECARGA = timedelta(minutes=45)

# Intervalo (minutos) antes de cada nova rodada de retentativa, crescente
# ate estabilizar em 30min — depois disso repete 30min ate o teto configurado
# em LIMITE_RETENTATIVA_SOBRECARGA.
# Ex.: tentativas 0,1,2,3,4,5+ -> espera 2,5,10,15,20,30min respectivamente.
_INTERVALOS_RETENTATIVA_SOBRECARGA_MINUTOS = [2, 5, 10, 15, 20, 30]

# Trechos que identificam o provedor recusando a chamada por estar
# sobrecarregado (nao e erro de configuracao, timeout de rede nem cota
# esgotada — e o MODELO em si sem capacidade no momento). Hoje cobre o
# padrao observado na Gemini; outros provedores podem ser adicionados aqui
# conforme surgirem casos reais.
_PADROES_MODELO_SOBRECARREGADO = (
    "currently experiencing high demand",
    "model is overloaded",
)


def _eh_erro_modelo_sobrecarregado(mensagem_tecnica):
    """True quando o detalhe tecnico do erro indica que o PROVEDOR recusou
    a chamada por sobrecarga momentanea do modelo (ex.: Gemini HTTP 503
    "This model is currently experiencing high demand") — situacao
    genuinamente temporaria do lado de fora, elegivel para o loop de
    retentativa (ver LIMITE_RETENTATIVA_SOBRECARGA) em vez de desistir
    depois de 1-2 tentativas."""
    if not mensagem_tecnica:
        return False
    normalizado = mensagem_tecnica.lower()
    if any(padrao in normalizado for padrao in _PADROES_MODELO_SOBRECARREGADO):
        return True
    return "503" in normalizado and "unavailable" in normalizado


def _proximo_intervalo_retentativa_sobrecarga(tentativas_ja_feitas):
    indice = min(
        tentativas_ja_feitas, len(_INTERVALOS_RETENTATIVA_SOBRECARGA_MINUTOS) - 1
    )
    return timedelta(minutes=_INTERVALOS_RETENTATIVA_SOBRECARGA_MINUTOS[indice])


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
    # Reseta o sub-progresso: cada chamada aqui marca o INICIO de uma etapa
    # "inteira" nova (ex.: "Lendo documento atual", "Documento processado
    # com sucesso"). Sub-progresso dentro da etapa atual usa
    # _registrar_progresso_etapa, que preserva etapa_atual e so avanca o
    # percentual.
    processamento.progresso_etapa_percentual = 0
    processamento.ultima_atividade_em = timezone.now()


def _registrar_progresso_etapa(processamento, *, percentual, etapa_atual):
    """Avanca o sub-progresso (0-100) da etapa em andamento no documento
    atual, sem trocar `documento_atual_nome`. Usado pelo pre-processamento
    de PDF para o indicador de progresso mostrar avanco continuo em vez de
    saltar direto de 0% para 100% num processamento de 1 documento so (ver
    selectors._calcular_percentual, que mistura este valor)."""
    processamento.etapa_atual = etapa_atual
    processamento.progresso_etapa_percentual = max(0, min(percentual, 100))
    processamento.ultima_atividade_em = timezone.now()
    processamento.save(
        update_fields=[
            "etapa_atual",
            "progresso_etapa_percentual",
            "ultima_atividade_em",
            "updated_at",
        ]
    )


logger = logging.getLogger(__name__)


class _AtividadeHeartbeat:
    """Mantem `ultima_atividade_em` atualizado enquanto uma chamada ao
    provedor de IA esta em andamento (inclusive durante retries internos do
    adapter, ver apps.integracoes.services.ai_providers.base).

    Sem isso, uma unica chamada de IA legitima que passe do limiar de
    "possivel travamento" (selectors.STALL_SECONDS_THRESHOLD) faz o indicador
    de progresso mostrar um alerta de trava mesmo com o processamento
    seguindo ativo, so aguardando resposta do provedor (caso investigado em
    producao em 16/08/2026, PROC-20260816204934-797C8A23: 226s numa unica
    chamada ao gemini-2.5-pro, com um retry por timeout no meio).

    Usa UPDATE direto (nao passa por Processamento.save) para nao conflitar
    com o objeto `processamento` em memoria, que a thread principal continua
    alterando e salvando normalmente apos a chamada terminar.
    """

    INTERVALO_SEGUNDOS = 30

    def __init__(self, processamento):
        self._processamento_id = processamento.pk
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        try:
            while not self._stop_event.wait(self.INTERVALO_SEGUNDOS):
                try:
                    Processamento.objects.filter(pk=self._processamento_id).update(
                        ultima_atividade_em=timezone.now()
                    )
                except Exception:
                    logger.debug(
                        "Falha ao atualizar heartbeat de atividade do processamento %s.",
                        self._processamento_id,
                        exc_info=True,
                    )
        finally:
            # Django nao gerencia conexoes de threads fora do ciclo de
            # request/response; fecha a conexao que esta thread abriu.
            close_old_connections()

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._stop_event.set()
        self._thread.join(timeout=5)
        return False


def execute_processing(processamento, actor, *, limite_documentos_por_execucao=None):
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

    execution_params = _build_execution_params(processamento, model_name=model_name)
    if not processamento.ai_provider_integration_snapshot_id:
        processamento.ai_provider_integration_snapshot = integration
    if _deve_reconstruir_prompt_snapshot(processamento):
        processamento.prompt_snapshot = _build_prompt_snapshot(processamento)
    if not processamento.modelo_snapshot:
        processamento.modelo_snapshot = model_name

    limite_novos_documentos = None
    if limite_documentos_por_execucao is not None:
        # So a rotina automatica (unico call site que preenche esse limite —
        # ver operational_execution._executar_rotina_automatica_agente)
        # readota documentos de rodadas anteriores deste agente que ficaram
        # PENDENTE aguardando uma 2a chance apos erro pontual do provedor de
        # IA (ver _marcar_documento_pendente_retentativa). Precisa acontecer
        # ANTES de prepare_documentos: como eles passam a pertencer a este
        # processamento, _select_documentos ja os inclui e, por serem mais
        # antigos (created_at), entram na frente dos arquivos novos no corte
        # de limite_documentos_por_execucao logo abaixo.
        adotar_documentos_pendentes_de_retentativa(
            processamento, limite_documentos_por_execucao
        )
        # Desconta os ja readotados do teto de NOVOS documentos que a
        # descoberta pode criar (ver prepare_documentos), pra garantir que
        # o total (readotados + novos) nunca passe de
        # limite_documentos_por_execucao — sem isso, a descoberta criava um
        # DocumentoEntrada pra CADA arquivo da pasta de uma vez (sem teto,
        # exceto quando o agente le subpastas recursivamente), e so a
        # EXECUCAO (corte abaixo) respeitava o limite da rodada: o
        # processamento acabava "descobrindo" mais documentos do que de
        # fato executava, sobrando pendente(s) dentro de um processamento
        # ja concluido em vez de ficar de fora pra proxima rodada descobrir
        # do zero. Caso real: pasta com 11 PDFs, lote=10 — processamento
        # concluido_sucesso com 10 processados e 1 pendente esquecido dentro
        # dele mesmo.
        ja_existentes = processamento.documentos.count()
        limite_novos_documentos = max(0, limite_documentos_por_execucao - ja_existentes)
    resultado_preparo = prepare_documentos(
        processamento, limite_novos_documentos=limite_novos_documentos
    )
    processamento.total_documentos_ignorados = resultado_preparo.get("ignorados", 0)
    # Sinaliza para a view/front-end que a descoberta parou antes de
    # esgotar a pasta (limite de lote atingido — ver document_sources.
    # _LimiteLoteTracker) e ha mais PDFs pendentes nas subpastas alem
    # desta execucao; usado para disparar a continuacao automatica do
    # proximo lote. So pode ser True quando o agente le subpastas
    # recursivamente (AgenteConfiguracaoOperacional.include_subfolders).
    processamento.atingiu_limite_lote_subpastas = resultado_preparo.get(
        "atingiu_limite_lote", False
    )
    processamento.save(
        update_fields=[
            "total_documentos_ignorados",
            "atingiu_limite_lote_subpastas",
            "updated_at",
        ]
    )
    documentos = list(_select_documentos(processamento))
    if limite_documentos_por_execucao is not None:
        # Rotina automatica (ver AgenteConfiguracaoOperacional.
        # execucao_automatica_ativa): processa so os N mais antigos
        # (_select_documentos ja ordena por created_at) nesta rodada — o
        # resto continua PENDENTE, selecionavel na proxima rodada (ou num
        # clique manual em "Executar" entre uma rodada e outra). Evita
        # lotes grandes (ex.: 40-50 documentos) estourarem o timeout do
        # gunicorn (600s) numa unica requisicao sincrona.
        documentos = documentos[:limite_documentos_por_execucao]
    if processamento.input_source_type == ProcessingInputSourceType.NONE:
        return _execute_without_document(
            processamento=processamento,
            integration=integration,
            model_name=model_name,
            execution_params=execution_params,
            actor=actor,
        )
    if not documentos:
        if resultado_preparo.get("ignorados"):
            # Todos os arquivos da pasta ja foram processados com sucesso
            # antes por este agente (ver document_sources._arquivo_ja_processado_anteriormente).
            # Mensagem precisa bater em _MENSAGENS_ATENCAO para virar
            # CONCLUIDO_ATENCAO (amarelo) em vez de erro. sem_trabalho=True
            # porque nenhuma chamada de IA chegou a acontecer.
            raise ProcessamentoExecutionError(
                "Todos os arquivos desta pasta ja foram processados anteriormente "
                "por este agente.",
                sem_trabalho=True,
            )
        raise ProcessamentoExecutionError(
            "Nenhum PDF pendente foi encontrado para execucao nesse processamento.",
            sem_trabalho=True,
        )

    batch_started_at = timezone.now()
    _start_processing_batch(
        processamento=processamento,
        batch_started_at=batch_started_at,
        integration=integration,
        model_name=model_name,
    )

    if _usa_execucao_individual(processamento):
        from apps.core.models import ConfiguracaoGeral

        batch_result = _execute_documents_individually(
            processamento=processamento,
            documentos=documentos,
            integration=integration,
            model_name=model_name,
            execution_params=execution_params,
            actor=actor,
            intervalo_entre_documentos_segundos=(
                ConfiguracaoGeral.obter().intervalo_entre_documentos_ia_segundos
            ),
            # So a rotina automatica pode adiar erro pontual do provedor de
            # IA para a proxima rodada (ver _marcar_documento_pendente_retentativa)
            # — execucao manual mantem o comportamento atual (erro na hora).
            permite_adiamento_erro_pontual=limite_documentos_por_execucao is not None,
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

    if (
        _usa_execucao_individual(processamento)
        and batch_result["total_errors"]
        and _eh_erro_modelo_sobrecarregado(batch_result["last_technical_error_message"])
    ):
        # Provedor sobrecarregado (nao erro nosso, nao erro do documento) —
        # em vez de concluir com erro/atencao de cara, entra no loop de
        # retentativa automatica (ver LIMITE_RETENTATIVA_SOBRECARGA e
        # retentar_processamentos_sobrecarga_provedor). Os documentos ja
        # processados com sucesso aqui permanecem PROCESSADO; so os que
        # falharam por sobrecarga continuam ERRO+erro_reprocessavel=True,
        # elegveis para o loop.
        _iniciar_retentativa_sobrecarga(processamento)
        return {
            "documentos_processados": batch_result["total_success"],
            "documentos_com_erro": batch_result["total_errors"],
            "aguardando_retentativa_sobrecarga": True,
        }

    finished_at = timezone.now()
    telemetry = _aggregate_processing_telemetry(processamento)

    with transaction.atomic():
        # DB-A1: recalcula ambos os totais em uma unica query agregada, evitando
        # a janela de inconsistencia entre duas contagens separadas.
        processamento.recalcular_totais()
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
            from apps.processamentos.services.operational_execution import _e_situacao_atencao
            msg_erro = batch_result["last_error_message"] or "Uma ou mais execucoes terminaram com erro."
            processamento.status = (
                ProcessingStatus.CONCLUIDO_ATENCAO
                if _e_situacao_atencao(msg_erro)
                else ProcessingStatus.CONCLUIDO_ERRO
            )
            processamento.mensagem_erro = msg_erro
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


def _iniciar_retentativa_sobrecarga(processamento):
    """Liga o loop de retentativa por sobrecarga do provedor: o
    processamento fica EM_PROCESSAMENTO (nao erro/atencao) enquanto o
    management command retentar_processamentos_sobrecarga_provedor tenta de
    novo, periodicamente, so os documentos que falharam por sobrecarga.

    Nao seta mensagem_erro aqui de proposito: o painel "Ver erro" do
    front-end (agente_execucao.js/processamentos.js) aparece sempre que
    mensagem_erro nao esta vazio, independente do status — setar essa
    mensagem enquanto status continua em_processamento mostraria um painel
    de erro vermelho durante algo que nao e um erro, so uma espera. O
    indicativo "em andamento" (nao alarmante) vem de etapa_atual, ja exibido
    normalmente na tela para qualquer execucao em processamento."""
    agora = timezone.now()
    processamento.retentativa_sobrecarga_ativa = True
    processamento.retentativa_sobrecarga_iniciada_em = agora
    processamento.retentativa_sobrecarga_tentativas = 0
    processamento.retentativa_sobrecarga_proxima_em = (
        agora + _proximo_intervalo_retentativa_sobrecarga(0)
    )
    processamento.status = ProcessingStatus.EM_PROCESSAMENTO
    _registrar_atividade_processamento(
        processamento,
        etapa_atual="Aguardando reenvio automatico (modelo de IA sobrecarregado)",
    )
    processamento.save(
        update_fields=[
            "retentativa_sobrecarga_ativa",
            "retentativa_sobrecarga_iniciada_em",
            "retentativa_sobrecarga_tentativas",
            "retentativa_sobrecarga_proxima_em",
            "status",
            "etapa_atual",
            "documento_atual_nome",
            "progresso_etapa_percentual",
            "ultima_atividade_em",
            "updated_at",
        ]
    )


def _ultimo_erro_tecnico_auditoria(processamento):
    """Busca o detalhe tecnico real (HTTP/corpo cru) da falha mais recente
    deste processamento, guardado por _tentar_executar_documento_individual
    via _log_execution_error. Usado ao finalizar o loop de retentativa por
    sobrecarga, quando nao ha um batch_result em memoria para consultar."""
    evento_model = django_apps.get_model("auditoria", "EventoAuditoria")
    if evento_model is None:
        return ""
    evento = (
        evento_model.objects.filter(
            processamento=processamento,
            acao="erro_execucao_agente_documento",
        )
        .order_by("-created_at")
        .first()
    )
    if not evento:
        return ""
    return (evento.payload or {}).get("erro", "")


def _finalizar_loop_sobrecarga(processamento, *, desistiu_por_timeout=False):
    """Encerra o loop de retentativa por sobrecarga — chamado quando todos
    os documentos elegveis finalmente processaram (sucesso ou erro
    definitivo) ou quando o teto de LIMITE_RETENTATIVA_SOBRECARGA foi
    atingido. Espelha a finalizacao de execute_processing, mas le o estado
    direto do banco em vez de um batch_result em memoria, ja que as
    tentativas aconteceram em chamadas separadas ao longo do tempo."""
    finished_at = timezone.now()
    telemetry = _aggregate_processing_telemetry(processamento)

    erro_docs = list(
        processamento.documentos.filter(status=DocumentStatus.ERRO).order_by(
            "-updated_at"
        )
    )
    total_errors = len(erro_docs)
    last_error_message = erro_docs[0].mensagem_erro if erro_docs else ""
    last_technical_error_message = _ultimo_erro_tecnico_auditoria(processamento)

    output_records = list(
        DocumentoSaidaProcessamento.objects.filter(processamento=processamento)
    )

    with transaction.atomic():
        processamento.recalcular_totais()
        processamento.execucao_finalizada_em = finished_at
        processamento.finalizado_em = finished_at
        processamento.input_tokens = telemetry["input_tokens"]
        processamento.processing_tokens = telemetry["processing_tokens"]
        processamento.output_tokens = telemetry["output_tokens"]
        processamento.total_tokens = telemetry["total_tokens"]
        processamento.custo_usd = telemetry.get("custo_usd")
        processamento.custo_brl = telemetry.get("custo_brl")
        processamento.retentativa_sobrecarga_ativa = False
        if total_errors:
            if desistiu_por_timeout:
                # Duracao calculada a partir da constante (nao hardcoded) pra
                # nunca destoar se LIMITE_RETENTATIVA_SOBRECARGA for ajustado.
                minutos_teto = int(LIMITE_RETENTATIVA_SOBRECARGA.total_seconds() // 60)
                duracao_legivel = (
                    f"{minutos_teto} minutos"
                    if minutos_teto < 60
                    else f"{minutos_teto // 60} hora(s)"
                )
                msg_erro = (
                    f"O modelo de IA continuou sobrecarregado mesmo apos "
                    f"tentar por {duracao_legivel}. {total_errors} documento(s) nao "
                    "puderam ser processados — tente executar o agente "
                    "novamente mais tarde."
                )
            else:
                msg_erro = last_error_message or "Uma ou mais execucoes terminaram com erro."
            # Root cause desta finalizacao e sempre sobrecarga do provedor
            # (so entra no loop por causa dela) — trata como "atencao", nao
            # como falha tecnica critica, mesmo apos desistir do loop.
            processamento.status = ProcessingStatus.CONCLUIDO_ATENCAO
            processamento.mensagem_erro = msg_erro
            processamento.mensagem_erro_tecnico = last_technical_error_message
        else:
            processamento.status = ProcessingStatus.CONCLUIDO_SUCESSO
            processamento.mensagem_erro = ""
            processamento.mensagem_erro_tecnico = ""
        _registrar_atividade_processamento(
            processamento,
            etapa_atual=(
                "Processamento concluido com erro"
                if total_errors
                else "Processamento concluido com sucesso"
            ),
        )
        if output_records:
            publicar_saida_final(
                processamento=processamento,
                output_records=output_records,
                output_packaging_mode=processamento.output_packaging_mode_snapshot,
                output_assembly_mode=processamento.output_assembly_mode_snapshot,
                source_document_count=processamento.total_documentos or len(output_records),
            )
        processamento.save()


def _processar_rodada_retentativa_sobrecarga(processamento, *, agora):
    """Uma rodada do loop: decide desistir (teto estourado), finalizar (nada
    mais pendente) ou tentar de novo so os documentos elegveis, adiando a
    proxima rodada com intervalo crescente. Chamado pelo management command
    retentar_processamentos_sobrecarga_provedor, uma vez por processamento
    elegvel a cada execucao do comando (cadencia real definida pelo
    agendamento do worker — ver docker-compose.yml)."""
    if (
        processamento.retentativa_sobrecarga_iniciada_em is not None
        and agora - processamento.retentativa_sobrecarga_iniciada_em
        >= LIMITE_RETENTATIVA_SOBRECARGA
    ):
        _finalizar_loop_sobrecarga(processamento, desistiu_por_timeout=True)
        return "desistiu_apos_2h"

    integration = (
        processamento.ai_provider_integration_snapshot
        or processamento.agente.ai_provider_integration
    )
    model_name = processamento.modelo_snapshot or integration.default_model
    execution_params = _build_execution_params(processamento, model_name=model_name)
    actor = processamento.iniciado_por

    documentos = list(
        processamento.documentos.filter(
            status=DocumentStatus.ERRO, erro_reprocessavel=True
        )
    )
    if not documentos:
        # Nada mais elegvel — ou tudo ja resolveu, ou o que sobrou e erro
        # definitivo (nao relacionado a sobrecarga). Finaliza de qualquer
        # forma; o estado real de cada documento decide sucesso/atencao.
        _finalizar_loop_sobrecarga(processamento)
        return "concluido_sem_pendentes"

    for documento in documentos:
        _tentar_executar_documento_individual(
            processamento=processamento,
            documento=documento,
            integration=integration,
            model_name=model_name,
            execution_params=execution_params,
            actor=actor,
        )

    ainda_pendente = processamento.documentos.filter(
        status=DocumentStatus.ERRO, erro_reprocessavel=True
    ).exists()
    if not ainda_pendente:
        _finalizar_loop_sobrecarga(processamento)
        return "concluido"

    processamento.refresh_from_db(fields=["retentativa_sobrecarga_tentativas"])
    processamento.retentativa_sobrecarga_tentativas += 1
    processamento.retentativa_sobrecarga_proxima_em = timezone.now() + (
        _proximo_intervalo_retentativa_sobrecarga(
            processamento.retentativa_sobrecarga_tentativas
        )
    )
    _registrar_atividade_processamento(
        processamento,
        etapa_atual=(
            "Aguardando reenvio automatico (tentativa "
            f"{processamento.retentativa_sobrecarga_tentativas})"
        ),
    )
    processamento.save(
        update_fields=[
            "retentativa_sobrecarga_tentativas",
            "retentativa_sobrecarga_proxima_em",
            "etapa_atual",
            "documento_atual_nome",
            "progresso_etapa_percentual",
            "ultima_atividade_em",
            "updated_at",
        ]
    )
    return "tentando_de_novo"


def retentar_processamentos_com_sobrecarga():
    """Ponto de entrada chamado periodicamente pelo worker (ver management
    command retentar_processamentos_sobrecarga_provedor) para avancar o
    loop de retentativa de todo processamento elegvel no momento. Uma
    rodada por processamento por chamada — a cadencia real de novas
    tentativas depende de com que frequencia o worker chama este comando."""
    agora = timezone.now()
    elegveis = Processamento.objects.filter(
        retentativa_sobrecarga_ativa=True,
        retentativa_sobrecarga_proxima_em__lte=agora,
    ).select_related("agente", "ai_provider_integration_snapshot")

    resultados = []
    for processamento in elegveis:
        resultado = _processar_rodada_retentativa_sobrecarga(processamento, agora=agora)
        resultados.append({"codigo": processamento.codigo, "resultado": resultado})
    return resultados


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
                "progresso_etapa_percentual",
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
    # LIVRE: nao altera o prompt — a IA retorna exatamente o que o prompt pede
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
        f"## {AI_DEFINED_OUTPUT_INSTRUCTION_MARKER}\n\n"
        "Escolha o formato mais adequado: xlsx (tabelas/listas), csv (dados simples), "
        "pdf (relatorios — use HTML com CSS), json (integracao com sistemas), txt (texto puro).\n\n"
        'Responda EXCLUSIVAMENTE com JSON valido: {"formato_saida": "<xlsx|csv|pdf|json|txt>", '
        '"justificativa": "<motivo em uma linha>", "dados": <conteudo completo>}\n\n'
        'Regra: "dados" deve ser completo, sem truncar. '
        "xlsx/csv: lista de listas com cabecalhos na 1a linha. "
        "O sistema converte automaticamente — nao gere arquivos diretamente."
    )


def _build_execution_params(processamento, *, model_name):
    execution_params = dict(processamento.agente.parametros_execucao or {})
    # Para formato LIVRE a IA deve retornar exatamente o que o prompt pede,
    # sem coerção de tipo. Para todos os outros formatos forçamos JSON para
    # garantir rastreabilidade e conversão estruturada.
    if processamento.output_format != ProcessingOutputFormat.LIVRE:
        execution_params.setdefault("response_mime_type", "application/json")
    # Reducao de thinking budget (ver AgenteConfiguracaoOperacional.
    # enable_thinking_budget_reduction): pede para a IA nao gastar tokens
    # com raciocinio interno antes de responder. Diferente do
    # pre-processamento de PDF, nao depende de documento nem de modo de
    # execucao — construido aqui uma unica vez, vale para os tres modos
    # (individual, grupo, pasta) e tambem para execucao sem documento.
    # Adapters que nao suportam thinking budget (todos exceto Gemini, por
    # enquanto) ignoram essa chave silenciosamente. Modelos Gemini que
    # exigem thinking mode sempre ligado (ex.: gemini-2.5-pro) sao
    # excluidos aqui — sem essa checagem, TODO documento pagaria uma
    # chamada HTTP inteira desperdicada (erro "Budget 0 is invalid...",
    # ver gemini_adapter) antes da retentativa que de fato funciona. Caso
    # real: agente JHS/Licitacao, 21/08/2026 — lote de 6 documentos
    # esbarrou no timeout de 600s do servidor por causa dessa lentidao
    # extra, so processando 5.
    configuracao_operacional = getattr(processamento.agente, "configuracao_operacional", None)
    if (
        configuracao_operacional
        and configuracao_operacional.enable_thinking_budget_reduction
        and suporta_reducao_de_thinking_budget(model_name)
    ):
        execution_params.setdefault("thinking_budget", 0)
    return execution_params


def _tentar_executar_documento_individual(
    *,
    processamento,
    documento,
    integration,
    model_name,
    execution_params,
    actor,
):
    """Executa um unico documento e normaliza o resultado (sucesso ou erro)
    num dict simples, sem levantar excecao. Usado tanto na 1a passada quanto
    na retentativa automatica de fim de lote em _execute_documents_individually
    — mantem o tratamento de erro (marcar documento, registrar auditoria)
    identico nos dois casos.
    """
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
        retryable = getattr(exc, "retryable", False)
        _mark_document_error(
            processamento=processamento,
            documento=documento,
            message=mensagem_operacional,
            integration=integration,
            model_name=model_name,
            execution_started_at=execution_started_at,
            usage_metadata=getattr(exc, "usage_metadata", None),
            retryable=retryable,
        )
        # Guarda o detalhe tecnico (ex.: HTTP 429/503, corpo cru da resposta
        # do provedor) na auditoria, nao so a mensagem amigavel — sem isso,
        # diagnosticar uma falha "provedor temporariamente indisponivel"
        # exige adivinhar se foi rate limit, timeout ou instabilidade real
        # (caso real: JHS/Licitacao, 19/08/2026).
        _log_execution_error(
            actor=actor,
            processamento=processamento,
            documento=documento,
            integration=integration,
            model_name=model_name,
            error_message=mensagem_tecnica or str(exc),
        )
        return {
            "sucesso": False,
            "retryable": retryable,
            "mensagem_operacional": mensagem_operacional,
            "mensagem_tecnica": mensagem_tecnica,
            # Usado por _execute_documents_individually para decidir se pode
            # adiar para a proxima rotina em vez de finalizar como erro (ver
            # _pode_adiar_para_proxima_rotina) — so falha vinda do PROVEDOR
            # de IA conta; erro interno (Drive, storage local, empacotamento
            # de saida) sempre vai direto para erro definitivo.
            "eh_erro_provedor_ia": isinstance(exc, AIProviderServiceError),
        }

    return {"sucesso": True, "execution_result": execution_result}


def _execute_documents_individually(
    *,
    processamento,
    documentos,
    integration,
    model_name,
    execution_params,
    actor,
    intervalo_entre_documentos_segundos=0,
    permite_adiamento_erro_pontual=False,
):
    output_records = []
    total_success = 0
    total_errors = 0
    last_error_message = ""
    last_technical_error_message = ""

    # DB-U2: limite de tentativas de execucao por documento (0 = sem limite).
    max_tentativas = obter_ou_criar_configuracao_operacional(
        processamento.agente
    ).max_tentativas

    def _registrar_erro_final(resultado):
        nonlocal total_errors, last_error_message, last_technical_error_message
        total_errors += 1
        last_error_message = resultado["mensagem_operacional"]
        if resultado["mensagem_tecnica"]:
            last_technical_error_message = resultado["mensagem_tecnica"]

    def _finalizar_documento_com_falha(documento, resultado):
        # Erro pontual do provedor de IA (ver AIProviderServiceError), 1a
        # falha deste documento entre rotinas automaticas: adia para a
        # proxima rodada em vez de fechar como erro definitivo agora — nao
        # entra em total_errors, entao o processamento pode fechar
        # CONCLUIDO_SUCESSO mesmo com este documento ainda pendente (o
        # documento resolve seu proprio destino, nao trava o processamento).
        # _mark_document_error ja rodou (dentro de
        # _tentar_executar_documento_individual) e ja registrou a auditoria
        # desta tentativa falha — aqui so ajustamos o status final.
        if (
            permite_adiamento_erro_pontual
            and resultado.get("eh_erro_provedor_ia")
            and documento.tentativas_pontuais == 0
        ):
            _marcar_documento_pendente_retentativa(documento)
            return
        _registrar_erro_final(resultado)

    # Espaca as chamadas de IA (ConfiguracaoGeral.
    # intervalo_entre_documentos_ia_segundos) para reduzir a chance de
    # estourar o limite de requisicoes por minuto do provedor em lotes
    # grandes (ex.: 50 documentos de uma vez). So espera ANTES de cada
    # chamada que nao seja a primeira do lote inteiro (1a e 2a passada
    # juntas) — nunca antes da primeira, nunca depois da ultima.
    _chamada_ja_feita = False

    def _aguardar_intervalo():
        nonlocal _chamada_ja_feita
        if _chamada_ja_feita and intervalo_entre_documentos_segundos:
            time.sleep(intervalo_entre_documentos_segundos)
        _chamada_ja_feita = True

    # 1a passada: tenta cada documento pendente uma vez.
    a_retentar = []
    for documento in documentos:
        if _documento_excedeu_tentativas(processamento, documento, max_tentativas):
            total_errors += 1
            mensagem = (
                f"O documento atingiu o limite de {max_tentativas} tentativa(s) de "
                "execucao e nao sera reprocessado."
            )
            last_error_message = mensagem
            _mark_document_max_tentativas(
                processamento=processamento,
                documento=documento,
                message=mensagem,
            )
            continue

        _aguardar_intervalo()
        resultado = _tentar_executar_documento_individual(
            processamento=processamento,
            documento=documento,
            integration=integration,
            model_name=model_name,
            execution_params=execution_params,
            actor=actor,
        )
        if resultado["sucesso"]:
            total_success += 1
            output_records.append(resultado["execution_result"]["output_record"])
            continue

        if resultado["retryable"] and not _documento_excedeu_tentativas(
            processamento, documento, max_tentativas
        ):
            # Erro potencialmente vindo da propria IA/provedor (timeout,
            # instabilidade, resposta truncada ou em JSON invalido) — guarda
            # para uma nova tentativa automatica ao final do lote em vez de
            # desistir na primeira falha. Erros de configuracao (credenciais,
            # formato nao suportado, documento maior que o contexto do
            # modelo) chegam aqui com retryable=False e vao direto para o
            # erro final, pois tendem a repetir a mesma falha.
            a_retentar.append(documento)
            continue

        _finalizar_documento_com_falha(documento, resultado)

    # 2a passada: uma unica retentativa automatica, ao final do lote, so para
    # os documentos guardados acima. Caso do incidente PROC-20260817131407:
    # 4 de 5 documentos passaram e o 5o falhou com "resposta da IA nao veio
    # em JSON valido" — falha de conteudo nao-deterministica da IA, nao um
    # problema permanente do documento; uma nova chamada tem boa chance de
    # dar certo. Ainda respeita max_tentativas do agente como teto.
    for documento in a_retentar:
        _aguardar_intervalo()
        resultado = _tentar_executar_documento_individual(
            processamento=processamento,
            documento=documento,
            integration=integration,
            model_name=model_name,
            execution_params=execution_params,
            actor=actor,
        )
        if resultado["sucesso"]:
            total_success += 1
            output_records.append(resultado["execution_result"]["output_record"])
            continue
        _finalizar_documento_com_falha(documento, resultado)

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
            usage_metadata=getattr(exc, "usage_metadata", None),
            retryable=getattr(exc, "retryable", False),
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
                usage_metadata=getattr(exc, "usage_metadata", None),
                retryable=getattr(exc, "retryable", False),
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
                "progresso_etapa_percentual",
                "ultima_atividade_em",
                "ai_provider_integration_snapshot",
                "prompt_snapshot",
                "modelo_snapshot",
                "updated_at",
            ]
        )

    adapter = get_ai_provider_adapter(integration)
    with _AtividadeHeartbeat(processamento):
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
        usage_metadata=execution_result.usage_metadata,
    )
    _ext = "" if processamento.output_format == ProcessingOutputFormat.LIVRE else f".{processamento.output_format}"
    output_filename, output_bytes, output_format, render_payload = _render_output_file(
        parsed_output,
        processamento.output_format,
        f"{processamento.codigo}_resultado{_ext}",
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


def _aplicar_preprocessamento_pdf(processamento, documento, document_bytes):
    """Roda o pre-processamento deterministico de PDF (remocao de paginas
    duplicadas/quase-duplicadas, ignorando cabecalhos/rodapes repetidos) e
    reporta o avanco no `processamento` a medida que roda. Em qualquer falha,
    loga e devolve o documento original sem reducao — isto e uma otimizacao
    de custo, nunca deve bloquear a analise pela IA.
    """
    ultimo_percentual_reportado = None

    def _reportar(percentual, etapa_atual):
        nonlocal ultimo_percentual_reportado
        if percentual == ultimo_percentual_reportado:
            return
        ultimo_percentual_reportado = percentual
        _registrar_progresso_etapa(processamento, percentual=percentual, etapa_atual=etapa_atual)

    try:
        resultado = pre_processar_pdf(document_bytes, on_progress=_reportar)
    except PdfPreprocessingError:
        logger.warning(
            "Falha no pre-processamento do PDF de '%s' (processamento %s); "
            "enviando o documento original para a IA sem reducao.",
            documento.nome_arquivo,
            processamento.codigo,
            exc_info=True,
        )
        return document_bytes

    if resultado.reduziu_documento:
        logger.info(
            "Pre-processamento removeu %d de %d paginas de '%s' (processamento %s) "
            "antes de enviar para a IA.",
            resultado.paginas_removidas,
            resultado.paginas_originais,
            documento.nome_arquivo,
            processamento.codigo,
        )
    return resultado.pdf_bytes


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
                "progresso_etapa_percentual",
                "ultima_atividade_em",
                "updated_at",
            ]
        )
        documento.status = DocumentStatus.EM_PROCESSAMENTO
        documento.mensagem_erro = ""
        documento.save(update_fields=["status", "mensagem_erro", "updated_at"])

    document_bytes = load_document_bytes(processamento, documento)

    configuracao_operacional = getattr(processamento.agente, "configuracao_operacional", None)
    preprocessamento_aplicado = bool(
        configuracao_operacional
        and configuracao_operacional.enable_pdf_preprocessing
        and eh_pdf(documento.mime_type, documento.nome_arquivo)
    )
    if preprocessamento_aplicado:
        document_bytes = _aplicar_preprocessamento_pdf(processamento, documento, document_bytes)

    adapter = get_ai_provider_adapter(integration)
    if preprocessamento_aplicado:
        # Fecha a fatia de progresso do pre-processamento (0-48%, ver
        # pdf_preprocessing.pre_processar_pdf) e segura em 50% enquanto
        # aguarda so a IA — que e uma unica chamada opaca, sem como reportar
        # avanco parcial. _AtividadeHeartbeat mantem ultima_atividade_em
        # fresca nesse meio tempo para o alerta de travamento nao disparar.
        _registrar_progresso_etapa(
            processamento,
            percentual=50,
            etapa_atual="Aguardando resposta da IA",
        )
    with _AtividadeHeartbeat(processamento):
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
        usage_metadata=execution_result.usage_metadata,
    )
    output_filename, output_bytes, output_format, render_payload = _render_output_file(
        parsed_output,
        processamento.output_format,
        _build_output_basename(processamento, documento, processamento.output_format),
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
                "progresso_etapa_percentual",
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
                "progresso_etapa_percentual",
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
    with _AtividadeHeartbeat(processamento):
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
        usage_metadata=execution_result.usage_metadata,
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
                "progresso_etapa_percentual",
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


_PLAIN_TEXT_FORMATS = {
    ProcessingOutputFormat.TXT,
    ProcessingOutputFormat.PDF,
    ProcessingOutputFormat.LIVRE,
}


def _parse_structured_output(output_text, requested_output_format=None, usage_metadata=None):
    if not output_text:
        raise ProcessamentoExecutionError(
            "A IA nao retornou conteudo util para compor a saida.",
            usage_metadata=usage_metadata,
            # Resposta vazia costuma vir de instabilidade do provedor
            # (filtro de seguranca, sobrecarga) e nao do documento em si:
            # elegivel para a retentativa automatica de fim de lote (ver
            # _execute_documents_individually).
            retryable=True,
        )

    normalized_text = output_text.strip()

    # Remove blocos de markdown ```json ... ``` ou ``` ... ```
    if normalized_text.startswith("```"):
        lines = normalized_text.splitlines()
        if len(lines) >= 3:
            normalized_text = "\n".join(lines[1:-1]).strip()

    # Tenta parse direto
    try:
        return json.loads(normalized_text)
    except json.JSONDecodeError:
        pass

    # Tenta extrair JSON do meio do texto (quando a IA adiciona texto antes/depois)
    import re
    # Procura objeto JSON {...}
    json_match = re.search(r'\{[\s\S]*\}', normalized_text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    # Procura array JSON [...]
    json_match = re.search(r'\[[\s\S]*\]', normalized_text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    if requested_output_format in _PLAIN_TEXT_FORMATS:
        return normalized_text

    raw_excerpt = _truncate_error_excerpt(normalized_text)
    raise ProcessamentoExecutionError(
        "A resposta da IA nao veio em JSON valido para este processamento.",
        technical_message=(
            "Falha ao interpretar JSON retornado pela IA. "
            f"Trecho da resposta: {raw_excerpt}"
        ),
        usage_metadata=usage_metadata,
        # Falha de conteudo da propria IA (resposta truncada ou mal formada),
        # nao um problema de configuracao do agente/documento — o mesmo
        # doc+prompt tem boa chance de gerar um JSON valido numa nova
        # chamada (caso real PROC-20260817131407: 4 de 5 documentos do
        # mesmo lote passaram, so 1 falhou aqui). Elegivel para a
        # retentativa automatica de fim de lote, respeitando max_tentativas.
        retryable=True,
    )


def _detectar_extensao_livre(texto: str) -> str:
    """Detecta a extensão correta para o modo livre baseado no conteúdo."""
    stripped = texto.strip()
    if stripped.lower().startswith(("<!doctype", "<html")):
        return "html"
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            import json as _json
            _json.loads(stripped)
            return "json"
        except ValueError:
            pass
    return "txt"


def _render_output_file(parsed_output, requested_output_format, output_basename):
    if requested_output_format == ProcessingOutputFormat.LIVRE:
        # Dados tabulares (lista de dicts ou lista de listas) → Excel, sem precisar
        # selecionar o formato manualmente. Cobre o caso "peça Excel no prompt → receba Excel".
        if (
            isinstance(parsed_output, list)
            and parsed_output
            and isinstance(parsed_output[0], (list, dict))
        ):
            output_filename, output_bytes = render_output_file(
                parsed_output, ProcessingOutputFormat.XLSX, output_basename
            )
            return output_filename, output_bytes, ProcessingOutputFormat.XLSX, parsed_output

        # Objetos não-string → serializa como JSON válido (evita repr Python)
        if not isinstance(parsed_output, str):
            texto = json.dumps(parsed_output, ensure_ascii=False, indent=2)
        else:
            texto = parsed_output

        ext = _detectar_extensao_livre(texto)
        filename = f"{output_basename}.{ext}"
        return filename, texto.encode("utf-8"), ProcessingOutputFormat.LIVRE, texto

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
    if output_format == ProcessingOutputFormat.LIVRE:
        # extensão será detectada pelo conteúdo em _render_output_file
        return f"{processamento.codigo}_{base_name}"
    return f"{processamento.codigo}_{base_name}.{output_format}"


def _next_execution_attempt_number(processamento):
    current_max = processamento.execucoes_ia.aggregate(
        max_tentativa=Max("tentativa_numero")
    )["max_tentativa"]
    return (current_max or 0) + 1


def _documento_excedeu_tentativas(processamento, documento, max_tentativas):
    """DB-U2: True se o documento ja atingiu o limite de execucoes configurado.

    Conta os registros de execucao ja existentes para o documento neste
    processamento. Como documentos em ERRO voltam para PENDENTE a cada re-run
    (ver document_sources._update_documento_if_needed), um documento que falha
    repetidamente acumularia uma execucao por re-run; este limite o interrompe.
    max_tentativas == 0 significa sem limite.
    """
    if not max_tentativas:
        return False
    tentativas_realizadas = processamento.execucoes_ia.filter(
        documento=documento
    ).count()
    return tentativas_realizadas >= max_tentativas


def _marcar_documento_pendente_retentativa(documento):
    """Adia um documento que falhou por erro pontual do provedor de IA (ver
    AIProviderServiceError) para a proxima rotina automatica, em vez de
    finalizar como erro definitivo — so na 1a falha consecutiva deste
    documento (ver DocumentoEntrada.tentativas_pontuais e
    _finalizar_documento_com_falha, em _execute_documents_individually).

    _mark_document_error ja rodou antes disso (dentro de
    _tentar_executar_documento_individual) e ja criou o registro de
    auditoria (ProcessamentoExecucaoIA com status ERRO) desta tentativa —
    aqui so sobrescrevemos o status "final" do documento, preservando esse
    historico. document_sources.adotar_documentos_pendentes_de_retentativa
    e quem devolve este documento para a fila na proxima rodada. Caso real:
    agente JHS/Licitacao, 21/08/2026.
    """
    documento.status = DocumentStatus.PENDENTE
    documento.mensagem_erro = ""
    documento.erro_reprocessavel = True
    documento.tentativas_pontuais += 1
    documento.save(
        update_fields=[
            "status",
            "mensagem_erro",
            "erro_reprocessavel",
            "tentativas_pontuais",
            "updated_at",
        ]
    )


def _mark_document_max_tentativas(*, processamento, documento, message):
    """DB-U2: marca o documento como erro por limite de tentativas atingido.

    Nao cria um novo ProcessamentoExecucaoIA de proposito: o objetivo do limite
    e justamente parar de consumir recursos: nenhuma chamada a IA e feita e a
    contagem de tentativas nao e inflada.
    """
    with transaction.atomic():
        documento.status = DocumentStatus.ERRO
        documento.mensagem_erro = message
        # Limite atingido: nao deve ser reprocessado novamente.
        documento.erro_reprocessavel = False
        documento.save(
            update_fields=[
                "status",
                "mensagem_erro",
                "erro_reprocessavel",
                "updated_at",
            ]
        )

        _registrar_atividade_processamento(
            processamento,
            etapa_atual="Documento ignorado: limite de tentativas atingido",
            documento_atual_nome=documento.nome_arquivo,
        )
        processamento.save(
            update_fields=[
                "etapa_atual",
                "documento_atual_nome",
                "progresso_etapa_percentual",
                "ultima_atividade_em",
                "updated_at",
            ]
        )


def _mark_document_error(
    *,
    processamento,
    documento,
    message,
    integration,
    model_name,
    execution_started_at,
    usage_metadata=None,
    retryable=False,
):
    execution_finished_at = timezone.now()
    duration_ms = max(
        int((execution_finished_at - execution_started_at).total_seconds() * 1000),
        0,
    )
    tokens = _tokens_from_usage(usage_metadata)
    custo_usd_exec, custo_brl_exec = _custo_de_tokens(model_name, tokens)

    with transaction.atomic():
        documento.status = DocumentStatus.ERRO
        documento.mensagem_erro = message
        # DB-U2/reprocesso seletivo: so erros transitorios sao reprocessados.
        documento.erro_reprocessavel = retryable
        documento.save(
            update_fields=[
                "status",
                "mensagem_erro",
                "erro_reprocessavel",
                "updated_at",
            ]
        )

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
                "progresso_etapa_percentual",
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
            input_tokens=tokens["input_tokens"],
            processing_tokens=tokens["processing_tokens"],
            output_tokens=tokens["output_tokens"],
            total_tokens=tokens["total_tokens"],
            custo_usd=custo_usd_exec,
            custo_brl=custo_brl_exec,
            usage_metadata=usage_metadata or {},
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
    usage_metadata=None,
    retryable=False,
):
    execution_finished_at = timezone.now()
    duration_ms = max(
        int((execution_finished_at - execution_started_at).total_seconds() * 1000),
        0,
    )
    tokens = _tokens_from_usage(usage_metadata)
    custo_usd_exec, custo_brl_exec = _custo_de_tokens(model_name, tokens)
    with transaction.atomic():
        for documento in documentos:
            documento.status = DocumentStatus.ERRO
            documento.mensagem_erro = message
            # Reprocesso seletivo: so erros transitorios voltam para PENDENTE.
            documento.erro_reprocessavel = retryable
            documento.save(
                update_fields=[
                    "status",
                    "mensagem_erro",
                    "erro_reprocessavel",
                    "updated_at",
                ]
            )

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
                "progresso_etapa_percentual",
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
            input_tokens=tokens["input_tokens"],
            processing_tokens=tokens["processing_tokens"],
            output_tokens=tokens["output_tokens"],
            total_tokens=tokens["total_tokens"],
            custo_usd=custo_usd_exec,
            custo_brl=custo_brl_exec,
            usage_metadata=usage_metadata or {},
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


def _tokens_from_usage(usage_metadata):
    """Extrai contagem de tokens de um usage_metadata de chamada que falhou.

    Usado para registrar o consumo real quando a IA respondeu mas o conteudo
    foi rejeitado (truncamento/JSON invalido) — o provedor cobra por esses
    tokens. Retorna None em cada campo quando nao ha dado de uso.
    """
    usage_metadata = usage_metadata or {}
    input_tokens = _normalize_token_value(usage_metadata.get("promptTokenCount"))
    output_tokens = _normalize_token_value(usage_metadata.get("candidatesTokenCount"))
    total_tokens = _normalize_token_value(usage_metadata.get("totalTokenCount"))
    processing_tokens = _normalize_token_value(usage_metadata.get("thoughtsTokenCount"))
    if (
        processing_tokens is None
        and total_tokens is not None
        and input_tokens is not None
        and output_tokens is not None
    ):
        processing_tokens = max(total_tokens - input_tokens - output_tokens, 0)
    if total_tokens is None and (input_tokens is not None or output_tokens is not None):
        total_tokens = (input_tokens or 0) + (output_tokens or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "processing_tokens": processing_tokens,
        "total_tokens": total_tokens,
    }


def _custo_de_tokens(model_name, tokens):
    """Calcula custo USD/BRL para tokens de uma execucao com erro; (None, None)
    quando nao ha tokens registrados."""
    if not tokens or tokens.get("total_tokens") in (None, 0):
        return None, None
    return calcular_custo_processamento(
        nome_modelo=model_name,
        input_tokens=tokens["input_tokens"],
        output_tokens=tokens["output_tokens"],
        processing_tokens=tokens["processing_tokens"],
    )


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
