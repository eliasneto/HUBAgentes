from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse

from apps.agentes_ia.models import (
    AgenteIA,
    AgentInputPolicy,
    AgentStatus,
    AgentTriggerMode,
    AgentVisibility,
)
from apps.agentes_ia.services import calcular_disponibilidade_agente


@dataclass(frozen=True)
class AgenteLeituraResumo:
    id: int
    slug: str
    nome: str
    objetivo: str
    tipo: str
    categoria: str
    visibilidade: str
    status: str
    integracao_ia: str
    atualizado_em: datetime | None
    disponibilidade_estado: str
    disponibilidade_cor: str
    pode_executar: bool
    motivo_bloqueio: str
    executar_url: str
    editar_url: str
    permite_upload_execucao: bool


def _montar_resumos_agentes(queryset) -> list[AgenteLeituraResumo]:
    agentes_resumo = []
    for agente in queryset:
        disponibilidade = calcular_disponibilidade_agente(agente)
        permite_upload_execucao = _permite_upload_na_execucao(agente)
        agentes_resumo.append(
            AgenteLeituraResumo(
                id=agente.id,
                slug=agente.slug,
                nome=agente.nome,
                objetivo=agente.objetivo,
                tipo=agente.get_tipo_display(),
                categoria=agente.get_categoria_operacional_display(),
                visibilidade=agente.get_visibilidade_display(),
                status=agente.get_status_display(),
                integracao_ia=str(agente.ai_provider_integration),
                atualizado_em=getattr(agente, "updated_at", None),
                disponibilidade_estado=disponibilidade.estado,
                disponibilidade_cor=disponibilidade.cor,
                pode_executar=disponibilidade.pode_executar,
                motivo_bloqueio=disponibilidade.motivo,
                executar_url=reverse(
                    "portal_agente_executar",
                    kwargs={"slug": agente.slug},
                ),
                editar_url=reverse(
                    "portal_agente_editar",
                    kwargs={"slug": agente.slug},
                ),
                permite_upload_execucao=permite_upload_execucao,
            )
        )
    return agentes_resumo


def _permite_upload_na_execucao(agente):
    try:
        configuracao = agente.configuracao_operacional
    except ObjectDoesNotExist:
        return False

    return bool(
        configuracao.allow_runtime_file_upload
        and configuracao.input_policy == AgentInputPolicy.UPLOAD_NA_EXECUCAO
    )


def listar_agentes_para_portal() -> list[AgenteLeituraResumo]:
    """Retorna somente campos seguros para exibicao no Portal Operacional."""
    agentes = (
        AgenteIA.objects.select_related(
            "ai_provider_integration",
            "configuracao_operacional",
        )
        .filter(
            status=AgentStatus.ATIVO,
            visibilidade=AgentVisibility.USUARIO,
            modo_acionamento=AgentTriggerMode.PORTAL,
        )
        .order_by("nome")
    )
    return _montar_resumos_agentes(agentes)


def listar_agentes_para_gerenciamento() -> list[AgenteLeituraResumo]:
    agentes = AgenteIA.objects.select_related(
        "ai_provider_integration",
        "configuracao_operacional",
    ).order_by("nome")
    return _montar_resumos_agentes(agentes)
