from datetime import timedelta
from secrets import token_hex

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.agentes_ia.models import AgenteConfiguracaoOperacional
from apps.agentes_ia.services import calcular_disponibilidade_agente
from apps.agentes_ia.services import obter_ou_criar_configuracao_operacional
from apps.agentes_ia.services import renderizar_prompt_com_parametros
from apps.integracoes.services.ai_providers import AIProviderServiceError
from apps.integracoes.services.google_drive import GoogleDriveServiceError
from apps.integracoes.services.local_storage import LocalStorageServiceError
from apps.processamentos.models import (
    DocumentStatus,
    Processamento,
    ProcessingInputSourceType,
    ProcessingStatus,
    RotinaAutomaticaExecucao,
    RotinaAutomaticaExecucaoStatus,
)
from apps.processamentos.services.agent_execution import (
    ProcessamentoExecutionError,
    execute_processing,
)
from apps.processamentos.services.document_sources import DocumentSourcePreparationError
from apps.processamentos.services.error_handling import normalizar_erro_processamento
from apps.processamentos.services.output_packaging import OutputPackagingError
from apps.processamentos.services.output_renderers import OutputRendererError


class OperationalExecutionError(Exception):
    pass


# Trava de concorrencia por agente ficando presa (ex.: processo morto pelo
# timeout do gunicorn no meio de uma execucao, sem chance de rodar o
# finally) nao pode bloquear o agente para sempre — destrava sozinha apos
# esse tempo. Generoso o bastante para um lote normal (mesmo com
# retentativas) terminar antes, mas nao tão longo que um agente fique
# preso o dia inteiro por um unico crash.
LIMITE_TRAVA_EXECUCAO_MINUTOS = 20


def _bloqueia_execucao_paralela(agente):
    configuracao = getattr(agente, "configuracao_operacional", None)
    if configuracao is None:
        return True
    policy = configuracao.concurrency_policy or {}
    return bool(policy.get("block_parallel_per_agent", True))


def _tentar_adquirir_trava_execucao(configuracao):
    """Marca o agente como 'em execucao' de forma atomica (UPDATE
    condicional — nao precisa manter transacao aberta pelo tempo todo da
    execucao, que pode levar minutos). Devolve True se conseguiu (ninguem
    mais estava executando este agente), False se ja tinha alguem rodando.
    Considera a trava liberável se estiver presa ha mais de
    LIMITE_TRAVA_EXECUCAO_MINUTOS (auto-recuperacao de crash)."""
    agora = timezone.now()
    limite = agora - timedelta(minutes=LIMITE_TRAVA_EXECUCAO_MINUTOS)
    linhas = (
        AgenteConfiguracaoOperacional.objects.filter(pk=configuracao.pk)
        .filter(
            models.Q(execucao_em_andamento=False)
            | models.Q(execucao_em_andamento_desde__lt=limite)
        )
        .update(execucao_em_andamento=True, execucao_em_andamento_desde=agora)
    )
    return linhas == 1


def _liberar_trava_execucao(configuracao):
    AgenteConfiguracaoOperacional.objects.filter(pk=configuracao.pk).update(
        execucao_em_andamento=False, execucao_em_andamento_desde=None
    )


