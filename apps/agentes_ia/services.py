import re
from dataclasses import dataclass

from django.db import transaction
from django.utils.text import slugify

from apps.agentes_ia.models import (
    AgenteConfiguracaoOperacional,
    AgenteIA,
    AgentDefaultInputSourceType,
    AgentInputPolicy,
    AgentOutputPolicy,
    AgentStatus,
    AgentTriggerMode,
    AgentVisibility,
)
from apps.integracoes.models import IntegrationStatus
from apps.processamentos.models import (
    Processamento,
    ProcessingInputSourceType,
    ProcessingStatus,
)


@dataclass(frozen=True)
class AgenteDisponibilidade:
    estado: str
    cor: str
    pode_executar: bool
    motivo: str


EXECUTION_BLOCKING_STATUSES = {
    ProcessingStatus.EM_FILA,
    ProcessingStatus.EM_PROCESSAMENTO,
}

PROMPT_VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def calcular_disponibilidade_agente(agente) -> AgenteDisponibilidade:
    """Calcula a disponibilidade operacional do agente para o portal."""
    if agente.visibilidade != AgentVisibility.USUARIO:
        return AgenteDisponibilidade(
            estado="indisponivel",
            cor="cinza",
            pode_executar=False,
            motivo="Agente tecnico nao aparece no painel operacional.",
        )

    if agente.modo_acionamento != AgentTriggerMode.PORTAL:
        return AgenteDisponibilidade(
            estado="indisponivel",
            cor="cinza",
            pode_executar=False,
            motivo="Agente configurado para acionamento fora do portal.",
        )

    if agente.status != AgentStatus.ATIVO:
        return AgenteDisponibilidade(
            estado="indisponivel",
            cor="cinza",
            pode_executar=False,
            motivo="Agente inativo ou pausado.",
        )

    if not agente.permite_execucao_manual:
        return AgenteDisponibilidade(
            estado="indisponivel",
            cor="cinza",
            pode_executar=False,
            motivo="Execucao manual desabilitada para este agente.",
        )

    integracao = agente.ai_provider_integration
    if integracao.status != IntegrationStatus.ATIVA:
        return AgenteDisponibilidade(
            estado="erro",
            cor="vermelho",
            pode_executar=False,
            motivo="Integracao de IA indisponivel.",
        )

    modelo = agente.modelo_preferencial or integracao.default_model
    if not modelo:
        return AgenteDisponibilidade(
            estado="erro",
            cor="vermelho",
            pode_executar=False,
            motivo="Modelo de IA nao configurado.",
        )

    bloqueio_configuracao = obter_bloqueio_execucao_padrao(agente)
    if bloqueio_configuracao:
        return AgenteDisponibilidade(
            estado="erro",
            cor="vermelho",
            pode_executar=False,
            motivo=bloqueio_configuracao,
        )

    em_execucao = Processamento.objects.filter(
        agente=agente,
        status__in=EXECUTION_BLOCKING_STATUSES,
    ).exists()
    if em_execucao:
        return AgenteDisponibilidade(
            estado="em_execucao",
            cor="amarelo",
            pode_executar=False,
            motivo="Existe uma execucao em andamento para este agente.",
        )

    return AgenteDisponibilidade(
        estado="liberado",
        cor="verde",
        pode_executar=True,
        motivo="Agente liberado para execucao.",
    )


def obter_ou_criar_configuracao_operacional(agente):
    configuracao, _ = AgenteConfiguracaoOperacional.objects.get_or_create(
        agente=agente
    )
    return configuracao


def normalizar_parametros_prompt(raw_parameters):
    if not isinstance(raw_parameters, list):
        return []

    normalized_parameters = []
    used_variables = set()
    for raw_parameter in raw_parameters:
        if not isinstance(raw_parameter, dict):
            continue

        campo = str(raw_parameter.get("campo", "")).strip()
        rotulo = str(raw_parameter.get("rotulo", "")).strip()
        if not campo and not rotulo:
            continue

        variable_base = _gerar_variavel_parametro(campo or rotulo)
        variable_name = variable_base
        counter = 2
        while variable_name in used_variables:
            variable_name = f"{variable_base}_{counter}"
            counter += 1

        used_variables.add(variable_name)
        normalized_parameters.append(
            {
                "campo": campo,
                "rotulo": rotulo,
                "variavel": variable_name,
            }
        )

    return normalized_parameters


