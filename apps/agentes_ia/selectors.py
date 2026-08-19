from dataclasses import dataclass
from datetime import datetime

from django.core.exceptions import ObjectDoesNotExist
from django.urls import reverse

from apps.agentes_ia.models import (
    AgenteIA,
    AgentDefaultInputSourceType,
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
    formato_saida: str = ""
    permite_forcar_reprocessamento: bool = False
    caminho_origem: str = ""
    inclui_subpastas: bool = False


def _label_formato_saida(config) -> str:
    if not config:
        return ""
    return config.get_default_output_format_display() or ""


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


def _caminho_origem_pasta(config) -> str:
    """Retorna o caminho completo da pasta de origem dos PDFs, para o
    usuario conferir visualmente antes de confirmar a execucao.

    So se aplica quando a origem padrao e uma pasta (local ou Google
    Drive) — nos demais casos (upload na execucao, arquivo fixo, sem
    origem) retorna vazio e o modal simplesmente nao exibe o campo.

    Monta a string apenas concatenando o que ja esta cadastrado, sem
    nenhum acesso a filesystem/rede — a tela de listagem nao pode
    depender da pasta (local ou de rede) estar acessivel no momento.
    """
    if not config:
        return ""
    st = config.default_input_source_type
    if st == AgentDefaultInputSourceType.LOCAL_FOLDER:
        integ = config.default_local_storage_integration
        if not integ or not integ.base_path:
            return ""
        base = integ.base_path.rstrip("/\\")
        relativo = (config.default_local_relative_input_path or "").strip().strip("/\\")
        if not relativo:
            return base
        separador = "\\" if "\\" in base else "/"
        return f"{base}{separador}{relativo.replace('/', separador)}"
    if st == AgentDefaultInputSourceType.GOOGLE_DRIVE_FOLDER:
        fonte = config.default_folder_source
        if not fonte:
            return ""
        partes = [fonte.folder_display_name or fonte.nome]
        for item in config.default_gdrive_subfolder_path or []:
            nome = item.get("nome") if isinstance(item, dict) else None
            if nome:
                partes.append(nome)
        return " / ".join(p for p in partes if p)
    return ""


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
        formato_saida = _label_formato_saida(config)
        permite_forcar_reprocessamento = _permite_forcar_reprocessamento(config)
        caminho_origem = _caminho_origem_pasta(config)
        inclui_subpastas = bool(config and config.include_subfolders)
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
                formato_saida=formato_saida,
                permite_forcar_reprocessamento=permite_forcar_reprocessamento,
                caminho_origem=caminho_origem,
                inclui_subpastas=inclui_subpastas,
            )
        )
    return agentes_resumo


def _permite_forcar_reprocessamento(config) -> bool:
    """
    True quando a origem padrao do agente e uma pasta (Google Drive ou
    Local) — os unicos casos em que o rastreamento de "arquivo ja
    processado" se aplica, e por isso os unicos em que a opcao de forcar
    reprocessamento faz sentido.
    """
    if not config:
        return False
    return config.default_input_source_type in {
        AgentDefaultInputSourceType.GOOGLE_DRIVE_FOLDER,
        AgentDefaultInputSourceType.LOCAL_FOLDER,
    }


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
