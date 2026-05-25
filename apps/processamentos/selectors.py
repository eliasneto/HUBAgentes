from dataclasses import dataclass
from datetime import datetime

from django.core.paginator import Paginator
from django.urls import reverse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.processamentos.models import (
    DocumentStatus,
    Processamento,
    ProcessingOutputFormat,
    ProcessingStatus,
)
from apps.processamentos.services.error_handling import (
    ERRO_TECNICO_OPERACIONAL,
    normalizar_erro_processamento,
)
from apps.processamentos.services.stalled_processing import (
    reconciliar_processamento_orfao,
)


@dataclass(frozen=True)
class ProcessamentoResumo:
    codigo: str
    status: str
    status_codigo: str
    agente: str
    origem: str
    formato_saida: str
    total_documentos: int
    total_processados: int
    total_tokens: int | None
    percentual: int
    duracao_minutos: float | None
    iniciado_em: datetime | None
    finalizado_em: datetime | None
    etapa_atual: str
    documento_atual_nome: str
    ultima_atividade_em: datetime | None
    ultima_atividade_humanizada: str
    possivel_travamento: bool
    erro_operacional: str
    arquivo_saida_nome: str
    download_saida_url: str
    tem_arquivo_saida: bool


@dataclass(frozen=True)
class ProcessamentosPortalResumo:
    processamentos: list[ProcessamentoResumo]
    total: int
    em_andamento: int
    concluidos: int
    com_erro: int
    pagina_atual: int
    total_paginas: int
    itens_por_pagina: int
    primeiro_item: int
    ultimo_item: int
    tem_pagina_anterior: bool
    tem_proxima_pagina: bool
    pagina_anterior: int | None
    proxima_pagina: int | None
    paginas: list


@dataclass(frozen=True)
class ProcessamentoStatusPortal:
    codigo: str
    status: str
    status_codigo: str
    origem: str
    formato_saida: str
    total_documentos: int
    total_processados: int
    total_tokens: int | None
    percentual: int
    duracao_minutos: float | None
    iniciado_em: str
    finalizado_em: str
    mensagem_erro: str
    etapa_atual: str
    documento_atual_nome: str
    ultima_atividade_em: str
    ultima_atividade_humanizada: str
    possivel_travamento: bool
    tem_arquivo_saida: bool
    download_saida_url: str
    resumo_total: int
    resumo_em_andamento: int
    resumo_concluidos: int
    resumo_com_erro: int


STALL_SECONDS_THRESHOLD = 180


def _duracao_minutos(duracao_ms: int | None) -> float | None:
    if duracao_ms is None:
        return None
    return round(duracao_ms / 60000, 2)


def _erro_operacional(processamento: Processamento) -> str:
    if processamento.mensagem_erro_tecnico and not processamento.mensagem_erro:
        return ERRO_TECNICO_OPERACIONAL

    if processamento.mensagem_erro:
        mensagem_operacional, _ = normalizar_erro_processamento(
            processamento.mensagem_erro
        )
        return mensagem_operacional

    execucao_com_erro = next(
        (
            execucao
            for execucao in processamento.execucoes_ia.all()
            if execucao.error_message
        ),
        None,
    )
    if execucao_com_erro:
        mensagem_operacional, _ = normalizar_erro_processamento(
            execucao_com_erro.error_message
        )
        return mensagem_operacional

    documento_com_erro = next(
        (
            documento
            for documento in processamento.documentos.all()
            if documento.mensagem_erro
        ),
        None,
    )
    if documento_com_erro:
        mensagem_operacional, _ = normalizar_erro_processamento(
            documento_com_erro.mensagem_erro
        )
        return mensagem_operacional

    saida_com_erro = next(
        (
            saida
            for saida in processamento.documentos_saida.all()
            if saida.mensagem_erro
        ),
        None,
    )
    if saida_com_erro:
        mensagem_operacional, _ = normalizar_erro_processamento(
            saida_com_erro.mensagem_erro
        )
        return mensagem_operacional

    return ""


def listar_processamentos_para_portal(
    *,
    page_number: int | str | None = 1,
    per_page: int = 20,
) -> ProcessamentosPortalResumo:
    """Retorna somente dados operacionais seguros dos processamentos."""
    queryset = (
        Processamento.objects.select_related("agente")
        .prefetch_related("documentos", "documentos_saida", "execucoes_ia")
        .order_by("-iniciado_em", "-created_at")
    )
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(page_number)
    processamentos_brutos = [
        reconciliar_processamento_orfao(p) for p in page_obj.object_list
    ]
    processamentos = [
        ProcessamentoResumo(
            codigo=processamento.codigo,
            status=processamento.get_status_display(),
            status_codigo=processamento.status,
            agente=str(processamento.agente),
            origem=processamento.get_input_source_type_display(),
            formato_saida=_resolver_formato_saida_exibido(processamento),
            total_documentos=processamento.total_documentos,
            total_processados=processamento.total_processados,
            total_tokens=processamento.total_tokens,
            percentual=_calcular_percentual(processamento),
            duracao_minutos=_duracao_minutos(processamento.duracao_processamento_ms),
            iniciado_em=processamento.iniciado_em,
            finalizado_em=processamento.finalizado_em,
            etapa_atual=processamento.etapa_atual,
            documento_atual_nome=processamento.documento_atual_nome,
            ultima_atividade_em=processamento.ultima_atividade_em,
            ultima_atividade_humanizada=_ultima_atividade_humanizada(processamento),
            possivel_travamento=_possivel_travamento(processamento),
            erro_operacional=_erro_operacional(processamento),
            arquivo_saida_nome=processamento.arquivo_saida_nome,
            download_saida_url=reverse(
                "portal_processamento_download_saida",
                kwargs={"codigo": processamento.codigo},
            ),
            tem_arquivo_saida=bool(processamento.arquivo_saida),
        )
        for processamento in processamentos_brutos
    ]

    em_andamento_statuses = {
        ProcessingStatus.CRIADO,
        ProcessingStatus.EM_FILA,
        ProcessingStatus.EM_PROCESSAMENTO,
    }

    return ProcessamentosPortalResumo(
        processamentos=processamentos,
        total=paginator.count,
        em_andamento=Processamento.objects.filter(
            status__in=em_andamento_statuses
        ).count(),
        concluidos=Processamento.objects.filter(
            status=ProcessingStatus.CONCLUIDO_SUCESSO
        ).count(),
        com_erro=Processamento.objects.filter(
            status=ProcessingStatus.CONCLUIDO_ERRO
        ).count(),
        pagina_atual=page_obj.number,
        total_paginas=paginator.num_pages,
        itens_por_pagina=per_page,
        primeiro_item=page_obj.start_index() if paginator.count else 0,
        ultimo_item=page_obj.end_index() if paginator.count else 0,
        tem_pagina_anterior=page_obj.has_previous(),
        tem_proxima_pagina=page_obj.has_next(),
        pagina_anterior=page_obj.previous_page_number()
        if page_obj.has_previous()
        else None,
        proxima_pagina=page_obj.next_page_number() if page_obj.has_next() else None,
        paginas=[
            "..." if isinstance(page, str) else page
            for page in paginator.get_elided_page_range(
                page_obj.number,
                on_each_side=2,
                on_ends=1,
            )
        ],
    )