def renderizar_prompt_com_parametros(prompt_base, prompt_parameters):
    values_by_variable = {
        parameter["variavel"]: parameter.get("campo", "")
        for parameter in normalizar_parametros_prompt(prompt_parameters)
        if parameter.get("variavel")
    }

    def replace_variable(match):
        variable_name = match.group(1)
        if variable_name not in values_by_variable:
            return match.group(0)
        return values_by_variable[variable_name]

    return PROMPT_VARIABLE_PATTERN.sub(replace_variable, prompt_base or "")


def obter_bloqueio_execucao_padrao(agente):
    configuracao = obter_ou_criar_configuracao_operacional(agente)
    source_type = _resolver_source_type_execucao_padrao(configuracao)

    if source_type == AgentDefaultInputSourceType.NONE:
        if configuracao.input_policy == AgentInputPolicy.SEM_ENTRADA:
            return ""
        return (
            "Agente sem origem documental padrao configurada. "
            "Atualize a configuracao operacional antes de executar."
        )

    if source_type == ProcessingInputSourceType.UPLOAD_AT_EXECUTION:
        if configuracao.allow_runtime_file_upload:
            return ""
        return (
            "Agente depende de upload informado na execucao, mas o upload operacional "
            "nao esta habilitado na configuracao do agente."
        )

    if source_type == ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER:
        if not configuracao.default_folder_source_id:
            return (
                "Agente sem pasta padrao do Google Drive configurada. "
                "Atualize a configuracao operacional antes de executar."
            )
        if configuracao.default_folder_source.status != IntegrationStatus.ATIVA:
            return "A pasta padrao do Google Drive deste agente esta inativa."
        if (
            configuracao.default_folder_source.google_drive_integration.status
            != IntegrationStatus.ATIVA
        ):
            return (
                "A integracao Google Drive da pasta padrao deste agente esta inativa."
            )
        return ""

    if source_type in {
        ProcessingInputSourceType.LOCAL_FOLDER,
        ProcessingInputSourceType.LOCAL_FILE,
    }:
        if not configuracao.default_local_storage_integration_id:
            return (
                "Agente sem storage local padrao configurado. "
                "Atualize a configuracao operacional antes de executar."
            )
        if not configuracao.default_local_relative_input_path:
            return (
                "Agente sem caminho local padrao configurado. "
                "Atualize a configuracao operacional antes de executar."
            )
        if (
            configuracao.default_local_storage_integration.status
            != IntegrationStatus.ATIVA
        ):
            return "O storage local padrao deste agente esta inativo."

    return ""


def montar_payload_execucao_padrao(agente):
    bloqueio = obter_bloqueio_execucao_padrao(agente)
    if bloqueio:
        raise ValueError(bloqueio)

    configuracao = obter_ou_criar_configuracao_operacional(agente)
    source_type = _resolver_source_type_execucao_padrao(configuracao)
    payload = {
        "input_source_type": source_type,
        "output_format": configuracao.default_output_format,
        "output_destination": configuracao.default_output_destination,
    }

    if source_type == ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER:
        payload["folder_source"] = configuracao.default_folder_source
    elif source_type in {
        ProcessingInputSourceType.LOCAL_FOLDER,
        ProcessingInputSourceType.LOCAL_FILE,
    }:
        payload["local_storage_integration"] = (
            configuracao.default_local_storage_integration
        )
        payload["local_relative_input_path"] = (
            configuracao.default_local_relative_input_path
        )

    return payload


