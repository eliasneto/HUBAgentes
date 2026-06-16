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
    excluir_url: str
    permite_upload_execucao: bool
    tipo_entrada: str = ""
    nome_integracao_local: str = ""
    usuario_tem_acesso: bool = True


def _label_tipo_entrada(config) -> tuple[str, str]:
    """Retorna (label_tipo_entrada, nome_integracao_local)."""
    if not config:
        return "Sem configuracao", ""
    st = config.default_input_source_type
    if st == "local_folder":
        integ = config.default_local_storage_integration
        return "Pasta local", (integ.nome if integ else "—")
    if st == "google_drive_folder":
        fonte = config.default_folder_source
        return "Google Drive", (fonte.nome if fonte else "—")
    if st == "upload_at_execution":
        return "Upload na execucao", ""
    if st == "local_file":
        return "Arquivo local fixo", ""
    return "Sem origem documental", ""


def _usuario_pode_usar_entrada(agente, usuario) -> bool:
    """False quando o agente usa pasta local fixa e o usuário não tem acesso."""
    if usuario is None or usuario.is_superuser:
        return True
    config = getattr(agente, "configuracao_operacional", None)
    if not config:
        return True
    from apps.agentes_ia.models import AgentInputPolicy, AgentDefaultInputSourceType
    if config.input_policy != AgentInputPolicy.FIXA:
        return True
    if config.default_input_source_type != AgentDefaultInputSourceType.LOCAL_FOLDER:
        return True
    integ = config.default_local_storage_integration
    if not integ:
        return True
    if not integ.compartilhada:
        return integ.created_by_id == usuario.pk
    # Pasta compartilhada: qualquer membro autorizado pode ler
    from apps.integracoes.models import PastaCompartilhadaUsuario
    return PastaCompartilhadaUsuario.objects.filter(
        integracao=integ, usuario=usuario
    ).exists()


def _montar_resumos_agentes(queryset, usuario=None) -> list[AgenteLeituraResumo]:
    # V142-1/V142-2: contadores de concorrencia sao globais para a lista inteira;
    # calculados uma unica vez aqui para evitar N+1 dentro do loop.
    from apps.agentes_ia.services import EXECUTION_BLOCKING_STATUSES
    from apps.processamentos.models import Processamento

    execucoes_no_sistema = Processamento.objects.filter(
        status__in=EXECUTION_BLOCKING_STATUSES
    ).count()
    execucoes_do_usuario = (
        Processamento.objects.filter(
            iniciado_por=usuario,
            status__in=EXECUTION_BLOCKING_STATUSES,
        ).count()
        if usuario is not None
        else 0
    )

    agentes_resumo = []
    for agente in queryset:
        disponibilidade = calcular_disponibilidade_agente(
            agente,
            usuario,
            execucoes_no_sistema=execucoes_no_sistema,
            execucoes_do_usuario=execucoes_do_usuario,
        )
        permite_upload_execucao = _permite_upload_na_execucao(agente)
        config = getattr(agente, "configuracao_operacional", None)
        tipo_entrada, nome_integ = _label_tipo_entrada(config)
        tem_acesso = _usuario_pode_usar_entrada(agente, usuario)
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
                executar_url=reverse("portal_agente_executar", kwargs={"slug": agente.slug}),
                editar_url=reverse("portal_agente_editar", kwargs={"slug": agente.slug}),
                excluir_url=reverse("portal_agente_excluir", kwargs={"slug": agente.slug}),
                permite_upload_execucao=permite_upload_execucao,
                tipo_entrada=tipo_entrada,
                nome_integracao_local=nome_integ,
                usuario_tem_acesso=tem_acesso,
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


def listar_agentes_para_portal(usuario=None) -> list[AgenteLeituraResumo]:
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
    return _montar_resumos_agentes(agentes, usuario=usuario)


def listar_agentes_para_gerenciamento() -> list[AgenteLeituraResumo]:
    agentes = AgenteIA.objects.select_related(
        "ai_provider_integration",
        "configuracao_operacional",
    ).order_by("nome")
    return _montar_resumos_agentes(agentes)
