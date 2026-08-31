from dataclasses import dataclass
from datetime import datetime, timedelta

from django.core.paginator import Paginator
from django.db.models import Count, Max, Prefetch
from django.urls import reverse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.processamentos.models import (
    DocumentoEntrada,
    DocumentStatus,
    ExecutionScopeType,
    OutputDocumentStatus,
    Processamento,
    ProcessamentoExecucaoIA,
    ProcessingOutputFormat,
    ProcessingStatus,
    RotinaAutomaticaExecucao,
)
from apps.processamentos.services.error_handling import (
    ERRO_TECNICO_OPERACIONAL,
    normalizar_erro_processamento,
)
from apps.processamentos.services.stalled_processing import (
    reconciliar_processamento_orfao,
)


@dataclass(frozen=True)
class DocumentoTokensResumo:
    nome_arquivo: str
    status: str
    total_tokens: int
    mensagem_erro: str = ""
    # Preenchido so no modo de entrada Individual (1 documento = 1 saida) e
    # so quando ESSE documento especifico ja foi processado com sucesso —
    # deixa o usuario baixar documentos prontos sem esperar o processamento
    # inteiro terminar. Vazio nos demais casos (Grupo/Lote por pasta, onde
    # a saida e consolidada e nao existe arquivo por documento; ou o
    # documento ainda nao processou/deu erro).
    download_url: str = ""


@dataclass(frozen=True)
class ProcessamentoResumo:
    codigo: str
    status: str
    status_codigo: str
    bloqueado_permanentemente: bool
    agente: str
    origem: str
    formato_saida: str
    total_documentos: int
    total_processados: int
    total_tokens: int | None
    input_tokens: int | None
    processing_tokens: int | None
    output_tokens: int | None
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
    documentos_tokens: list[DocumentoTokensResumo]


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
    filtrado_por_codigos: bool = False


@dataclass(frozen=True)
class ProcessamentoStatusPortal:
    codigo: str
    status: str
    status_codigo: str
    origem: str
    formato_saida: str
    total_documentos: int
    total_processados: int
    total_documentos_ignorados: int
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
    documentos_tokens: list[DocumentoTokensResumo]


# Investigacao em producao (16/08/2026, PROC-20260816204934-797C8A23) mostrou
# chamadas de IA legitimas (sem erro) levando ate 226s (gemini-2.5-pro) e 482s
# (claude-haiku-4.5) so aguardando a resposta do provedor — 180s gerava alerta
# de "possivel travamento" em execucoes saudaveis. Ver tambem o heartbeat em
# apps/processamentos/services/agent_execution.py (_AtividadeHeartbeat), que
# atualiza ultima_atividade_em durante a chamada e reduz a chance de o gap
# real chegar perto deste limiar.
STALL_SECONDS_THRESHOLD = 300

# Janela em que um processamento recem-concluido (sucesso/erro/atencao)
# continua aparecendo no indicador global, para o usuario ver o resultado
# final mesmo que tenha navegado para outra tela antes de terminar.
PROCESSAMENTOS_ATIVOS_JANELA_MINUTOS = 10


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


