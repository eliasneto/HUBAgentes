from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.processamentos.models import DocumentStatus, Processamento, ProcessingStatus


ORPHAN_PROCESSING_TIMEOUT_SECONDS = 300


def reconciliar_processamento_orfao(processamento: Processamento) -> Processamento:
    if not _is_candidate(processamento):
        return processamento

    last_activity = processamento.ultima_atividade_em or processamento.updated_at
    if last_activity is None:
        return processamento

    if timezone.now() - last_activity < timedelta(
        seconds=ORPHAN_PROCESSING_TIMEOUT_SECONDS
    ):
        return processamento

    with transaction.atomic():
        if processamento.status not in {
            ProcessingStatus.CRIADO,
            ProcessingStatus.EM_FILA,
            ProcessingStatus.EM_PROCESSAMENTO,
        }:
            return processamento

        processamento.status = ProcessingStatus.CONCLUIDO_ERRO
        processamento.mensagem_erro = (
            "Processamento interrompido antes da conclusao. "
            "Contate o administrador do sistema."
        )
        processamento.mensagem_erro_tecnico = (
            "Processamento orfao detectado: nenhuma atividade registrada "
            "dentro do tempo limite operacional."
        )
        processamento.finalizado_em = timezone.now()
        processamento.execucao_finalizada_em = processamento.execucao_finalizada_em or timezone.now()
        processamento.etapa_atual = "Processamento interrompido"
        processamento.documento_atual_nome = ""
        processamento.ultima_atividade_em = timezone.now()
        processamento.total_processados = processamento.documentos.filter(
            status=DocumentStatus.PROCESSADO
        ).count()
        processamento.save(
            update_fields=[
                "status",
                "mensagem_erro",
                "mensagem_erro_tecnico",
                "finalizado_em",
                "execucao_finalizada_em",
                "etapa_atual",
                "documento_atual_nome",
                "ultima_atividade_em",
                "total_processados",
                "updated_at",
            ]
        )

        processamento.documentos.filter(status=DocumentStatus.EM_PROCESSAMENTO).update(
            status=DocumentStatus.ERRO,
            mensagem_erro="Processamento interrompido antes da conclusao.",
            updated_at=timezone.now(),
        )

    processamento.refresh_from_db()
    return processamento


def _is_candidate(processamento: Processamento) -> bool:
    return processamento.status in {
        ProcessingStatus.CRIADO,
        ProcessingStatus.EM_FILA,
        ProcessingStatus.EM_PROCESSAMENTO,
    }
