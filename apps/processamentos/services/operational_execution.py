from datetime import timedelta
from secrets import token_hex

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.agentes_ia.models import (
    AgenteConfiguracaoOperacional,
    AgentDocumentExecutionMode,
    AgentOutputAssemblyMode,
)
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
from apps.processamentos.services.document_sources import (
    DocumentSourcePreparationError,
    prepare_documentos,
)
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

# ADR-001 Fase 2 (v2.0.0): trava global do CICLO da rotina automatica —
# bloqueia qualquer execucao manual (nao so do agente da vez) enquanto o
# worker esta processando uma rodada. Um ciclo processa varios agentes em
# sequencia (cada um podendo repetir ate LIMITE_TRAVA_EXECUCAO_MINUTOS
# minutos na sua propria trava), entao esta janela de auto-recuperacao e
# mais generosa que a trava por agente — evita que um crash no meio do
# ciclo bloqueie TODA execucao manual do sistema indefinidamente (blast
# radius bem maior que a trava por agente, que ja levou um incidente real
# em producao para ganhar esse mesmo tipo de auto-recuperacao).
LIMITE_TRAVA_ROTINA_AUTOMATICA_MINUTOS = 60


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


def _tentar_adquirir_trava_rotina_automatica_global(configuracao_geral):
    """Mesmo padrao de _tentar_adquirir_trava_execucao, mas GLOBAL (uma
    unica linha em ConfiguracaoGeral, nao por agente) — liga no inicio do
    loop de agentes da rotina automatica e desliga no fim (try/finally em
    executar_rotinas_automaticas_agentes)."""
    from apps.core.models import ConfiguracaoGeral

    agora = timezone.now()
    limite = agora - timedelta(minutes=LIMITE_TRAVA_ROTINA_AUTOMATICA_MINUTOS)
    linhas = (
        ConfiguracaoGeral.objects.filter(pk=configuracao_geral.pk)
        .filter(
            models.Q(rotina_automatica_em_execucao=False)
            | models.Q(rotina_automatica_em_execucao_desde__lt=limite)
        )
        .update(rotina_automatica_em_execucao=True, rotina_automatica_em_execucao_desde=agora)
    )
    return linhas == 1


def _liberar_trava_rotina_automatica_global(configuracao_geral):
    from apps.core.models import ConfiguracaoGeral

    ConfiguracaoGeral.objects.filter(pk=configuracao_geral.pk).update(
        rotina_automatica_em_execucao=False, rotina_automatica_em_execucao_desde=None
    )


def _rotina_automatica_em_execucao_agora(configuracao_geral) -> bool:
    """Leitura (nao atomica, nao precisa ser — so decide bloquear ou nao um
    clique manual) que respeita a mesma janela de auto-recuperacao usada na
    aquisicao da trava, para nao bloquear execucao manual para sempre se o
    campo ficou "True" preso por um crash do worker."""
    if not configuracao_geral.rotina_automatica_em_execucao:
        return False
    desde = configuracao_geral.rotina_automatica_em_execucao_desde
    if desde is None:
        return True
    limite = timezone.now() - timedelta(minutes=LIMITE_TRAVA_ROTINA_AUTOMATICA_MINUTOS)
    return desde >= limite