def criar_e_iniciar_processamento_para_agente(
    *, agente, actor, cleaned_data, limite_documentos_por_execucao=None
):
    disponibilidade = calcular_disponibilidade_agente(agente, actor)
    if not disponibilidade.pode_executar:
        raise OperationalExecutionError(disponibilidade.motivo)

    configuracao = obter_ou_criar_configuracao_operacional(agente)
    trava_exige_verificacao = _bloqueia_execucao_paralela(agente)
    if trava_exige_verificacao and not _tentar_adquirir_trava_execucao(configuracao):
        # Alguem ja esta executando este agente agora (clique manual e a
        # rotina automatica coincidindo, por exemplo) — nao enfileira uma
        # segunda execucao disputando os mesmos documentos pendentes e
        # duplicando custo de IA.
        raise OperationalExecutionError(
            "Este agente ja esta em execucao agora. Aguarde terminar antes "
            "de executar de novo."
        )

    try:
        processamento = _criar_processamento(
            agente=agente,
            actor=actor,
            cleaned_data=cleaned_data,
        )

        processamento.status = ProcessingStatus.EM_FILA
        processamento.mensagem_erro = ""
        processamento.mensagem_erro_tecnico = ""
        processamento.etapa_atual = "Aguardando inicio da execucao"
        processamento.documento_atual_nome = ""
        processamento.ultima_atividade_em = timezone.now()
        processamento.save(
            update_fields=[
                "status",
                "mensagem_erro",
                "mensagem_erro_tecnico",
                "etapa_atual",
                "documento_atual_nome",
                "ultima_atividade_em",
                "updated_at",
            ]
        )

        try:
            execute_processing(
                processamento,
                actor,
                limite_documentos_por_execucao=limite_documentos_por_execucao,
            )
        except (
            AIProviderServiceError,
            GoogleDriveServiceError,
            LocalStorageServiceError,
            DocumentSourcePreparationError,
            ProcessamentoExecutionError,
            OutputRendererError,
            OutputPackagingError,
        ) as exc:
            mensagem_operacional, mensagem_tecnica = normalizar_erro_processamento(exc)
            erro_operacional = OperationalExecutionError(mensagem_operacional)
            if getattr(exc, "sem_trabalho", False):
                _finalizar_processamento_sem_trabalho(processamento, mensagem_operacional, mensagem_tecnica)
                # Processamento foi soft-deleted acima — nao anexa (ver
                # SoftDeleteModel), so sinaliza a condicao. Quem chama
                # (ex.: executar_rotinas_automaticas_agentes) usa isso pra
                # registrar "sem documentos novos" no historico, sem tentar
                # acessar um Processamento ja soft-deleted.
                erro_operacional.sem_trabalho = True
            else:
                _finalizar_processamento_com_erro(processamento, mensagem_operacional, mensagem_tecnica)
                # Processamento chegou a rodar (mesmo terminando em erro) —
                # anexa pra quem chama poder contar documentos/motivos sem
                # precisar re-buscar (ex.: historico da rotina automatica).
                erro_operacional.processamento = processamento
            raise erro_operacional from exc
        except Exception as exc:
            # Fallback para exceções não mapeadas (DatabaseError, MemoryError, etc.)
            # Garante que o processamento nunca fica preso em EM_PROCESSAMENTO.
            _finalizar_processamento_com_erro(
                processamento,
                "Ocorreu um erro inesperado durante a execucao do agente.",
                str(exc),
            )
            erro_operacional = OperationalExecutionError(
                "Ocorreu um erro inesperado durante a execucao do agente."
            )
            erro_operacional.processamento = processamento
            raise erro_operacional from exc
    finally:
        if trava_exige_verificacao:
            _liberar_trava_execucao(configuracao)

    processamento.refresh_from_db()
    return processamento


