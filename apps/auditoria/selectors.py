from dataclasses import dataclass
from datetime import datetime

from django.core.paginator import Paginator
from django.db.models import Q
from django.utils import timezone

from apps.auditoria.models import EventoAuditoria


@dataclass(frozen=True)
class EventoAuditoriaResumo:
    id: int
    modulo: str
    acao: str
    actor: str
    objeto_tipo: str
    objeto_id: str
    descricao: str
    criado_em: datetime
    criado_em_formatado: str
    tempo_relativo: str
    tokens_total: int | None
    tokens_entrada: int | None
    tokens_processamento: int | None
    tokens_saida: int | None
    custo_brl: str | None


@dataclass(frozen=True)
class AuditoriaPortalResumo:
    eventos: list[EventoAuditoriaResumo]
    total: int
    hoje: int
    modulos_count: int
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
    modulos_disponiveis: list[str]
    filtro_modulo: str
    filtro_busca: str


def _tempo_relativo(criado_em: datetime) -> str:
    seconds = max(int((timezone.now() - criado_em).total_seconds()), 0)
    if seconds < 5:
        return "Agora mesmo"
    if seconds < 60:
        return f"Ha {seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"Ha {minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"Ha {hours} h"
    days = hours // 24
    return f"Ha {days} d"


def _montar_evento_resumo(e: EventoAuditoria) -> EventoAuditoriaResumo:
    return EventoAuditoriaResumo(
        id=e.id,
        modulo=e.modulo,
        acao=e.acao,
        actor=str(e.actor) if e.actor else "Sistema",
        objeto_tipo=e.objeto_tipo,
        objeto_id=e.objeto_id,
        descricao=e.descricao,
        criado_em=e.created_at,
        criado_em_formatado=timezone.localtime(e.created_at).strftime("%d/%m/%Y %H:%M"),
        tempo_relativo=_tempo_relativo(e.created_at),
        tokens_total=e.payload.get("total_tokens") if e.payload else None,
        tokens_entrada=e.payload.get("input_tokens") if e.payload else None,
        tokens_processamento=e.payload.get("processing_tokens") if e.payload else None,
        tokens_saida=e.payload.get("output_tokens") if e.payload else None,
        custo_brl=e.payload.get("custo_brl") if e.payload else None,
    )


def _montar_resumo_paginado(
    queryset,
    *,
    page_number,
    per_page: int,
    modulos_disponiveis: list[str],
    filtro_modulo: str = "",
    filtro_busca: str = "",
) -> AuditoriaPortalResumo:
    """Monta a paginacao + os EventoAuditoriaResumo de um queryset ja
    filtrado — extraido de listar_eventos_para_portal para ser reaproveitado
    por listar_eventos_do_processamento (ADR-001 Fase 3, v2.0.0) sem
    duplicar a logica de paginacao."""
    hoje_inicio = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    total_hoje = queryset.filter(created_at__gte=hoje_inicio).count()
    modulos_count = len(modulos_disponiveis)

    paginator = Paginator(queryset, per_page)
    page_obj = paginator.get_page(page_number)

    eventos = [_montar_evento_resumo(e) for e in page_obj.object_list]

    return AuditoriaPortalResumo(
        eventos=eventos,
        total=paginator.count,
        hoje=total_hoje,
        modulos_count=modulos_count,
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
        modulos_disponiveis=modulos_disponiveis,
        filtro_modulo=filtro_modulo,
        filtro_busca=filtro_busca,
    )


def listar_eventos_para_portal(
    *,
    page_number: int | str | None = 1,
    per_page: int = 25,
    filtro_modulo: str = "",
    filtro_busca: str = "",
) -> AuditoriaPortalResumo:
    queryset = EventoAuditoria.objects.select_related("actor").order_by("-created_at")

    if filtro_modulo:
        queryset = queryset.filter(modulo=filtro_modulo)

    if filtro_busca:
        queryset = queryset.filter(
            Q(descricao__icontains=filtro_busca)
            | Q(acao__icontains=filtro_busca)
            | Q(objeto_tipo__icontains=filtro_busca)
            | Q(objeto_id__icontains=filtro_busca)
        )

    modulos_disponiveis = list(
        EventoAuditoria.objects.values_list("modulo", flat=True)
        .distinct()
        .order_by("modulo")
    )

    return _montar_resumo_paginado(
        queryset,
        page_number=page_number,
        per_page=per_page,
        modulos_disponiveis=modulos_disponiveis,
        filtro_modulo=filtro_modulo,
        filtro_busca=filtro_busca,
    )


def listar_eventos_do_processamento(
    processamento, *, page_number: int | str | None = 1, per_page: int = 25
) -> AuditoriaPortalResumo:
    """Log proprio de UM processamento (ADR-001 Fase 3, v2.0.0) — mesmo
    padrao de listar_eventos_para_portal, sem os filtros de modulo/busca
    (a tela ja esta escopada a um unico processamento). Reaproveita
    EventoAuditoria, que ja tem FK processamento desde antes desta fase."""
    queryset = EventoAuditoria.objects.filter(processamento=processamento).select_related(
        "actor"
    ).order_by("-created_at")

    modulos_disponiveis = list(
        queryset.values_list("modulo", flat=True).distinct().order_by("modulo")
    )

    return _montar_resumo_paginado(
        queryset,
        page_number=page_number,
        per_page=per_page,
        modulos_disponiveis=modulos_disponiveis,
    )