def _validar_e_travar_para_execucao(*, agente, actor, origem_rotina_automatica):
    """Checagens de pre-voo compartilhadas por criar_e_iniciar_processamento_
    para_agente (ciclo 1) e reexecutar_processamento_existente (ciclo 2 —
    ADR-001 Fase 4): trava global da rotina automatica (Fase 2),
    disponibilidade do agente, trava de concorrencia por agente. Levanta
    OperationalExecutionError se algum bloqueio impedir a execucao agora;
    senao devolve (configuracao, trava_exige_verificacao) para o chamador
    liberar a trava por agente em seu proprio finally."""
    if not origem_rotina_automatica:
        # ADR-001 Fase 2 (v2.0.0): nenhuma execucao manual (de agente ou de
        # reexecutar processamento) pode rodar enquanto o ciclo inteiro da
        # rotina automatica esta em andamento. A propria rotina automatica
        # (origem_rotina_automatica=True) nao se autobloqueia aqui.
        from apps.core.models import ConfiguracaoGeral

        if _rotina_automatica_em_execucao_agora(ConfiguracaoGeral.obter()):
            # ADR-001 Fase 3 (v2.0.0): sem Processamento ainda (bloqueado
            # antes de criar) — evento so aparece na auditoria global, nao
            # no log de um processamento especifico.
            from apps.auditoria.services import registrar_evento_auditoria

            registrar_evento_auditoria(
                modulo="processamentos",
                acao="execucao_bloqueada_rotina_automatica",
                actor=actor,
                objeto_tipo="AgenteIA",
                objeto_id=agente.pk,
                descricao=(
                    f"Execucao manual do agente {agente.nome} bloqueada: a rotina "
                    "automatica esta em execucao agora."
                ),
            )
            raise OperationalExecutionError(
                "A rotina automatica esta em execucao agora. Aguarde o "
                "ciclo terminar para executar manualmente."
            )

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
        if not origem_rotina_automatica:
            # ADR-001 Fase 3 (v2.0.0): so registra quando quem foi bloqueado
            # e uma execucao manual — quando e a propria rotina automatica
            # que esbarra nesta trava, RotinaAutomaticaExecucao ja registra
            # isso bem (status BLOQUEADA), sem precisar duplicar aqui.
            from apps.auditoria.services import registrar_evento_auditoria

            registrar_evento_auditoria(
                modulo="processamentos",
                acao="execucao_bloqueada_trava_agente",
                actor=actor,
                objeto_tipo="AgenteIA",
                objeto_id=agente.pk,
                descricao=(
                    f"Execucao manual do agente {agente.nome} bloqueada: ja existe "
                    "uma execucao em andamento para este agente."
                ),
            )
        raise OperationalExecutionError(
            "Este agente ja esta em execucao agora. Aguarde terminar antes "
            "de executar de novo."
        )

    return configuracao, trava_exige_verificacao