def criar_agente_portal(
    *,
    actor,
    nome,
    tipo,
    categoria_operacional,
    visibilidade,
    modo_acionamento,
    status,
    objetivo,
    prompt_base,
    ai_provider_integration,
    modelo_preferencial,
    default_input_source_type,
    default_folder_source,
    default_local_storage_integration,
    default_local_relative_input_path,
    permitir_upload_na_execucao,
    default_output_format,
    default_output_destination,
    document_execution_mode,
    output_assembly_mode,
    output_packaging_mode,
    prompt_parameters,
):
    with transaction.atomic():
        agente = AgenteIA(
            nome=nome,
            slug=_gerar_slug_disponivel(nome),
            tipo=tipo,
            categoria_operacional=categoria_operacional,
            visibilidade=visibilidade,
            modo_acionamento=modo_acionamento,
            objetivo=objetivo,
            status=status,
            prompt_base=prompt_base,
            modelo_preferencial=modelo_preferencial,
            ai_provider_integration=ai_provider_integration,
            permite_execucao_manual=modo_acionamento == AgentTriggerMode.PORTAL,
            permite_clonagem=True,
            created_by=actor,
            updated_by=actor,
        )
        agente.full_clean()
        agente.save()

        configuracao = AgenteConfiguracaoOperacional(
            agente=agente,
            input_policy=_resolver_input_policy_padrao(
                default_input_source_type,
                permitir_upload_na_execucao=permitir_upload_na_execucao,
            ),
            default_input_source_type=default_input_source_type,
            default_folder_source=default_folder_source,
            default_local_storage_integration=default_local_storage_integration,
            default_local_relative_input_path=default_local_relative_input_path,
            allowed_input_extensions=["pdf"],
            allow_runtime_input_choice=False,
            allow_runtime_file_upload=permitir_upload_na_execucao,
            output_policy=AgentOutputPolicy.FIXA,
            default_output_format=default_output_format,
            default_output_destination=default_output_destination,
            allow_runtime_output_override=False,
            runtime_fields_schema={
                "show_input_source_type": False,
                "show_file_upload": permitir_upload_na_execucao,
                "show_output_format": False,
            },
            builder_schema={"origin": "portal"},
            document_execution_mode=document_execution_mode,
            output_assembly_mode=output_assembly_mode,
            output_packaging_mode=output_packaging_mode,
            prompt_parameters=normalizar_parametros_prompt(prompt_parameters),
            concurrency_policy=AgenteConfiguracaoOperacional._meta.get_field(
                "concurrency_policy"
            ).default(),
            created_by=actor,
            updated_by=actor,
        )
        configuracao.full_clean()
        configuracao.save()

    return agente


def atualizar_agente_portal(
    *,
    agente,
    actor,
    nome,
    tipo,
    categoria_operacional,
    visibilidade,
    modo_acionamento,
    status,
    objetivo,
    prompt_base,
    ai_provider_integration,
    modelo_preferencial,
    default_input_source_type,
    default_folder_source,
    default_local_storage_integration,
    default_local_relative_input_path,
    permitir_upload_na_execucao,
    default_output_format,
    default_output_destination,
    document_execution_mode,
    output_assembly_mode,
    output_packaging_mode,
    prompt_parameters,
):
    with transaction.atomic():
        agente.nome = nome
        agente.tipo = tipo
        agente.categoria_operacional = categoria_operacional
        agente.visibilidade = visibilidade
        agente.modo_acionamento = modo_acionamento
        agente.status = status
        agente.objetivo = objetivo
        agente.prompt_base = prompt_base
        agente.modelo_preferencial = modelo_preferencial
        agente.ai_provider_integration = ai_provider_integration
        agente.permite_execucao_manual = (
            modo_acionamento == AgentTriggerMode.PORTAL
        )
        agente.updated_by = actor
        agente.full_clean()
        agente.save()

        configuracao = obter_ou_criar_configuracao_operacional(agente)
        configuracao.input_policy = _resolver_input_policy_padrao(
            default_input_source_type,
            permitir_upload_na_execucao=permitir_upload_na_execucao,
        )
        configuracao.default_input_source_type = default_input_source_type
        configuracao.default_folder_source = default_folder_source
        configuracao.default_local_storage_integration = (
            default_local_storage_integration
        )
        configuracao.default_local_relative_input_path = (
            default_local_relative_input_path
        )
        configuracao.allowed_input_extensions = (
            configuracao.allowed_input_extensions or ["pdf"]
        )
        configuracao.allow_runtime_input_choice = False
        configuracao.allow_runtime_file_upload = permitir_upload_na_execucao
        configuracao.output_policy = AgentOutputPolicy.FIXA
        configuracao.default_output_format = default_output_format
        configuracao.default_output_destination = default_output_destination
        configuracao.allow_runtime_output_override = False
        configuracao.runtime_fields_schema = {
            "show_input_source_type": False,
            "show_file_upload": permitir_upload_na_execucao,
            "show_output_format": False,
        }
        configuracao.document_execution_mode = document_execution_mode
        configuracao.output_assembly_mode = output_assembly_mode
        configuracao.output_packaging_mode = output_packaging_mode
        configuracao.prompt_parameters = normalizar_parametros_prompt(
            prompt_parameters
        )
        builder_schema = dict(configuracao.builder_schema or {})
        builder_schema["origin"] = "portal"
        configuracao.builder_schema = builder_schema
        if not configuracao.concurrency_policy:
            configuracao.concurrency_policy = (
                AgenteConfiguracaoOperacional._meta.get_field(
                    "concurrency_policy"
                ).default()
            )
        configuracao.updated_by = actor
        configuracao.full_clean()
        configuracao.save()

    return agente