def _tokens_por_documento(processamento: Processamento) -> list[DocumentoTokensResumo]:
    """
    Quebra o total de tokens do processamento por documento, somando todas as
    tentativas de IA feitas para aquele documento (inclusive as que deram
    erro antes de um reprocessamento dar certo — reflete o custo real gasto
    com ele, mesmo criterio do "Tokens total" agregado do processamento).

    Opera em cima de `processamento.execucoes_ia.all()` — que precisa vir
    prefetched com `select_related("documento")` e
    `prefetch_related("documentos_entrada")` (ver Prefetch usado nos
    querysets abaixo) para nao disparar uma query nova por processamento.

    Execucoes em modo "Grupo"/"Lote por pasta" processam varios documentos
    numa unica chamada de IA — nesses casos nao existe um total individual
    por documento (o provedor retorna uso agregado da chamada inteira), entao
    a linha representa o grupo inteiro, com os nomes dos documentos juntos.

    `mensagem_erro` reflete o estado FINAL do documento (`DocumentoEntrada.
    mensagem_erro`), nao a tentativa que falhou no meio do caminho — ou seja,
    um documento que falhou na 1a tentativa mas passou na retentativa
    automatica de fim de lote (ver agent_execution._execute_documents_individually)
    aparece aqui sem mensagem, com status "Processado", refletindo so o
    resultado que realmente importa para quem esta acompanhando.

    `download_url` deixa baixar o arquivo de UM documento individual assim
    que ele termina, sem esperar o processamento inteiro (que pode ter
    dezenas de outros documentos ainda rodando) — usa
    `processamento.documentos_saida.all()`, que tambem precisa vir
    prefetched. So se aplica ao modo Individual: em "Grupo"/"Lote por
    pasta" a saida e consolidada, sem arquivo por documento.
    """
    status_labels = dict(DocumentStatus.choices)
    saida_por_documento = {
        saida.documento_id: saida
        for saida in processamento.documentos_saida.all()
        if saida.documento_id and saida.status == OutputDocumentStatus.GERADO
    }
    individuais: dict[int, dict] = {}
    grupos = []

    for execucao in processamento.execucoes_ia.all():
        tokens = execucao.total_tokens or 0
        if execucao.scope_type == ExecutionScopeType.INDIVIDUAL and execucao.documento_id:
            documento = execucao.documento
            download_url = ""
            if documento.status == DocumentStatus.PROCESSADO:
                saida = saida_por_documento.get(documento.id)
                if saida and saida.arquivo:
                    download_url = reverse(
                        "portal_processamento_download_documento",
                        kwargs={"codigo": processamento.codigo, "saida_id": saida.id},
                    )
            acumulado = individuais.setdefault(
                documento.id,
                {
                    "nome_arquivo": documento.nome_arquivo,
                    "status": status_labels.get(documento.status, ""),
                    "total_tokens": 0,
                    "mensagem_erro": (
                        documento.mensagem_erro
                        if documento.status == DocumentStatus.ERRO
                        else ""
                    ),
                    "download_url": download_url,
                },
            )
            acumulado["total_tokens"] += tokens
        elif execucao.scope_type == ExecutionScopeType.GRUPO:
            nomes = sorted(doc.nome_arquivo for doc in execucao.documentos_entrada.all())
            if nomes:
                grupos.append(
                    DocumentoTokensResumo(
                        nome_arquivo="Grupo: " + ", ".join(nomes),
                        status=execucao.get_status_display(),
                        total_tokens=tokens,
                    )
                )

    linhas = [
        DocumentoTokensResumo(**dados)
        for dados in sorted(individuais.values(), key=lambda d: d["nome_arquivo"])
    ]
    linhas.extend(grupos)
    return linhas