def executar_rotinas_automaticas_agentes():
    """Ponto de entrada chamado periodicamente pelo worker (ver management
    command executar_rotinas_automaticas_agentes e docker-compose.yml).

    O interruptor geral, o intervalo entre rodadas e quantos documentos
    cada rodada processa sao todos GLOBAIS (ver ConfiguracaoGeral.
    rotina_automatica_agentes_ativa/rotina_automatica_intervalo_minutos/
    rotina_automatica_lote_tamanho, editaveis em Administrador > Rotina
    automatica) — cada agente so decide, individualmente, SE participa
    (AgenteConfiguracaoOperacional.execucao_automatica_ativa). Quando o
    interruptor geral esta desligado, a rotina nao roda para nenhum
    agente, mesmo que ele tenha a participacao ativada. Quando o
    intervalo global e menor que 30 minutos, cada rodada processa no
    maximo 6 documentos por agente, por seguranca, ignorando o lote
    global configurado.

    A primeira rodada apos essa configuracao ser salva respeita
    ConfiguracaoGeral.rotina_automatica_inicio_em, se configurado (ex.:
    "20/08/2026 as 19:20") — antes desse horario, a rotina nao roda. A
    partir da primeira rodada, as demais seguem so o intervalo, ignorando
    o horario de inicio (ver SalvarRotinaAutomaticaConfigView, que reseta
    rotina_automatica_proxima_execucao_em sempre que o inicio agendado
    muda, para o novo horario valer).

    Para cada agente participante ativo cuja proxima rodada ja chegou,
    dispara uma execucao normal (mesmo caminho de "Executar" manual). Se
    nao houver nada novo (tudo ja processado antes - mesma regra de
    duplicidade que ja existe) ou o agente ja estiver em execucao agora
    (trava de concorrencia), simplesmente nao roda nada nessa rodada — sem
    gerar processamento visivel de erro. Cada tentativa (rodou ou nao) fica
    registrada em RotinaAutomaticaExecucao, para a tela de historico."""
    from apps.agentes_ia.models import AgentStatus
    from apps.agentes_ia.services import montar_payload_execucao_padrao
    from apps.core.models import ConfiguracaoGeral

    configuracao_geral = ConfiguracaoGeral.obter()
    if not configuracao_geral.rotina_automatica_agentes_ativa:
        return []

    agora = timezone.now()
    proxima_execucao = configuracao_geral.rotina_automatica_proxima_execucao_em
    if proxima_execucao is None:
        # Nunca rodou desde a ultima vez que essa configuracao foi salva —
        # respeita o horario de inicio agendado (se houver e ainda nao
        # tiver chegado). Sem inicio configurado, ou com o horario ja no
        # passado, fica elegivel imediatamente (comportamento anterior).
        inicio_agendado = configuracao_geral.rotina_automatica_inicio_em
        if inicio_agendado is not None and inicio_agendado > agora:
            return []
    elif proxima_execucao > agora:
        return []

    intervalo_minutos = configuracao_geral.rotina_automatica_intervalo_minutos
    # Reagenda a proxima rodada global JA, antes de executar qualquer
    # agente — assim, se o worker cair no meio da rodada, a proxima
    # checagem (a cada poucos minutos) nao martela a rotina de novo em vez
    # de respeitar o intervalo configurado.
    ConfiguracaoGeral.objects.filter(pk=configuracao_geral.pk).update(
        rotina_automatica_proxima_execucao_em=agora + timedelta(minutes=intervalo_minutos)
    )

    # Regra de seguranca: intervalos curtos (< 30min) rodam com mais
    # frequencia, entao cada rodada processa um lote bem menor, para nao
    # acumular custo/risco de RPM do provedor de IA — ignora o lote
    # global configurado nesse caso.
    lote_tamanho = (
        6 if intervalo_minutos < 30 else configuracao_geral.rotina_automatica_lote_tamanho
    )

    configuracoes = AgenteConfiguracaoOperacional.objects.filter(
        execucao_automatica_ativa=True,
        agente__status=AgentStatus.ATIVO,
    ).select_related("agente")

    resultados = []
    for configuracao in configuracoes:
        resultados.append(
            _executar_rotina_automatica_agente(
                configuracao,
                montar_payload=montar_payload_execucao_padrao,
                lote_tamanho=lote_tamanho,
            )
        )
    return resultados


def _executar_rotina_automatica_agente(configuracao, *, montar_payload, lote_tamanho):
    agente = configuracao.agente
    iniciado_em = timezone.now()

    actor = agente.created_by or agente.updated_by
    if actor is None:
        return _registrar_historico_rotina(
            agente,
            iniciado_em=iniciado_em,
            status=RotinaAutomaticaExecucaoStatus.ERRO,
            motivo=(
                "Agente sem usuario responsavel (created_by/updated_by) "
                "para executar a rotina automatica."
            ),
        )

    try:
        cleaned_data = montar_payload(agente)
    except ValueError as exc:
        return _registrar_historico_rotina(
            agente,
            iniciado_em=iniciado_em,
            status=RotinaAutomaticaExecucaoStatus.ERRO,
            motivo=str(exc),
        )

    try:
        processamento = criar_e_iniciar_processamento_para_agente(
            agente=agente,
            actor=actor,
            cleaned_data=cleaned_data,
            limite_documentos_por_execucao=lote_tamanho,
        )
    except OperationalExecutionError as exc:
        processamento_tentado = getattr(exc, "processamento", None)
        if processamento_tentado is not None:
            # Chegou a rodar (mesmo que tenha terminado em erro/atencao) —
            # conta como "executada", com os detalhes vindos do
            # processamento (ver _registrar_historico_rotina).
            return _registrar_historico_rotina(
                agente,
                iniciado_em=iniciado_em,
                status=RotinaAutomaticaExecucaoStatus.EXECUTADA,
                processamento=processamento_tentado,
            )
        if getattr(exc, "sem_trabalho", False):
            return _registrar_historico_rotina(
                agente,
                iniciado_em=iniciado_em,
                status=RotinaAutomaticaExecucaoStatus.SEM_DOCUMENTOS,
                motivo=str(exc),
            )
        # Sobrou a trava de concorrencia ocupada (execucao manual ou outra
        # rodada da rotina disputando o mesmo agente) ou o agente
        # indisponivel para execucao (ex.: integracao inativa).
        return _registrar_historico_rotina(
            agente,
            iniciado_em=iniciado_em,
            status=RotinaAutomaticaExecucaoStatus.BLOQUEADA,
            motivo=str(exc),
        )

    return _registrar_historico_rotina(
        agente,
        iniciado_em=iniciado_em,
        status=RotinaAutomaticaExecucaoStatus.EXECUTADA,
        processamento=processamento,
    )