def clonar_agente(*, agente, actor, novo_nome=None):
    if not agente.permite_clonagem:
        raise ValueError("Este agente nao permite clonagem.")

    base_nome = novo_nome or f"Copia de {agente.nome}"
    with transaction.atomic():
        clone = type(agente).objects.create(
            nome=base_nome,
            slug=_gerar_slug_disponivel(base_nome),
            tipo=agente.tipo,
            categoria_operacional=agente.categoria_operacional,
            visibilidade=agente.visibilidade,
            modo_acionamento=agente.modo_acionamento,
            objetivo=agente.objetivo,
            status=AgentStatus.INATIVO,
            prompt_base=agente.prompt_base,
            prompt_version=agente.prompt_version,
            modelo_preferencial=agente.modelo_preferencial,
            parametros_execucao=agente.parametros_execucao,
            ai_provider_integration=agente.ai_provider_integration,
            permite_execucao_manual=agente.permite_execucao_manual,
            permite_clonagem=agente.permite_clonagem,
            clonado_de=agente,
            created_by=actor,
            updated_by=actor,
        )

        configuracao_origem = obter_ou_criar_configuracao_operacional(agente)
        AgenteConfiguracaoOperacional.objects.create(
            agente=clone,
            input_policy=configuracao_origem.input_policy,
            default_input_source_type=configuracao_origem.default_input_source_type,
            default_folder_source=configuracao_origem.default_folder_source,
            default_local_storage_integration=(
                configuracao_origem.default_local_storage_integration
            ),
            default_local_relative_input_path=(
                configuracao_origem.default_local_relative_input_path
            ),
            allowed_input_extensions=configuracao_origem.allowed_input_extensions,
            allow_runtime_input_choice=(
                configuracao_origem.allow_runtime_input_choice
            ),
            allow_runtime_file_upload=configuracao_origem.allow_runtime_file_upload,
            output_policy=configuracao_origem.output_policy,
            default_output_format=configuracao_origem.default_output_format,
            default_output_destination=configuracao_origem.default_output_destination,
            allow_runtime_output_override=(
                configuracao_origem.allow_runtime_output_override
            ),
            runtime_fields_schema=configuracao_origem.runtime_fields_schema,
            builder_schema=configuracao_origem.builder_schema,
            document_execution_mode=configuracao_origem.document_execution_mode,
            output_assembly_mode=configuracao_origem.output_assembly_mode,
            output_packaging_mode=configuracao_origem.output_packaging_mode,
            prompt_parameters=configuracao_origem.prompt_parameters,
            concurrency_policy=configuracao_origem.concurrency_policy,
            created_by=actor,
            updated_by=actor,
        )

    return clone


def _gerar_slug_clone(nome):
    return _gerar_slug_disponivel(nome, fallback="agente-clonado")


def _gerar_slug_disponivel(nome, fallback="agente"):
    base_slug = slugify(nome) or fallback
    slug = base_slug
    counter = 2
    while AgenteIA.objects.filter(slug=slug).exists():
        slug = f"{base_slug}-{counter}"
        counter += 1
    return slug


def _gerar_variavel_parametro(value):
    normalized_value = slugify(value).replace("-", "_")
    return normalized_value or "parametro"


def _resolver_source_type_execucao_padrao(configuracao):
    if configuracao.input_policy == AgentInputPolicy.SEM_ENTRADA:
        return ProcessingInputSourceType.NONE
    if configuracao.input_policy == AgentInputPolicy.UPLOAD_NA_EXECUCAO:
        return ProcessingInputSourceType.UPLOAD_AT_EXECUTION
    if configuracao.default_input_source_type:
        if configuracao.default_input_source_type == AgentDefaultInputSourceType.NONE:
            return ProcessingInputSourceType.NONE
        return configuracao.default_input_source_type
    return ProcessingInputSourceType.NONE


def _resolver_input_policy_padrao(
    default_input_source_type,
    *,
    permitir_upload_na_execucao=False,
):
    if default_input_source_type == AgentDefaultInputSourceType.NONE:
        if permitir_upload_na_execucao:
            return AgentInputPolicy.UPLOAD_NA_EXECUCAO
        return AgentInputPolicy.SEM_ENTRADA
    if default_input_source_type == AgentDefaultInputSourceType.UPLOAD_AT_EXECUTION:
        return AgentInputPolicy.UPLOAD_NA_EXECUCAO
    return AgentInputPolicy.FIXA