def _executar_e_tratar_erros(
    processamento,
    actor,
    *,
    limite_documentos_por_execucao=None,
    permitir_sem_trabalho=True,
    marcar_bloqueio_permanente_em_erro=False,
    pular_descoberta=False,
):
    """Roda execute_processing sobre um Processamento ja existente,
    traduzindo qualquer excecao de execucao em OperationalExecutionError e
    finalizando o Processamento adequadamente. Extraido de
    criar_e_iniciar_processamento_para_agente (ADR-001 Fase 4) para ser
    compartilhado com reexecutar_processamento_existente — esse bloco ja
    foi palco de varios incidentes reais de producao (classificacao de
    erro, trava, sobrecarga), entao duplica-lo a mao entre os dois
    chamadores e o tipo exato de duplicacao que diverge silenciosamente
    depois de um hotfix aplicado em so um dos dois lugares.

    `permitir_sem_trabalho=False` (usado na reexecucao) converte o que
    seria um "sem trabalho" (que soft-deleta o Processamento — ver
    _finalizar_processamento_sem_trabalho) em erro definitivo normal:
    reexecutar um Processamento que ja existe nunca deve fazê-lo
    desaparecer da tela do usuario.

    `marcar_bloqueio_permanente_em_erro=True` (idem, so na reexecucao)
    trava o Processamento para sempre (regra 3) quando o resultado e
    CONCLUIDO_ERRO — nao quando e CONCLUIDO_ATENCAO, que conta como
    "concluido" (decisao do usuario) e ja esconde o botao "Executar" so
    pelo status, sem precisar da trava."""
    try:
        execute_processing(
            processamento,
            actor,
            limite_documentos_por_execucao=limite_documentos_por_execucao,
            pular_descoberta=pular_descoberta,
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
        if getattr(exc, "sem_trabalho", False) and permitir_sem_trabalho:
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
            if (
                marcar_bloqueio_permanente_em_erro
                and processamento.status == ProcessingStatus.CONCLUIDO_ERRO
            ):
                _bloquear_processamento_permanentemente(processamento)
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
        if (
            marcar_bloqueio_permanente_em_erro
            and processamento.status == ProcessingStatus.CONCLUIDO_ERRO
        ):
            _bloquear_processamento_permanentemente(processamento)
        raise erro_operacional from exc


def _bloquear_processamento_permanentemente(processamento):
    processamento.bloqueado_permanentemente = True
    Processamento.objects.filter(pk=processamento.pk).update(
        bloqueado_permanentemente=True
    )
    from apps.auditoria.services import registrar_evento_auditoria

    registrar_evento_auditoria(
        modulo="processamentos",
        acao="processamento_bloqueado_permanentemente",
        actor=processamento.iniciado_por,
        processamento=processamento,
        objeto_tipo="Processamento",
        objeto_id=processamento.pk,
        descricao=(
            f"Processamento {processamento.codigo} terminou em erro na "
            "reexecucao e nao pode mais ser executado. Execute o agente "
            "novamente para criar um processamento novo para este arquivo."
        ),
    )


def _criar_e_iniciar_processamento_sem_trava(
    *, agente, actor, cleaned_data, limite_documentos_por_execucao=None
):
    """Parte "fazer o trabalho" de criar_e_iniciar_processamento_para_agente,
    sem nenhuma acao sobre a trava por agente — ADR-001 Fase 5b (v2.0.0):
    extraido para ser reaproveitado por
    criar_e_iniciar_processamentos_individuais_para_agente, que precisa
    criar/rodar N Processamentos (1 por arquivo) segurando a trava UMA
    unica vez pra rodada inteira, nao uma vez por arquivo (a trava por
    agente nao e reentrante — ver nota de risco na ADR-001, Fase 5b)."""
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

    _executar_e_tratar_erros(
        processamento,
        actor,
        limite_documentos_por_execucao=limite_documentos_por_execucao,
    )
    return processamento


def criar_e_iniciar_processamento_para_agente(
    *, agente, actor, cleaned_data, limite_documentos_por_execucao=None,
    origem_rotina_automatica=False,
):
    configuracao, trava_exige_verificacao = _validar_e_travar_para_execucao(
        agente=agente, actor=actor, origem_rotina_automatica=origem_rotina_automatica
    )

    try:
        processamento = _criar_e_iniciar_processamento_sem_trava(
            agente=agente,
            actor=actor,
            cleaned_data=cleaned_data,
            limite_documentos_por_execucao=limite_documentos_por_execucao,
        )
    finally:
        if trava_exige_verificacao:
            _liberar_trava_execucao(configuracao)

    processamento.refresh_from_db()
    return processamento


def _reexecutar_processamento_sem_trava(
    *, processamento, actor, acao_evento, descricao_evento
):
    """Parte "fazer o trabalho" de _reexecutar_processamento, sem nenhuma
    acao sobre a trava por agente — ADR-001 Fase 5b (v2.0.0): extraido
    pelo mesmo motivo de _criar_e_iniciar_processamento_sem_trava, para a
    orquestracao por rodada poder reexecutar N Processamentos pendentes
    segurando a trava uma unica vez."""
    # Reabre para retentativa os documentos que ficaram em ERRO —
    # _select_documentos (chamado dentro de execute_processing) so
    # seleciona PENDENTE; sem isso, a reexecucao nao teria nenhum
    # documento elegivel e cairia no ramo "sem trabalho". Documentos ja
    # PENDENTE (caso do retry automatico da Fase 5b, que nunca chegou a
    # virar ERRO) nao precisam de reset.
    processamento.documentos.filter(status=DocumentStatus.ERRO).update(
        status=DocumentStatus.PENDENTE,
        mensagem_erro="",
        updated_at=timezone.now(),
    )

    processamento.status = ProcessingStatus.EM_FILA
    processamento.mensagem_erro = ""
    processamento.mensagem_erro_tecnico = ""
    processamento.etapa_atual = "Aguardando reexecucao"
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

    from apps.auditoria.services import registrar_evento_auditoria

    registrar_evento_auditoria(
        modulo="processamentos",
        acao=acao_evento,
        actor=actor,
        processamento=processamento,
        objeto_tipo="Processamento",
        objeto_id=processamento.pk,
        descricao=descricao_evento,
    )

    _executar_e_tratar_erros(
        processamento,
        actor,
        permitir_sem_trabalho=False,
        marcar_bloqueio_permanente_em_erro=True,
        # ADR-001 Fase 5b (v2.0.0): "reexecutar" significa rodar de novo os
        # documentos que JA pertencem a este Processamento — nunca sair
        # descobrindo arquivos novos na pasta (isso e papel da descoberta,
        # nao da reexecucao). Sem isso, reexecutar um Processamento
        # individual (1 documento) redescobria a pasta inteira e podia
        # "roubar" para dentro dele arquivos irmaos que deveriam ganhar seu
        # proprio Processamento (encontrado testando no servidor local).
        pular_descoberta=True,
    )


def _reexecutar_processamento(
    *, processamento, actor, origem_rotina_automatica, acao_evento, descricao_evento
):
    """Nucleo compartilhado por reexecutar_processamento_existente (manual,
    Fase 4) e _reexecutar_processamento_pendente_retentativa (automatico,
    Fase 5b) — roda de novo o MESMO Processamento (nao cria um novo) e
    trava para sempre (ver _bloquear_processamento_permanentemente) se
    terminar em CONCLUIDO_ERRO real. So existe esta 1 chance extra em
    qualquer um dos dois casos."""
    agente = processamento.agente
    if agente is None:
        raise OperationalExecutionError(
            "O agente deste processamento nao existe mais."
        )

    configuracao, trava_exige_verificacao = _validar_e_travar_para_execucao(
        agente=agente, actor=actor, origem_rotina_automatica=origem_rotina_automatica
    )

    try:
        _reexecutar_processamento_sem_trava(
            processamento=processamento,
            actor=actor,
            acao_evento=acao_evento,
            descricao_evento=descricao_evento,
        )
    finally:
        if trava_exige_verificacao:
            _liberar_trava_execucao(configuracao)

    processamento.refresh_from_db()
    return processamento


# Estados elegiveis para o botao "Executar" manual num Processamento ja
# existente — CONCLUIDO_ERRO (Fase 4) e, desde a Fase 5b,
# PENDENTE_RETENTATIVA (usuario pode forcar a retentativa antes da proxima
# rotina automatica, em vez de esperar). concluido_sucesso e
# concluido_atencao contam como "concluido" (regra 2) e nunca aparecem
# aqui; estados transitorios (criado/em_fila/em_processamento) tambem nao —
# nao faz sentido "executar" algo que ja esta rodando.
_STATUS_ELEGIVEIS_PARA_REEXECUCAO_MANUAL = {
    ProcessingStatus.CONCLUIDO_ERRO,
    ProcessingStatus.PENDENTE_RETENTATIVA,
}


def reexecutar_processamento_existente(*, processamento, actor):
    """ADR-001 Fases 4 e 5b (v2.0.0, regras 2, 3 e 6): reexecuta o MESMO
    Processamento (nao cria um novo) — so permitido quando o status esta em
    _STATUS_ELEGIVEIS_PARA_REEXECUCAO_MANUAL e ainda nao esta
    bloqueado_permanentemente."""
    if processamento.bloqueado_permanentemente:
        raise OperationalExecutionError(
            "Este processamento ja foi reexecutado e nao pode mais ser "
            "executado. Execute o agente novamente para criar um "
            "processamento novo para este arquivo."
        )
    if processamento.status not in _STATUS_ELEGIVEIS_PARA_REEXECUCAO_MANUAL:
        raise OperationalExecutionError(
            "Este processamento nao pode ser executado no estado atual."
        )

    return _reexecutar_processamento(
        processamento=processamento,
        actor=actor,
        origem_rotina_automatica=False,
        acao_evento="reexecucao_manual_iniciada",
        descricao_evento=f"Processamento {processamento.codigo} reexecutado manualmente.",
    )


def _reexecutar_processamento_pendente_retentativa(*, processamento, actor):
    """ADR-001 Fase 5b (v2.0.0, regra 6): 2a e ultima chance automatica para
    um Processamento individual que adiou seu unico documento na 1a falha
    por erro pontual do provedor de IA (ver agent_execution.
    _marcar_documento_pendente_retentativa e o novo status
    ProcessingStatus.PENDENTE_RETENTATIVA). Chamada pela propria rotina
    automatica, com prioridade sobre descobrir arquivos novos — o clique
    manual tambem pode forcar essa retentativa mais cedo (ver
    reexecutar_processamento_existente, elegibilidade ampliada nesta mesma
    fase para tambem cobrir PENDENTE_RETENTATIVA, nao so CONCLUIDO_ERRO)."""
    if processamento.status != ProcessingStatus.PENDENTE_RETENTATIVA:
        raise OperationalExecutionError(
            "Este processamento nao esta aguardando retentativa da rotina "
            "automatica."
        )

    return _reexecutar_processamento(
        processamento=processamento,
        actor=actor,
        origem_rotina_automatica=True,
        acao_evento="retentativa_pendente_iniciada",
        descricao_evento=(
            f"Processamento {processamento.codigo}: retentativa automatica "
            "do documento adiado na rodada anterior."
        ),
    )


def _agente_usa_execucao_individual(configuracao) -> bool:
    """Mesma condicao de agent_execution._usa_execucao_individual, mas
    contra a configuracao operacional do agente diretamente — usada ANTES
    de existir qualquer Processamento, para decidir se este agente usa o
    caminho novo da Fase 5b (1 Processamento por documento,
    criar_e_iniciar_processamentos_individuais_para_agente) ou o caminho
    antigo (GRUPO_UNICO/LOTE_POR_PASTA, criar_e_iniciar_processamento_
    para_agente, sem nenhuma mudanca nesta fase)."""
    return (
        configuracao.document_execution_mode == AgentDocumentExecutionMode.INDIVIDUAL
        or configuracao.output_assembly_mode == AgentOutputAssemblyMode.UMA_POR_ENTRADA
    )


def _descobrir_e_criar_processamentos_individuais(*, agente, actor, cleaned_data, limite=None):
    """ADR-001 Fase 5b (v2.0.0, regra 1): descobre arquivos ainda nao
    cobertos por nenhum Processamento deste agente e cria 1 Processamento
    dedicado por arquivo (exatamente 1 DocumentoEntrada cada).

    Reaproveita 100% da descoberta/dedup ja existente
    (document_sources.prepare_documentos, com toda a logica de Google
    Drive/pasta local/subpastas/lote/dedup) rodando-a UMA vez contra um
    Processamento "staging" descartavel — depois move (reatribui a FK) cada
    DocumentoEntrada descoberto para o seu proprio Processamento novo, e
    apaga o staging (que fica vazio). Evita reescrever ~200 linhas de
    _prepare_* so para "descobrir sem anexar a 1 processamento so".

    `limite`: teto de Processamentos NOVOS que esta chamada pode criar
    (None = sem teto — execucao manual descobre a pasta inteira de uma
    vez, como sempre fez). So a rotina automatica passa um valor.

    Retorna a lista de Processamentos novos (EM_FILA, ainda nao
    executados) — quem chama e responsavel por executa-los.

    Limitacao conhecida, aceita: eventos de auditoria gerados durante a
    descoberta no Processamento staging (ex.: "documento_ignorado_
    duplicidade") ficam com processamento=None (SET_NULL) apos o staging
    ser apagado — continuam visiveis na auditoria global, so nao aparecem
    no log de nenhum Processamento especifico."""
    staging = _criar_processamento(agente=agente, actor=actor, cleaned_data=cleaned_data)
    try:
        prepare_documentos(staging, limite_novos_documentos=limite)
        documentos_descobertos = list(staging.documentos.all())

        novos_processamentos = []
        agora = timezone.now()
        for documento in documentos_descobertos:
            processamento = _criar_processamento(
                agente=agente, actor=actor, cleaned_data=cleaned_data
            )
            processamento.status = ProcessingStatus.EM_FILA
            processamento.etapa_atual = "Aguardando inicio da execucao"
            processamento.ultima_atividade_em = agora
            processamento.save(
                update_fields=["status", "etapa_atual", "ultima_atividade_em", "updated_at"]
            )
            documento.processamento = processamento
            documento.save(update_fields=["processamento", "updated_at"])
            novos_processamentos.append(processamento)
        return novos_processamentos
    finally:
        # Staging fica vazio (todo documento descoberto foi movido para o
        # seu proprio Processamento) — descarta. Hard delete: nunca chegou
        # a ser "iniciado"/executado, nao ha nada de valor operacional a
        # preservar nele.
        Processamento.objects.filter(pk=staging.pk).delete()


def criar_e_iniciar_processamentos_individuais_para_agente(
    *, agente, actor, cleaned_data, limite_documentos_por_execucao=None,
    origem_rotina_automatica=False,
):
    """ADR-001 Fase 5b (v2.0.0, regras 1, 4, 5, 6): para agentes cujo modo e
    Individual (ver _agente_usa_execucao_individual) — cada arquivo (novo ou
    retomado) ganha seu PROPRIO Processamento, nunca compartilhado. Chamada
    tanto pela execucao manual (AgenteExecucaoView) quanto pela rotina
    automatica (_executar_rotina_automatica_agente) no lugar de
    criar_e_iniciar_processamento_para_agente. Agentes GRUPO_UNICO/
    LOTE_POR_PASTA continuam usando a funcao antiga, sem nenhuma mudanca.

    Trava por agente e trava global adquiridas UMA vez para a rodada
    inteira, nao por arquivo — a trava por agente nao e reentrante (ver
    _criar_e_iniciar_processamento_sem_trava/_reexecutar_processamento_sem_trava,
    que por isso nao fazem nenhuma acao de trava por conta propria).

    Retorna a lista de Processamentos tocados nesta chamada (reexecutados
    ou criados), na ordem em que foram tratados — pendentes retomados
    primeiro (regra 6, prioridade), depois os arquivos novos."""
    configuracao, trava_exige_verificacao = _validar_e_travar_para_execucao(
        agente=agente, actor=actor, origem_rotina_automatica=origem_rotina_automatica
    )

    processamentos_tocados = []
    try:
        pendentes = list(
            Processamento.objects.filter(
                agente=agente,
                status=ProcessingStatus.PENDENTE_RETENTATIVA,
                bloqueado_permanentemente=False,
            ).order_by("created_at")
        )
        if limite_documentos_por_execucao is not None:
            pendentes = pendentes[:limite_documentos_por_execucao]

        for processamento in pendentes:
            try:
                _reexecutar_processamento_sem_trava(
                    processamento=processamento,
                    actor=actor,
                    acao_evento="retentativa_pendente_iniciada",
                    descricao_evento=(
                        f"Processamento {processamento.codigo}: retentativa "
                        "automatica do documento adiado na rodada anterior."
                    ),
                )
            except OperationalExecutionError:
                # Ja finalizado (sucesso, erro definitivo ou pendente de
                # novo) dentro da funcao — nao interrompe o resto da rodada
                # por causa de 1 arquivo.
                pass
            processamento.refresh_from_db()
            processamentos_tocados.append(processamento)

        limite_novos = None
        if limite_documentos_por_execucao is not None:
            limite_novos = max(0, limite_documentos_por_execucao - len(processamentos_tocados))
            if limite_novos == 0:
                return processamentos_tocados

        novos = _descobrir_e_criar_processamentos_individuais(
            agente=agente, actor=actor, cleaned_data=cleaned_data, limite=limite_novos
        )
        for processamento in novos:
            try:
                _executar_e_tratar_erros(
                    processamento,
                    actor,
                    limite_documentos_por_execucao=limite_documentos_por_execucao,
                    pular_descoberta=True,
                )
            except OperationalExecutionError:
                pass
            processamento.refresh_from_db()
            processamentos_tocados.append(processamento)
    finally:
        if trava_exige_verificacao:
            _liberar_trava_execucao(configuracao)

    return processamentos_tocados


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
    registrada em RotinaAutomaticaExecucao, para a tela de historico.

    ConfiguracaoGeral.rotina_automatica_ultima_verificacao_em e atualizado
    a cada chamada desta funcao, mesmo sem nenhuma rodada elegivel (ou com
    o interruptor geral desligado) — e o heartbeat exibido na tela, para
    confirmar que o worker esta de fato checando no intervalo esperado."""
    from apps.agentes_ia.models import AgentStatus
    from apps.agentes_ia.services import montar_payload_execucao_padrao
    from apps.core.models import ConfiguracaoGeral

    configuracao_geral = ConfiguracaoGeral.obter()

    agora = timezone.now()
    # Grava a CADA chamada (mesmo com o interruptor geral desligado ou sem
    # rodada elegivel ainda) — e o unico sinal, na tela Administrador >
    # Rotina automatica, de que o worker esta de fato vivo e chamando esse
    # comando na frequencia esperada. Sem isso, "nada pra fazer agora" e
    # "worker parado" ficam indistinguiveis (historico igualmente vazio nos
    # dois casos). Update direto na tabela — nao usa configuracao_geral.save()
    # pra nao pisar em outros campos alterados concorrentemente.
    ConfiguracaoGeral.objects.filter(pk=configuracao_geral.pk).update(
        rotina_automatica_ultima_verificacao_em=agora
    )

    if not configuracao_geral.rotina_automatica_agentes_ativa:
        return []
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

    configuracoes = list(
        AgenteConfiguracaoOperacional.objects.filter(
            execucao_automatica_ativa=True,
            agente__status=AgentStatus.ATIVO,
        ).select_related("agente")
    )
    if not configuracoes:
        return []

    # ADR-001 Fase 2 (v2.0.0): trava global so enquanto ha trabalho de fato
    # (o loop de agentes abaixo) — os retornos antecipados acima (interruptor
    # desligado, rodada ainda nao devida) nao chegam a bloquear execucao
    # manual nenhuma, entao nao precisam da trava. Se a trava global ja
    # estiver ocupada (nao deveria, nesse worker sequencial, mas protege
    # contra uma corrida teorica ou um crash sem finally anterior), esta
    # chamada simplesmente nao processa nada agora — a proxima tentativa (~5
    # min) tenta de novo.
    if not _tentar_adquirir_trava_rotina_automatica_global(configuracao_geral):
        return []

    resultados = []
    try:
        for configuracao in configuracoes:
            # ADR-001 Fase 5b (v2.0.0): agentes em modo Individual usam a
            # orquestracao nova (1 Processamento por arquivo); GRUPO_UNICO/
            # LOTE_POR_PASTA continuam na funcao antiga, sem mudanca.
            if _agente_usa_execucao_individual(configuracao):
                resultados.append(
                    _executar_rotina_automatica_agente_individual(
                        configuracao,
                        montar_payload=montar_payload_execucao_padrao,
                        lote_tamanho=lote_tamanho,
                    )
                )
            else:
                resultados.append(
                    _executar_rotina_automatica_agente(
                        configuracao,
                        montar_payload=montar_payload_execucao_padrao,
                        lote_tamanho=lote_tamanho,
                    )
                )
    finally:
        _liberar_trava_rotina_automatica_global(configuracao_geral)
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
            origem_rotina_automatica=True,
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
    total_documentos = total_sucesso = total_erro = total_pendente = 0
    if processamento is not None:
        contagem = processamento.documentos.aggregate(
            total=models.Count("id"),
            sucesso=models.Count("id", filter=models.Q(status=DocumentStatus.PROCESSADO)),
            erro=models.Count("id", filter=models.Q(status=DocumentStatus.ERRO)),
            # Adiados para a proxima rotina por erro pontual do provedor de
            # IA (ver agent_execution._marcar_documento_pendente_retentativa)
            # — nao contam em total_erro; sem isso total_documentos -
            # total_sucesso - total_erro ficaria > 0 sem explicacao na tela.
            pendente=models.Count("id", filter=models.Q(status=DocumentStatus.PENDENTE)),
        )
        total_documentos = contagem["total"]
        total_sucesso = contagem["sucesso"]
        total_erro = contagem["erro"]
        total_pendente = contagem["pendente"]
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
        total_pendente=total_pendente,
        motivo=motivo,
    )
    return {
        "agente": agente.nome,
        "status": historico.status,
        "processamento": processamento.codigo if processamento else None,
        "total_documentos": total_documentos,
        "total_sucesso": total_sucesso,
        "total_erro": total_erro,
        "total_pendente": total_pendente,
        "motivo": motivo,
    }


def _executar_rotina_automatica_agente_individual(configuracao, *, montar_payload, lote_tamanho):
    """ADR-001 Fase 5b (v2.0.0): variante de _executar_rotina_automatica_agente
    para agentes em modo Individual — usa criar_e_iniciar_processamentos_
    individuais_para_agente (1 Processamento por arquivo) em vez de
    criar_e_iniciar_processamento_para_agente (1 Processamento pra tudo).

    Regra 7: "se apos a rotina o documento for processado com acerto, o
    status daquela rotina fica como concluido" — mapeado para
    RotinaAutomaticaExecucaoStatus.EXECUTADA (nao existe um status
    "concluido" literal; EXECUTADA ja significa "a rodada rodou e fez
    trabalho", que e o que a regra pede)."""
    agente = configuracao.agente
    iniciado_em = timezone.now()

    actor = agente.created_by or agente.updated_by
    if actor is None:
        return _registrar_historico_rotina_individual(
            agente,
            iniciado_em=iniciado_em,
            status=RotinaAutomaticaExecucaoStatus.ERRO,
            motivo=(
                "Agente sem usuario responsavel (created_by/updated_by) "
                "para executar a rotina automatica."
            ),
            processamentos=[],
        )

    try:
        cleaned_data = montar_payload(agente)
    except ValueError as exc:
        return _registrar_historico_rotina_individual(
            agente,
            iniciado_em=iniciado_em,
            status=RotinaAutomaticaExecucaoStatus.ERRO,
            motivo=str(exc),
            processamentos=[],
        )

    try:
        processamentos = criar_e_iniciar_processamentos_individuais_para_agente(
            agente=agente,
            actor=actor,
            cleaned_data=cleaned_data,
            limite_documentos_por_execucao=lote_tamanho,
            origem_rotina_automatica=True,
        )
    except OperationalExecutionError as exc:
        # Bloqueada antes mesmo de comecar (trava ocupada, agente
        # indisponivel) — diferente da funcao antiga, aqui nunca sobra um
        # Processamento "tentado" parcial, porque a checagem de pre-voo
        # acontece antes de qualquer Processamento ser criado.
        return _registrar_historico_rotina_individual(
            agente,
            iniciado_em=iniciado_em,
            status=RotinaAutomaticaExecucaoStatus.BLOQUEADA,
            motivo=str(exc),
            processamentos=[],
        )

    if not processamentos:
        return _registrar_historico_rotina_individual(
            agente,
            iniciado_em=iniciado_em,
            status=RotinaAutomaticaExecucaoStatus.SEM_DOCUMENTOS,
            motivo="Nenhum arquivo novo ou pendente encontrado.",
            processamentos=[],
        )

    return _registrar_historico_rotina_individual(
        agente,
        iniciado_em=iniciado_em,
        status=RotinaAutomaticaExecucaoStatus.EXECUTADA,
        processamentos=processamentos,
    )


def _registrar_historico_rotina_individual(
    agente, *, iniciado_em, status, processamentos, motivo=""
):
    """Variante de _registrar_historico_rotina para a Fase 5b — agrega
    totais de N Processamentos (1 por arquivo cada) em vez de olhar os
    documentos de 1 so, e liga cada um a rodada via Processamento.
    rotina_automatica_execucao (FK nova da Fase 5a) em vez do
    OneToOneField legado RotinaAutomaticaExecucao.processamento (que so
    comporta 1 — deixado de fora aqui de proposito, sem popular)."""
    total_documentos = len(processamentos)
    total_sucesso = sum(
        1
        for p in processamentos
        if p.status in (ProcessingStatus.CONCLUIDO_SUCESSO, ProcessingStatus.CONCLUIDO_ATENCAO)
    )
    total_erro = sum(1 for p in processamentos if p.status == ProcessingStatus.CONCLUIDO_ERRO)
    total_pendente = sum(
        1 for p in processamentos if p.status == ProcessingStatus.PENDENTE_RETENTATIVA
    )

    if total_erro and not motivo:
        motivos_erro = list(
            dict.fromkeys(
                p.mensagem_erro
                for p in processamentos
                if p.status == ProcessingStatus.CONCLUIDO_ERRO and p.mensagem_erro
            )
        )[:5]
        motivo = "; ".join(motivos_erro)

    historico = RotinaAutomaticaExecucao.objects.create(
        agente=agente,
        status=status,
        iniciado_em=iniciado_em,
        finalizado_em=timezone.now(),
        total_documentos=total_documentos,
        total_sucesso=total_sucesso,
        total_erro=total_erro,
        total_pendente=total_pendente,
        motivo=motivo,
    )
    if processamentos:
        Processamento.objects.filter(pk__in=[p.pk for p in processamentos]).update(
            rotina_automatica_execucao=historico
        )
    return {
        "agente": agente.nome,
        "status": historico.status,
        "processamentos": [p.codigo for p in processamentos],
        "total_documentos": total_documentos,
        "total_sucesso": total_sucesso,
        "total_erro": total_erro,
        "total_pendente": total_pendente,
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

    # ADR-001 Fase 3 (v2.0.0): evento semente do log proprio deste
    # processamento (ver ProcessamentoLogView) — todo processamento passa a
    # ter, no minimo, este registro de quando/por quem foi criado.
    from apps.auditoria.services import registrar_evento_auditoria

    registrar_evento_auditoria(
        modulo="processamentos",
        acao="processamento_criado",
        actor=actor,
        processamento=processamento,
        objeto_tipo="Processamento",
        objeto_id=processamento.pk,
        descricao=f"Processamento {processamento.codigo} criado para o agente {agente.nome}.",
        payload={
            "agente": agente.nome,
            "input_source_type": source_type,
            "forcar_reprocessamento": processamento.forcar_reprocessamento,
        },
    )

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