def _registrar_historico_rotina(agente, *, iniciado_em, status, processamento=None, motivo=""):
    """Persiste o resultado de uma tentativa da rotina automatica (rodou
    ou nao, quantos documentos, quantos com sucesso/erro e os motivos),
    para alimentar a tela Administrador > Rotina automatica de agentes."""
    total_documentos = total_sucesso = total_erro = 0
    if processamento is not None:
        contagem = processamento.documentos.aggregate(
            total=models.Count("id"),
            sucesso=models.Count("id", filter=models.Q(status=DocumentStatus.PROCESSADO)),
            erro=models.Count("id", filter=models.Q(status=DocumentStatus.ERRO)),
        )
        total_documentos = contagem["total"]
        total_sucesso = contagem["sucesso"]
        total_erro = contagem["erro"]
        if total_erro and not motivo:
            motivos_erro = list(
                processamento.documentos.filter(status=DocumentStatus.ERRO)
                .exclude(mensagem_erro="")
                .values_list("mensagem_erro", flat=True)
                .distinct()[:5]
            )
            motivo = "; ".join(motivos_erro)

    historico = RotinaAutomaticaExecucao.objects.create(
        agente=agente,
        processamento=processamento,
        status=status,
        iniciado_em=iniciado_em,
        finalizado_em=timezone.now(),
        total_documentos=total_documentos,
        total_sucesso=total_sucesso,
        total_erro=total_erro,
        motivo=motivo,
    )
    return {
        "agente": agente.nome,
        "status": historico.status,
        "processamento": processamento.codigo if processamento else None,
        "total_documentos": total_documentos,
        "total_sucesso": total_sucesso,
        "total_erro": total_erro,
        "motivo": motivo,
    }


_MENSAGENS_ATENCAO = (
    "nenhum pdf pendente",
    "nenhum arquivo pendente",
    "nenhuma subpasta encontrada",
    "pasta local nao encontrada",
    "pasta nao encontrada",
    "caminho nao encontrado",
    "nenhum documento encontrado",
    "nenhum item encontrado",
    # Todos os arquivos da pasta ja foram processados com sucesso em execucao
    # anterior deste agente — situacao normal, nao erro.
    "ja foram processados anteriormente",
    # Indisponibilidade temporaria do provedor de IA: condicao transitoria,
    # o usuario apenas precisa tentar novamente — atencao (amarelo), nao erro.
    "temporariamente indisponivel",
    "sobrecarregado",
    # Falha de conteudo da propria IA (resposta truncada/mal formada ou
    # vazia) que persistiu mesmo apos a retentativa automatica de fim de
    # lote (ver agent_execution._execute_documents_individually e
    # _parse_structured_output, retryable=True para estes dois casos) — e
    # instabilidade do provedor, nao um erro tecnico do sistema.
    "nao veio em json valido",
    "nao retornou conteudo util",
)


def _e_situacao_atencao(mensagem: str) -> bool:
    """Retorna True para situações que exigem atenção do usuário, não erro técnico."""
    msg = mensagem.lower()
    return any(p in msg for p in _MENSAGENS_ATENCAO)


def _finalizar_processamento_com_erro(processamento, mensagem_operacional, mensagem_tecnica=""):
    processamento.refresh_from_db()
    processamento.status = (
        ProcessingStatus.CONCLUIDO_ATENCAO
        if _e_situacao_atencao(mensagem_operacional)
        else ProcessingStatus.CONCLUIDO_ERRO
    )
    processamento.mensagem_erro = mensagem_operacional
    processamento.mensagem_erro_tecnico = mensagem_tecnica
    processamento.finalizado_em = timezone.now()
    processamento.etapa_atual = "Falha ao iniciar processamento"
    processamento.documento_atual_nome = ""
    processamento.ultima_atividade_em = timezone.now()
    processamento.save(
        update_fields=[
            "status",
            "mensagem_erro",
            "mensagem_erro_tecnico",
            "finalizado_em",
            "etapa_atual",
            "documento_atual_nome",
            "ultima_atividade_em",
            "updated_at",
        ]
    )