def listar_processamentos_para_portal(
    *,
    page_number: int | str | None = 1,
    per_page: int = 10,
    codigos: list[str] | None = None,
) -> ProcessamentosPortalResumo:
    """Retorna somente dados operacionais seguros dos processamentos.

    `codigos` (ADR-001 Fase 5b, v2.0.0): quando informado, mostra so os
    Processamentos com esses codigos — usado pelo redirect apos "Executar"
    num agente em modo Individual, que cria N Processamentos (1 por
    arquivo) num unico clique e precisa mostrar so o lote recem-criado."""
    queryset = (
        Processamento.objects.select_related("agente")
        .prefetch_related(
            "documentos",
            "documentos_saida",
            Prefetch(
                "execucoes_ia",
                queryset=ProcessamentoExecucaoIA.objects.select_related(
                    "documento"
                ).prefetch_related("documentos_entrada"),
            ),
        )
        .order_by("-iniciado_em", "-created_at")
    )
    if codigos:
        queryset = queryset.filter(codigo__in=codigos)
    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(page_number)
    processamentos = [
        ProcessamentoResumo(
            codigo=processamento.codigo,
            status=processamento.get_status_display(),
            status_codigo=processamento.status,
            bloqueado_permanentemente=processamento.bloqueado_permanentemente,
            agente=str(processamento.agente),
            origem=processamento.get_input_source_type_display(),
            formato_saida=_resolver_formato_saida_exibido(processamento),
            total_documentos=processamento.total_documentos,
            total_processados=processamento.total_processados,
            total_tokens=processamento.total_tokens,
            input_tokens=processamento.input_tokens,
            processing_tokens=processamento.processing_tokens,
            output_tokens=processamento.output_tokens,
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
            documentos_tokens=_tokens_por_documento(processamento),
        )
        for processamento in page_obj.object_list
    ]

    em_andamento_statuses = {
        ProcessingStatus.CRIADO,
        ProcessingStatus.EM_FILA,
        ProcessingStatus.EM_PROCESSAMENTO,
        # ADR-001 Fase 5b (v2.0.0): aguardando a proxima rotina automatica —
        # nao e nem "concluido" nem "com erro" ainda.
        ProcessingStatus.PENDENTE_RETENTATIVA,
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
        filtrado_por_codigos=bool(codigos),
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
    processamento = get_object_or_404(
        Processamento.objects.select_related("agente", "ai_provider_integration_snapshot")
        .prefetch_related(
            "documentos",
            "documentos_saida",
            Prefetch(
                "execucoes_ia",
                queryset=ProcessamentoExecucaoIA.objects.select_related(
                    "documento"
                ).prefetch_related("documentos_entrada"),
            ),
        ),
        codigo=codigo,
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
        total_documentos_ignorados=processamento.total_documentos_ignorados,
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
        documentos_tokens=_tokens_por_documento(processamento),
        **_resumo_counts(),
    )


@dataclass(frozen=True)
class ProcessamentoAtivoResumo:
    codigo: str
    agente: str
    status: str
    status_codigo: str
    percentual: int
    etapa_atual: str
    documento_atual_nome: str
    mensagem_erro: str
    finalizado: bool
    status_endpoint: str


def listar_processamentos_ativos_do_usuario(
    usuario, *, limite: int = 5
) -> list[ProcessamentoAtivoResumo]:
    """Processamentos do usuario em andamento ou concluidos ha pouco tempo.

    Alimenta o indicador global de progresso (visivel em qualquer tela do
    portal via `_portal_sidebar.html`), para que o usuario nao perca a visao
    de uma execucao ao navegar para outra pagina.
    """
    from django.db.models import Q

    em_andamento_statuses = {
        ProcessingStatus.CRIADO,
        ProcessingStatus.EM_FILA,
        ProcessingStatus.EM_PROCESSAMENTO,
        # ADR-001 Fase 5b (v2.0.0): aguardando a proxima rotina automatica —
        # nao e nem "concluido" nem "com erro" ainda.
        ProcessingStatus.PENDENTE_RETENTATIVA,
    }
    recem_finalizado_desde = timezone.now() - timedelta(
        minutes=PROCESSAMENTOS_ATIVOS_JANELA_MINUTOS
    )
    queryset = (
        Processamento.objects.select_related("agente")
        .prefetch_related("documentos", "documentos_saida", "execucoes_ia")
        .filter(iniciado_por=usuario)
        .filter(
            Q(status__in=em_andamento_statuses)
            | Q(finalizado_em__gte=recem_finalizado_desde)
        )
        .order_by("-iniciado_em")[:limite]
    )
    return [
        ProcessamentoAtivoResumo(
            codigo=processamento.codigo,
            agente=str(processamento.agente) if processamento.agente_id else "",
            status=processamento.get_status_display(),
            status_codigo=processamento.status,
            percentual=_calcular_percentual(processamento),
            etapa_atual=processamento.etapa_atual,
            documento_atual_nome=processamento.documento_atual_nome,
            mensagem_erro=_erro_operacional(processamento),
            finalizado=processamento.status not in em_andamento_statuses,
            status_endpoint=reverse(
                "portal_processamento_status",
                kwargs={"codigo": processamento.codigo},
            ),
        )
        for processamento in queryset
    ]


def _resumo_counts() -> dict:
    from django.db.models import Case, When, IntegerField, Sum, Value
    result = Processamento.objects.aggregate(
        resumo_total=Sum(Value(1), output_field=IntegerField()),
        resumo_em_andamento=Sum(
            Case(
                When(status__in=[ProcessingStatus.CRIADO, ProcessingStatus.EM_FILA, ProcessingStatus.EM_PROCESSAMENTO], then=1),
                default=0, output_field=IntegerField(),
            )
        ),
        resumo_concluidos=Sum(
            Case(When(status=ProcessingStatus.CONCLUIDO_SUCESSO, then=1), default=0, output_field=IntegerField())
        ),
        resumo_com_erro=Sum(
            Case(When(status=ProcessingStatus.CONCLUIDO_ERRO, then=1), default=0, output_field=IntegerField())
        ),
    )
    return {k: (v or 0) for k, v in result.items()}


def _total_documentos(processamento: Processamento) -> int:
    return processamento.total_documentos or processamento.documentos.count()


def _total_processados(processamento: Processamento) -> int:
    return processamento.total_processados or processamento.documentos.filter(
        status=DocumentStatus.PROCESSADO
    ).count()


_STATUS_TERMINAIS_100_POR_CENTO = {
    ProcessingStatus.CONCLUIDO_SUCESSO,
    ProcessingStatus.CONCLUIDO_ERRO,
    ProcessingStatus.CONCLUIDO_ATENCAO,
    ProcessingStatus.CANCELADO,
}


def _calcular_percentual(processamento: Processamento) -> int:
    if processamento.status in _STATUS_TERMINAIS_100_POR_CENTO:
        # O ciclo deste Processamento ja terminou — 100% significa "todo o
        # processamento que ia rodar, rodou", nao "todo documento teve
        # sucesso". Sem isso, um Processamento individual (1 documento, ver
        # ADR-001 Fase 5b) que terminasse em erro ficava com a barra de
        # progresso zerada para sempre, como se nada tivesse acontecido —
        # mesmo apos rodar o processo inteiro (relatado testando no
        # servidor local, 30/08/2026). PENDENTE_RETENTATIVA fica de fora de
        # proposito: ainda vai rodar de novo, 100% seria enganoso ali.
        return 100
    total_documentos = _total_documentos(processamento)
    total_processados = _total_processados(processamento)
    if not total_documentos:
        return 0
    # Enquanto o documento em andamento ainda nao terminou, soma a fracao do
    # sub-progresso dele (0-100, ver Processamento.progresso_etapa_percentual
    # e agent_execution._registrar_progresso_etapa) para o indicador avancar
    # de forma continua durante o pre-processamento de PDF, em vez de saltar
    # direto de 0% para 100% num processamento de 1 documento so.
    fracao_documento_atual = 0.0
    if (
        processamento.status == ProcessingStatus.EM_PROCESSAMENTO
        and total_processados < total_documentos
    ):
        percentual_etapa = max(0, min(processamento.progresso_etapa_percentual or 0, 100))
        fracao_documento_atual = percentual_etapa / 100
    progresso = total_processados + fracao_documento_atual
    return min(round((progresso / total_documentos) * 100), 100)


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


@dataclass(frozen=True)
class ProcessamentoDaRodadaResumo:
    """ADR-001 Fase 5b (v2.0.0): um dos N Processamentos (1 por arquivo)
    ligados a uma rodada da rotina automatica de um agente Individual —
    ver Processamento.rotina_automatica_execucao (FK nova da Fase 5a)."""
    codigo: str
    status_label: str


@dataclass(frozen=True)
class RotinaAutomaticaExecucaoResumo:
    id: int
    agente_nome: str
    status: str
    status_label: str
    iniciado_em_formatado: str
    finalizado_em_formatado: str
    total_documentos: int
    total_sucesso: int
    total_erro: int
    total_pendente: int
    motivo: str
    processamento_codigo: str
    processamentos_da_rodada: list[ProcessamentoDaRodadaResumo]


@dataclass(frozen=True)
class RotinaAutomaticaHistoricoResumo:
    execucoes: list[RotinaAutomaticaExecucaoResumo]
    total: int
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
    agentes_disponiveis: list
    filtro_agente: str
    filtro_status: str


def listar_historico_rotina_automatica(
    *,
    page_number: int | str | None = 1,
    per_page: int = 10,
    filtro_agente: str = "",
    filtro_status: str = "",
) -> RotinaAutomaticaHistoricoResumo:
    """Historico de tentativas da rotina automatica (ver
    executar_rotinas_automaticas_agentes), para a tela Administrador >
    Rotina automatica de agentes."""
    queryset = (
        RotinaAutomaticaExecucao.objects.select_related("agente", "processamento")
        .prefetch_related("processamentos_da_rodada")
        .order_by("-iniciado_em")
    )

    if filtro_agente:
        queryset = queryset.filter(agente_id=filtro_agente)
    if filtro_status:
        queryset = queryset.filter(status=filtro_status)

    agentes_disponiveis = list(
        RotinaAutomaticaExecucao.objects.select_related("agente")
        .values_list("agente_id", "agente__nome")
        .distinct()
        .order_by("agente__nome")
    )

    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(page_number)

    status_labels = dict(RotinaAutomaticaExecucao._meta.get_field("status").choices)

    execucoes = [
        RotinaAutomaticaExecucaoResumo(
            id=execucao.id,
            agente_nome=execucao.agente.nome,
            status=execucao.status,
            status_label=status_labels.get(execucao.status, execucao.status),
            iniciado_em_formatado=_format_datetime(execucao.iniciado_em),
            finalizado_em_formatado=_format_datetime(execucao.finalizado_em),
            total_documentos=execucao.total_documentos,
            total_sucesso=execucao.total_sucesso,
            total_erro=execucao.total_erro,
            total_pendente=execucao.total_pendente,
            motivo=execucao.motivo,
            processamento_codigo=(
                execucao.processamento.codigo if execucao.processamento_id else ""
            ),
            processamentos_da_rodada=[
                ProcessamentoDaRodadaResumo(
                    codigo=p.codigo, status_label=p.get_status_display()
                )
                for p in execucao.processamentos_da_rodada.all()
            ],
        )
        for execucao in page_obj.object_list
    ]

    return RotinaAutomaticaHistoricoResumo(
        execucoes=execucoes,
        total=paginator.count,
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
        agentes_disponiveis=agentes_disponiveis,
        filtro_agente=filtro_agente,
        filtro_status=filtro_status,
    )


@dataclass(frozen=True)
class DocumentoProcessadoResumo:
    """1 linha = 1 NOME de arquivo (identidade do documento — mesma regra
    de negocio de document_sources._arquivo_ja_processado_em_outra_
    execucao: o nome e a chave, nao o conteudo). Agrega todos os
    Processamentos, de qualquer agente, que tiveram um DocumentoEntrada
    com esse nome — N processamentos para 1 documento."""
    nome_arquivo: str
    agentes: str
    total_processamentos: int
    status_mais_recente: str
    status_mais_recente_codigo: str
    pode_reprocessar: bool
    ultima_execucao_formatada: str
    ver_processamentos_url: str


@dataclass(frozen=True)
class DocumentosProcessadosPortalResumo:
    documentos: list[DocumentoProcessadoResumo]
    total: int
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
    filtro_busca: str
    filtro_agente: str
    agentes_disponiveis: list


def listar_documentos_processados_para_portal(
    *,
    page_number: int | str | None = 1,
    per_page: int = 10,
    filtro_busca: str = "",
    filtro_agente: str = "",
) -> DocumentosProcessadosPortalResumo:
    """Tela "Documentos Processados": 1 linha por NOME de documento, com
    quantos Processamentos diferentes tiveram um arquivo com esse nome e um
    link para ve-los filtrados (reaproveita o filtro ?codigos= que
    ProcessamentosView ja suporta desde a Fase 5b do ADR-001).

    `pode_reprocessar=False` so quando algum DocumentoEntrada com esse nome
    ja chegou a PROCESSADO (concluido com sucesso) — espelha a regra de
    negocio "documento concluido com sucesso nao e reprocessado, so se
    mudar de nome" ja aplicada na descoberta de documentos (ver
    document_sources._arquivo_ja_processado_em_outra_execucao). Esta tela e
    so leitura/consulta; a aplicacao real da regra continua la, escopada
    por (agente, pasta) — aqui a aproximacao e global por nome, de proposito
    mais simples, so para informar o usuario."""
    queryset = DocumentoEntrada.objects.exclude(nome_arquivo="")
    if filtro_busca:
        queryset = queryset.filter(nome_arquivo__icontains=filtro_busca)
    if filtro_agente:
        queryset = queryset.filter(processamento__agente_id=filtro_agente)

    agrupado = (
        queryset.values("nome_arquivo")
        .annotate(
            total_entradas=Count("id"),
            ultima_execucao=Max("processamento__iniciado_em"),
        )
        .order_by("-ultima_execucao", "nome_arquivo")
    )

    paginator = Paginator(agrupado, per_page)
    page_obj = paginator.get_page(page_number)

    agentes_disponiveis = list(
        DocumentoEntrada.objects.select_related("processamento__agente")
        .exclude(processamento__agente_id=None)
        .values_list("processamento__agente_id", "processamento__agente__nome")
        .distinct()
        .order_by("processamento__agente__nome")
    )

    status_labels = dict(DocumentoEntrada._meta.get_field("status").choices)

    documentos = []
    for row in page_obj.object_list:
        nome = row["nome_arquivo"]
        entradas_qs = DocumentoEntrada.objects.filter(
            nome_arquivo=nome
        ).select_related("processamento", "processamento__agente")
        if filtro_agente:
            entradas_qs = entradas_qs.filter(processamento__agente_id=filtro_agente)
        entradas = list(
            entradas_qs.order_by("-processamento__iniciado_em", "-created_at")
        )

        agentes_nomes = []
        codigos = []
        for entrada in entradas:
            processamento = entrada.processamento
            if not processamento:
                continue
            if processamento.agente and processamento.agente.nome not in agentes_nomes:
                agentes_nomes.append(processamento.agente.nome)
            if processamento.codigo not in codigos:
                codigos.append(processamento.codigo)

        mais_recente = entradas[0] if entradas else None
        pode_reprocessar = not any(
            entrada.status == DocumentStatus.PROCESSADO for entrada in entradas
        )

        documentos.append(
            DocumentoProcessadoResumo(
                nome_arquivo=nome,
                agentes=", ".join(agentes_nomes) if agentes_nomes else "—",
                total_processamentos=len(codigos),
                status_mais_recente=(
                    status_labels.get(mais_recente.status, mais_recente.status)
                    if mais_recente
                    else "—"
                ),
                status_mais_recente_codigo=mais_recente.status if mais_recente else "",
                pode_reprocessar=pode_reprocessar,
                ultima_execucao_formatada=_format_datetime(row["ultima_execucao"]),
                ver_processamentos_url=(
                    reverse("portal_processamentos") + "?codigos=" + ",".join(codigos)
                    if codigos
                    else reverse("portal_processamentos")
                ),
            )
        )

    return DocumentosProcessadosPortalResumo(
        documentos=documentos,
        total=paginator.count,
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
        filtro_busca=filtro_busca,
        filtro_agente=filtro_agente,
        agentes_disponiveis=agentes_disponiveis,
    )