def _resolver_formato_saida_exibido(processamento: Processamento) -> str:
    if processamento.arquivo_saida_formato:
        display_map = dict(ProcessingOutputFormat.choices)
        return display_map.get(
            processamento.arquivo_saida_formato,
            processamento.arquivo_saida_formato.upper(),
        )
    return processamento.get_output_format_display()


def obter_status_processamento_para_portal(codigo: str) -> ProcessamentoStatusPortal:
    processamento = reconciliar_processamento_orfao(
        get_object_or_404(Processamento, codigo=codigo)
    )
    total_documentos = _total_documentos(processamento)
    total_processados = _total_processados(processamento)
    percentual = _calcular_percentual(processamento)

    return ProcessamentoStatusPortal(
        codigo=processamento.codigo,
        status=processamento.get_status_display(),
        status_codigo=processamento.status,
        origem=processamento.get_input_source_type_display(),
        formato_saida=_resolver_formato_saida_exibido(processamento),
        total_documentos=total_documentos,
        total_processados=total_processados,
        total_tokens=processamento.total_tokens,
        percentual=percentual,
        duracao_minutos=_duracao_minutos(processamento.duracao_processamento_ms),
        iniciado_em=_format_datetime(processamento.iniciado_em),
        finalizado_em=_format_datetime(processamento.finalizado_em),
        mensagem_erro=_erro_operacional(processamento),
        etapa_atual=processamento.etapa_atual,
        documento_atual_nome=processamento.documento_atual_nome,
        ultima_atividade_em=(
            processamento.ultima_atividade_em.isoformat()
            if processamento.ultima_atividade_em
            else ""
        ),
        ultima_atividade_humanizada=_ultima_atividade_humanizada(processamento),
        possivel_travamento=_possivel_travamento(processamento),
        tem_arquivo_saida=bool(processamento.arquivo_saida),
        download_saida_url=reverse(
            "portal_processamento_download_saida",
            kwargs={"codigo": processamento.codigo},
        ),
        resumo_total=Processamento.objects.count(),
        resumo_em_andamento=Processamento.objects.filter(
            status__in={
                ProcessingStatus.CRIADO,
                ProcessingStatus.EM_FILA,
                ProcessingStatus.EM_PROCESSAMENTO,
            }
        ).count(),
        resumo_concluidos=Processamento.objects.filter(
            status=ProcessingStatus.CONCLUIDO_SUCESSO
        ).count(),
        resumo_com_erro=Processamento.objects.filter(
            status=ProcessingStatus.CONCLUIDO_ERRO
        ).count(),
    )


def _total_documentos(processamento: Processamento) -> int:
    return processamento.total_documentos or processamento.documentos.count()


def _total_processados(processamento: Processamento) -> int:
    return processamento.total_processados or processamento.documentos.filter(
        status=DocumentStatus.PROCESSADO
    ).count()


def _calcular_percentual(processamento: Processamento) -> int:
    total_documentos = _total_documentos(processamento)
    total_processados = _total_processados(processamento)
    if not total_documentos:
        return 100 if processamento.status == ProcessingStatus.CONCLUIDO_SUCESSO else 0
    return min(round((total_processados / total_documentos) * 100), 100)


def _ultima_atividade_humanizada(processamento: Processamento) -> str:
    if not processamento.ultima_atividade_em:
        return "Nao informada"
    seconds = max(
        int((timezone.now() - processamento.ultima_atividade_em).total_seconds()),
        0,
    )
    if seconds < 5:
        return "Agora mesmo"
    if seconds < 60:
        return f"Ha {seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"Ha {minutes} min"
    hours = minutes // 60
    return f"Ha {hours} h"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return timezone.localtime(value).strftime("%d/%m/%Y %H:%M")


def _possivel_travamento(processamento: Processamento) -> bool:
    if processamento.status not in {
        ProcessingStatus.CRIADO,
        ProcessingStatus.EM_FILA,
        ProcessingStatus.EM_PROCESSAMENTO,
    }:
        return False
    if not processamento.ultima_atividade_em:
        return False
    return (
        timezone.now() - processamento.ultima_atividade_em
    ).total_seconds() >= STALL_SECONDS_THRESHOLD