def _finalizar_processamento_sem_trabalho(processamento, mensagem_operacional, mensagem_tecnica=""):
    """
    Usado quando nenhum documento chegou a ser selecionado para processamento
    (pasta vazia ou 100% ja processada antes por este agente — ver
    ProcessamentoExecutionError.sem_trabalho) — nenhuma chamada de IA
    aconteceu. Registra o resultado normalmente (status/mensagem, para
    auditoria) mas descarta o Processamento via soft-delete
    (SoftDeleteModel.delete()) em vez de deixa-lo "concluido com atencao"
    visivel no Portal: como nada foi de fato tentado, nao ha progresso para
    o usuario acompanhar, so ruido na lista de Processamentos.

    O registro continua no banco e visivel no Django Admin (auditoria) via
    `Processamento.all_objects` — so some do Portal Operacional, que usa o
    manager padrao `Processamento.objects` (SoftDeleteManager).
    """
    processamento.refresh_from_db()
    processamento.status = ProcessingStatus.CONCLUIDO_ATENCAO
    processamento.mensagem_erro = mensagem_operacional
    processamento.mensagem_erro_tecnico = mensagem_tecnica
    processamento.finalizado_em = timezone.now()
    processamento.etapa_atual = "Nenhum documento pendente para processar"
    processamento.documento_atual_nome = ""
    processamento.ultima_atividade_em = timezone.now()
    processamento.save(
        update_fields=[
            "status",
            "mensagem_erro",
            "mensagem_erro_tecnico",
            "finalizado_em",
            "etapa_atual",
            "documento_atual_nome",
            "ultima_atividade_em",
            "updated_at",
        ]
    )
    processamento.delete()  # soft-delete: so seta deleted_at, nao remove do banco


def _criar_processamento(*, agente, actor, cleaned_data):
    configuracao = obter_ou_criar_configuracao_operacional(agente)
    source_type = cleaned_data["input_source_type"]

    processamento = Processamento(
        codigo=_gerar_codigo_processamento(),
        status=ProcessingStatus.CRIADO,
        iniciado_por=actor,
        agente=agente,
        input_source_type=source_type,
        forcar_reprocessamento=bool(cleaned_data.get("forcar_reprocessamento")),
        output_format=cleaned_data.get("output_format")
        or configuracao.default_output_format,
        arquivo_saida_formato=cleaned_data.get("output_format")
        or configuracao.default_output_format,
        prompt_snapshot=renderizar_prompt_com_parametros(
            agente.prompt_base,
            configuracao.prompt_parameters,
        ),
        document_execution_mode_snapshot=configuracao.document_execution_mode,
        output_assembly_mode_snapshot=configuracao.output_assembly_mode,
        output_packaging_mode_snapshot=configuracao.output_packaging_mode,
    )

    if source_type == ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER:
        processamento.folder_source = (
            cleaned_data.get("folder_source")
            or configuracao.default_folder_source
        )
    elif source_type in {
        ProcessingInputSourceType.LOCAL_FOLDER,
        ProcessingInputSourceType.LOCAL_FILE,
    }:
        processamento.local_storage_integration = cleaned_data[
            "local_storage_integration"
        ] or configuracao.default_local_storage_integration
        processamento.local_relative_input_path = cleaned_data[
            "local_relative_input_path"
        ] or configuracao.default_local_relative_input_path
    elif source_type == ProcessingInputSourceType.UPLOAD_AT_EXECUTION:
        upload_file = cleaned_data.get("arquivo_execucao_upload")
        if not upload_file:
            raise OperationalExecutionError(
                "Escolha um arquivo PDF antes de executar este agente."
            )
        processamento.arquivo_execucao_upload = upload_file

    try:
        with transaction.atomic():
            processamento.full_clean()
            processamento.save()
    except ValidationError as exc:
        raise OperationalExecutionError(_format_validation_error(exc)) from exc

    return processamento


def _gerar_codigo_processamento():
    timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
    return f"PROC-{timestamp}-{token_hex(4).upper()}"


def _format_validation_error(exc):
    if hasattr(exc, "message_dict"):
        messages = []
        for field_messages in exc.message_dict.values():
            messages.extend(field_messages)
        return " ".join(messages)
    return " ".join(exc.messages)
