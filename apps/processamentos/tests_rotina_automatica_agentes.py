"""
Rotina automatica de execucao por agente (AgenteConfiguracaoOperacional.
execucao_automatica_ativa) e a trava de concorrencia por agente
(execucao_em_andamento) que ela tornou necessaria — antes, nada impedia a
rotina automatica e um clique manual em "Executar" rodarem o mesmo agente
ao mesmo tempo, disputando os mesmos documentos pendentes.

Motivado por: cliente que as vezes precisa processar 40-50 documentos de
uma vez, o que nao cabe numa unica execucao sincrona sem estourar o
timeout do gunicorn (600s). O interruptor, o intervalo entre rodadas e
quantos documentos cada rodada processa sao todos GLOBAIS
(ConfiguracaoGeral.rotina_automatica_agentes_ativa/
rotina_automatica_intervalo_minutos/rotina_automatica_lote_tamanho,
editaveis em Administrador > Rotina automatica) — cada agente so decide
se PARTICIPA (execucao_automatica_ativa). Reaproveita a mesma regra de
duplicidade que ja existe: se nao houver documento novo, nao roda nada.
Cada tentativa fica registrada em RotinaAutomaticaExecucao
para a tela de historico.
"""

import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.agentes_ia.models import (
    AgenteConfiguracaoOperacional,
    AgenteIA,
    AgentDefaultInputSourceType,
    AgentInputPolicy,
    AgentStatus,
    AgentType,
)
from apps.core.models import ConfiguracaoGeral
from apps.integracoes.models import (
    AIProviderIntegration,
    IntegrationStatus,
    LocalStorageIntegration,
)
from apps.processamentos.models import (
    DocumentoSaidaProcessamento,
    DocumentStatus,
    ExecutionScopeType,
    OutputDocumentStatus,
    Processamento,
    ProcessingInputSourceType,
    RotinaAutomaticaExecucao,
    RotinaAutomaticaExecucaoStatus,
)
from apps.processamentos.services.agent_execution import execute_processing
from apps.processamentos.services.operational_execution import (
    LIMITE_TRAVA_EXECUCAO_MINUTOS,
    OperationalExecutionError,
    _executar_rotina_automatica_agente,
    _liberar_trava_execucao,
    _registrar_historico_rotina,
    _tentar_adquirir_trava_execucao,
    criar_e_iniciar_processamento_para_agente,
    executar_rotinas_automaticas_agentes,
)


def _criar_agente(*, criado_por, execucao_automatica_ativa=False, concurrency_policy=None):
    integracao = AIProviderIntegration.objects.create(
        nome=f"Integracao {AIProviderIntegration.objects.count()}",
        api_key="chave-teste",
        status=IntegrationStatus.ATIVA,
        default_model="modelo-teste",
    )
    agente = AgenteIA.objects.create(
        nome=f"Agente {AgenteIA.objects.count()}",
        slug=f"agente-{AgenteIA.objects.count()}",
        tipo=AgentType.GENERICO,
        ai_provider_integration=integracao,
        status=AgentStatus.ATIVO,
        prompt_base="prompt de teste",
        created_by=criado_por,
    )
    kwargs = dict(
        agente=agente,
        input_policy=AgentInputPolicy.SEM_ENTRADA,
        default_input_source_type=AgentDefaultInputSourceType.NONE,
        execucao_automatica_ativa=execucao_automatica_ativa,
    )
    if concurrency_policy is not None:
        kwargs["concurrency_policy"] = concurrency_policy
    configuracao = AgenteConfiguracaoOperacional.objects.create(**kwargs)
    return agente, configuracao


class TravaExecucaoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono", password="x")
        self.agente, self.configuracao = _criar_agente(criado_por=self.user)

    def test_adquire_quando_livre(self):
        self.assertTrue(_tentar_adquirir_trava_execucao(self.configuracao))
        self.configuracao.refresh_from_db()
        self.assertTrue(self.configuracao.execucao_em_andamento)
        self.assertIsNotNone(self.configuracao.execucao_em_andamento_desde)

    def test_nao_adquire_quando_ja_esta_em_andamento(self):
        self.assertTrue(_tentar_adquirir_trava_execucao(self.configuracao))
        self.assertFalse(_tentar_adquirir_trava_execucao(self.configuracao))

    def test_liberar_permite_adquirir_de_novo(self):
        _tentar_adquirir_trava_execucao(self.configuracao)
        _liberar_trava_execucao(self.configuracao)
        self.configuracao.refresh_from_db()
        self.assertFalse(self.configuracao.execucao_em_andamento)
        self.assertTrue(_tentar_adquirir_trava_execucao(self.configuracao))

    def test_trava_presa_ha_muito_tempo_e_liberavel_sozinha(self):
        # Simula um crash: trava marcada, mas nunca liberada, ha mais tempo
        # que o limite de auto-recuperacao.
        muito_tempo_atras = timezone.now() - timedelta(
            minutes=LIMITE_TRAVA_EXECUCAO_MINUTOS + 5
        )
        AgenteConfiguracaoOperacional.objects.filter(pk=self.configuracao.pk).update(
            execucao_em_andamento=True, execucao_em_andamento_desde=muito_tempo_atras
        )
        self.assertTrue(_tentar_adquirir_trava_execucao(self.configuracao))

    def test_trava_presa_ha_pouco_tempo_nao_e_liberavel(self):
        recente = timezone.now() - timedelta(minutes=2)
        AgenteConfiguracaoOperacional.objects.filter(pk=self.configuracao.pk).update(
            execucao_em_andamento=True, execucao_em_andamento_desde=recente
        )
        self.assertFalse(_tentar_adquirir_trava_execucao(self.configuracao))


@patch("apps.processamentos.services.operational_execution.execute_processing")
class CriarEIniciarProcessamentoTravaTests(TestCase):
    """Isola a trava de concorrencia do restante de execute_processing
    (mockado) — o que importa aqui e se a trava bloqueia/libera direito,
    nao o que a execucao em si faz."""

    def setUp(self):
        self.user = User.objects.create_user(username="dono2", password="x")
        self.agente, self.configuracao = _criar_agente(criado_por=self.user)
        self.cleaned_data = {
            "input_source_type": AgentDefaultInputSourceType.NONE,
            "output_format": "json",
            "output_destination": "internal_media",
            "document_execution_mode": "individual",
            "output_assembly_mode": "uma_por_entrada",
            "output_packaging_mode": "zip_se_multiplos",
            "prompt_parameters": [],
        }

    def test_execucao_normal_adquire_e_libera_a_trava(self, mock_execute):
        criar_e_iniciar_processamento_para_agente(
            agente=self.agente, actor=self.user, cleaned_data=self.cleaned_data
        )
        self.configuracao.refresh_from_db()
        self.assertFalse(self.configuracao.execucao_em_andamento)
        mock_execute.assert_called_once()

    def test_libera_a_trava_mesmo_quando_execucao_falha(self, mock_execute):
        mock_execute.side_effect = RuntimeError("falha inesperada")
        with self.assertRaises(OperationalExecutionError):
            criar_e_iniciar_processamento_para_agente(
                agente=self.agente, actor=self.user, cleaned_data=self.cleaned_data
            )
        self.configuracao.refresh_from_db()
        self.assertFalse(self.configuracao.execucao_em_andamento)

    def test_segunda_chamada_enquanto_a_primeira_esta_em_andamento_e_bloqueada(
        self, mock_execute
    ):
        _tentar_adquirir_trava_execucao(self.configuracao)

        with self.assertRaises(OperationalExecutionError) as ctx:
            criar_e_iniciar_processamento_para_agente(
                agente=self.agente, actor=self.user, cleaned_data=self.cleaned_data
            )

        self.assertIn("ja esta em execucao", str(ctx.exception).lower())
        mock_execute.assert_not_called()

    def test_concurrency_policy_desligada_ignora_a_trava(self, mock_execute):
        self.configuracao.concurrency_policy = {"block_parallel_per_agent": False}
        self.configuracao.save(update_fields=["concurrency_policy"])
        _tentar_adquirir_trava_execucao(self.configuracao)

        # Mesmo com a trava marcada, a policy desligada deixa passar.
        criar_e_iniciar_processamento_para_agente(
            agente=self.agente, actor=self.user, cleaned_data=self.cleaned_data
        )
        mock_execute.assert_called_once()

    def test_limite_documentos_por_execucao_e_repassado_para_execute_processing(
        self, mock_execute
    ):
        criar_e_iniciar_processamento_para_agente(
            agente=self.agente,
            actor=self.user,
            cleaned_data=self.cleaned_data,
            limite_documentos_por_execucao=10,
        )
        _, kwargs = mock_execute.call_args
        self.assertEqual(kwargs["limite_documentos_por_execucao"], 10)


class ExecutarRotinaAutomaticaAgenteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono3", password="x")

    def test_sem_usuario_responsavel_nao_quebra(self):
        agente, configuracao = _criar_agente(
            criado_por=None, execucao_automatica_ativa=True
        )
        resultado = _executar_rotina_automatica_agente(
            configuracao, montar_payload=MagicMock(), lote_tamanho=10
        )
        self.assertEqual(resultado["status"], RotinaAutomaticaExecucaoStatus.ERRO)
        self.assertEqual(
            RotinaAutomaticaExecucao.objects.filter(agente=agente).count(), 1
        )

    @patch("apps.processamentos.services.operational_execution.criar_e_iniciar_processamento_para_agente")
    def test_sem_trabalho_novo_nao_propaga_excecao(self, mock_criar):
        agente, configuracao = _criar_agente(
            criado_por=self.user, execucao_automatica_ativa=True
        )
        erro = OperationalExecutionError(
            "Todos os arquivos desta pasta ja foram processados anteriormente por este agente."
        )
        erro.sem_trabalho = True
        mock_criar.side_effect = erro
        montar_payload = MagicMock(return_value={"input_source_type": AgentDefaultInputSourceType.NONE})

        resultado = _executar_rotina_automatica_agente(
            configuracao, montar_payload=montar_payload, lote_tamanho=10
        )

        self.assertEqual(resultado["status"], RotinaAutomaticaExecucaoStatus.SEM_DOCUMENTOS)
        self.assertIn("ja foram processados", resultado["motivo"])

    @patch("apps.processamentos.services.operational_execution.criar_e_iniciar_processamento_para_agente")
    def test_trava_ocupada_registra_como_bloqueada(self, mock_criar):
        agente, configuracao = _criar_agente(
            criado_por=self.user, execucao_automatica_ativa=True
        )
        mock_criar.side_effect = OperationalExecutionError(
            "Este agente ja esta em execucao agora. Aguarde terminar antes de executar de novo."
        )
        montar_payload = MagicMock(return_value={"input_source_type": AgentDefaultInputSourceType.NONE})

        resultado = _executar_rotina_automatica_agente(
            configuracao, montar_payload=montar_payload, lote_tamanho=10
        )

        self.assertEqual(resultado["status"], RotinaAutomaticaExecucaoStatus.BLOQUEADA)

    @patch("apps.processamentos.services.operational_execution._registrar_historico_rotina")
    @patch("apps.processamentos.services.operational_execution.criar_e_iniciar_processamento_para_agente")
    def test_repassa_o_lote_tamanho_recebido_para_limite_documentos(
        self, mock_criar, mock_registrar
    ):
        # lote_tamanho e sempre calculado pelo chamador (global, ou 6 no
        # caso de intervalo < 30min) — esta funcao so repassa o valor
        # recebido, sem nenhuma logica de override por conta propria.
        agente, configuracao = _criar_agente(
            criado_por=self.user, execucao_automatica_ativa=True
        )
        montar_payload = MagicMock(return_value={"input_source_type": AgentDefaultInputSourceType.NONE})
        mock_criar.return_value = MagicMock(codigo="PROC-TESTE")

        _executar_rotina_automatica_agente(
            configuracao, montar_payload=montar_payload, lote_tamanho=6
        )

        _, kwargs = mock_criar.call_args
        self.assertEqual(kwargs["limite_documentos_por_execucao"], 6)


class ExecutarRotinasAutomaticasAgentesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono4", password="x")
        # Garante estado limpo do singleton entre testes (mesmo objeto pk=1
        # em todos, valores default: ativa=True, intervalo=60, sem
        # proxima_execucao ainda agendada).
        ConfiguracaoGeral.objects.all().delete()

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_so_considera_agentes_com_rotina_ativa(self, mock_rodar):
        mock_rodar.return_value = {"agente": "x", "status": "executada"}
        _criar_agente(criado_por=self.user, execucao_automatica_ativa=False)
        agente_ativo, _ = _criar_agente(
            criado_por=self.user, execucao_automatica_ativa=True
        )

        executar_rotinas_automaticas_agentes()

        self.assertEqual(mock_rodar.call_count, 1)

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_interruptor_geral_desligado_nao_roda_nenhum_agente(self, mock_rodar):
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_agentes_ativa = False
        config.save(update_fields=["rotina_automatica_agentes_ativa"])
        _criar_agente(criado_por=self.user, execucao_automatica_ativa=True)

        resultados = executar_rotinas_automaticas_agentes()

        self.assertEqual(resultados, [])
        mock_rodar.assert_not_called()

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_nao_considera_quando_proxima_rodada_global_ainda_nao_chegou(self, mock_rodar):
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_proxima_execucao_em = timezone.now() + timedelta(minutes=30)
        config.save(update_fields=["rotina_automatica_proxima_execucao_em"])
        _criar_agente(criado_por=self.user, execucao_automatica_ativa=True)

        executar_rotinas_automaticas_agentes()

        mock_rodar.assert_not_called()

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_considera_quando_proxima_rodada_global_ja_passou(self, mock_rodar):
        mock_rodar.return_value = {"agente": "x", "status": "executada"}
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_proxima_execucao_em = timezone.now() - timedelta(minutes=1)
        config.save(update_fields=["rotina_automatica_proxima_execucao_em"])
        _criar_agente(criado_por=self.user, execucao_automatica_ativa=True)

        executar_rotinas_automaticas_agentes()

        mock_rodar.assert_called_once()

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_nao_considera_antes_do_horario_de_inicio_agendado(self, mock_rodar):
        # rotina_automatica_proxima_execucao_em ainda None (nunca rodou) —
        # respeita o horario de inicio configurado.
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_inicio_em = timezone.now() + timedelta(hours=1)
        config.save(update_fields=["rotina_automatica_inicio_em"])
        _criar_agente(criado_por=self.user, execucao_automatica_ativa=True)

        executar_rotinas_automaticas_agentes()

        mock_rodar.assert_not_called()

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_considera_quando_horario_de_inicio_agendado_ja_passou(self, mock_rodar):
        mock_rodar.return_value = {"agente": "x", "status": "executada"}
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_inicio_em = timezone.now() - timedelta(minutes=1)
        config.save(update_fields=["rotina_automatica_inicio_em"])
        _criar_agente(criado_por=self.user, execucao_automatica_ativa=True)

        executar_rotinas_automaticas_agentes()

        mock_rodar.assert_called_once()

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_horario_de_inicio_e_ignorado_apos_a_primeira_rodada(self, mock_rodar):
        # Uma vez que rotina_automatica_proxima_execucao_em ja foi
        # calculado (rodou pelo menos uma vez), o horario de inicio nao
        # importa mais — so o intervalo entre rodadas vale.
        mock_rodar.return_value = {"agente": "x", "status": "executada"}
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_inicio_em = timezone.now() + timedelta(hours=1)
        config.rotina_automatica_proxima_execucao_em = timezone.now() - timedelta(minutes=1)
        config.save(
            update_fields=["rotina_automatica_inicio_em", "rotina_automatica_proxima_execucao_em"]
        )
        _criar_agente(criado_por=self.user, execucao_automatica_ativa=True)

        executar_rotinas_automaticas_agentes()

        mock_rodar.assert_called_once()

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_agente_inativo_nao_e_considerado_mesmo_com_rotina_ativa(self, mock_rodar):
        agente, configuracao = _criar_agente(
            criado_por=self.user, execucao_automatica_ativa=True
        )
        agente.status = AgentStatus.INATIVO
        agente.save(update_fields=["status"])

        executar_rotinas_automaticas_agentes()

        mock_rodar.assert_not_called()

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_reagenda_a_proxima_rodada_global_antes_de_executar(self, mock_rodar):
        mock_rodar.return_value = {"agente": "x", "status": "executada"}
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_intervalo_minutos = 45
        config.save(update_fields=["rotina_automatica_intervalo_minutos"])
        _criar_agente(criado_por=self.user, execucao_automatica_ativa=True)
        agora = timezone.now()

        executar_rotinas_automaticas_agentes()

        config.refresh_from_db()
        self.assertAlmostEqual(
            (config.rotina_automatica_proxima_execucao_em - agora).total_seconds(),
            timedelta(minutes=45).total_seconds(),
            delta=3,
        )

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_intervalo_abaixo_de_30_forca_lote_de_6(self, mock_rodar):
        mock_rodar.return_value = {"agente": "x", "status": "executada"}
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_intervalo_minutos = 15
        config.rotina_automatica_lote_tamanho = 40  # deve ser ignorado
        config.save(update_fields=["rotina_automatica_intervalo_minutos", "rotina_automatica_lote_tamanho"])
        _criar_agente(criado_por=self.user, execucao_automatica_ativa=True)

        executar_rotinas_automaticas_agentes()

        _, kwargs = mock_rodar.call_args
        self.assertEqual(kwargs["lote_tamanho"], 6)

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_intervalo_de_30_ou_mais_usa_o_lote_global_configurado(self, mock_rodar):
        mock_rodar.return_value = {"agente": "x", "status": "executada"}
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_intervalo_minutos = 30
        config.rotina_automatica_lote_tamanho = 8
        config.save(update_fields=["rotina_automatica_intervalo_minutos", "rotina_automatica_lote_tamanho"])
        _criar_agente(criado_por=self.user, execucao_automatica_ativa=True)

        executar_rotinas_automaticas_agentes()

        _, kwargs = mock_rodar.call_args
        self.assertEqual(kwargs["lote_tamanho"], 8)


class UltimaVerificacaoHeartbeatTests(TestCase):
    """ConfiguracaoGeral.rotina_automatica_ultima_verificacao_em — heartbeat
    exibido em Administrador > Rotina automatica pra confirmar que o
    worker esta de fato chamando essa rotina no intervalo esperado. Sem
    isso, "nada elegivel ainda"/"interruptor desligado" e "worker parado"
    ficam indistinguiveis (historico igualmente vazio nos tres casos) —
    caso real: usuario deixou a rotina rodando ~3h sem documento pendente
    e nao tinha como confirmar que a checagem estava acontecendo
    (21/08/2026)."""

    def setUp(self):
        self.user = User.objects.create_user(username="dono5", password="x")
        ConfiguracaoGeral.objects.all().delete()

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_atualiza_mesmo_com_interruptor_geral_desligado(self, mock_rodar):
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_agentes_ativa = False
        config.save(update_fields=["rotina_automatica_agentes_ativa"])
        antes = timezone.now()

        executar_rotinas_automaticas_agentes()

        config.refresh_from_db()
        self.assertIsNotNone(config.rotina_automatica_ultima_verificacao_em)
        self.assertGreaterEqual(config.rotina_automatica_ultima_verificacao_em, antes)
        mock_rodar.assert_not_called()

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_atualiza_mesmo_sem_rodada_elegivel_ainda(self, mock_rodar):
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_proxima_execucao_em = timezone.now() + timedelta(minutes=30)
        config.save(update_fields=["rotina_automatica_proxima_execucao_em"])
        _criar_agente(criado_por=self.user, execucao_automatica_ativa=True)
        antes = timezone.now()

        executar_rotinas_automaticas_agentes()

        config.refresh_from_db()
        self.assertIsNotNone(config.rotina_automatica_ultima_verificacao_em)
        self.assertGreaterEqual(config.rotina_automatica_ultima_verificacao_em, antes)
        mock_rodar.assert_not_called()

    @patch("apps.processamentos.services.operational_execution._executar_rotina_automatica_agente")
    def test_atualiza_quando_roda_normalmente(self, mock_rodar):
        mock_rodar.return_value = {"agente": "x", "status": "executada"}
        _criar_agente(criado_por=self.user, execucao_automatica_ativa=True)
        antes = timezone.now()

        executar_rotinas_automaticas_agentes()

        config = ConfiguracaoGeral.obter()
        self.assertIsNotNone(config.rotina_automatica_ultima_verificacao_em)
        self.assertGreaterEqual(config.rotina_automatica_ultima_verificacao_em, antes)
        mock_rodar.assert_called_once()


class RegistrarHistoricoRotinaTests(TestCase):
    """RotinaAutomaticaExecucao — o registro que alimenta a tela
    Administrador > Rotina automatica (rodou ou nao, quantos documentos,
    quantos com sucesso/erro e os motivos)."""

    def setUp(self):
        self.user = User.objects.create_user(username="dono6", password="x")
        self.agente, _ = _criar_agente(criado_por=self.user)

    def _processamento_com_documentos(self, *, sucesso=0, erro=0, mensagem="Falha tecnica X"):
        processamento = Processamento.objects.create(
            codigo=f"PROC-HIST-{Processamento.objects.count()}",
            iniciado_por=self.user,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
        )
        for _ in range(sucesso):
            processamento.documentos.create(
                nome_arquivo="ok.pdf",
                source_type=ProcessingInputSourceType.LOCAL_FOLDER,
                source_reference="ok.pdf",
                status=DocumentStatus.PROCESSADO,
            )
        for _ in range(erro):
            processamento.documentos.create(
                nome_arquivo="falhou.pdf",
                source_type=ProcessingInputSourceType.LOCAL_FOLDER,
                source_reference="falhou.pdf",
                status=DocumentStatus.ERRO,
                mensagem_erro=mensagem,
            )
        return processamento

    def test_sem_processamento_registra_zero_documentos(self):
        resultado = _registrar_historico_rotina(
            self.agente,
            iniciado_em=timezone.now(),
            status=RotinaAutomaticaExecucaoStatus.SEM_DOCUMENTOS,
            motivo="Nenhum PDF pendente encontrado.",
        )
        self.assertEqual(resultado["total_documentos"], 0)
        historico = RotinaAutomaticaExecucao.objects.get(agente=self.agente)
        self.assertEqual(historico.status, RotinaAutomaticaExecucaoStatus.SEM_DOCUMENTOS)
        self.assertIsNone(historico.processamento)

    def test_conta_sucesso_e_erro_a_partir_do_processamento(self):
        processamento = self._processamento_com_documentos(sucesso=3, erro=2)

        resultado = _registrar_historico_rotina(
            self.agente,
            iniciado_em=timezone.now(),
            status=RotinaAutomaticaExecucaoStatus.EXECUTADA,
            processamento=processamento,
        )

        self.assertEqual(resultado["total_documentos"], 5)
        self.assertEqual(resultado["total_sucesso"], 3)
        self.assertEqual(resultado["total_erro"], 2)
        self.assertIn("Falha tecnica X", resultado["motivo"])

    def test_motivo_explicito_tem_prioridade_sobre_erros_do_processamento(self):
        processamento = self._processamento_com_documentos(erro=1, mensagem="Erro tecnico")

        resultado = _registrar_historico_rotina(
            self.agente,
            iniciado_em=timezone.now(),
            status=RotinaAutomaticaExecucaoStatus.EXECUTADA,
            processamento=processamento,
            motivo="Motivo customizado",
        )

        self.assertEqual(resultado["motivo"], "Motivo customizado")


@patch("apps.processamentos.services.agent_execution._execute_document")
class LimiteDocumentosPorExecucaoTests(TestCase):
    """execute_processing(..., limite_documentos_por_execucao=N) — o
    coracao da rotina automatica: cada rodada so DESCOBRE (cria
    DocumentoEntrada) e executa os N documentos mais antigos, deixando o
    resto de fora do processamento desta rodada — nao descoberto, disponivel
    pra proxima rodada (novo Processamento) descobrir do zero.

    Ate a correcao de 23/08/2026 (caso real: pasta com 11 PDFs, lote=10 —
    a rodada descobria os 11 de uma vez e so executava 10, deixando 1
    pendente esquecido dentro de um processamento ja concluido_sucesso), a
    descoberta nao respeitava esse limite — so a selecao pra execucao
    (_select_documentos()[:limite]) respeitava, entao o processamento
    acabava com mais documentos "descobertos" do que executados. Ver
    document_sources.prepare_documentos(limite_novos_documentos=...)."""

    def setUp(self):
        self.user = User.objects.create_user(username="dono5", password="x")
        self.ai_integration = AIProviderIntegration.objects.create(
            nome="Integracao Limite",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-teste",
        )
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.local_integration = LocalStorageIntegration.objects.create(
            nome="Pasta Limite",
            base_path=str(self.base_path),
            status=IntegrationStatus.ATIVA,
            allowed_extensions=["pdf"],
        )
        self.agente = AgenteIA.objects.create(
            nome="Agente Limite",
            slug="agente-limite",
            tipo=AgentType.GENERICO,
            ai_provider_integration=self.ai_integration,
            status=AgentStatus.ATIVO,
            prompt_base="prompt",
        )
        AgenteConfiguracaoOperacional.objects.create(
            agente=self.agente,
            default_input_source_type=AgentDefaultInputSourceType.LOCAL_FOLDER,
            default_local_storage_integration=self.local_integration,
        )
        for i in range(5):
            (self.base_path / f"doc{i}.pdf").write_bytes(b"pdf")

    def _processamento(self):
        return Processamento.objects.create(
            codigo=f"PROC-LIMITE-{Processamento.objects.count()}",
            iniciado_por=self.user,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            local_storage_integration=self.local_integration,
            local_relative_input_path="",
        )

    @staticmethod
    def _fake_execute_document(
        *, processamento, documento, integration, model_name, execution_params, actor
    ):
        # Simula so o que _execute_document faz que interessa aqui: marca
        # o documento como processado e devolve uma saida real (nao um
        # MagicMock) — publicar_saida_final le bytes de verdade do arquivo
        # ao montar o ZIP final.
        output_record = DocumentoSaidaProcessamento(
            processamento=processamento,
            documento=documento,
            status=OutputDocumentStatus.GERADO,
            scope_type=ExecutionScopeType.INDIVIDUAL,
        )
        output_record.arquivo.save(
            f"{documento.nome_arquivo}.json", ContentFile(b'{"ok": true}'), save=False
        )
        output_record.save()
        documento.status = DocumentStatus.PROCESSADO
        documento.save(update_fields=["status"])
        return {"output_record": output_record}

    def test_processa_so_o_limite_sem_descobrir_o_resto_da_pasta(
        self, mock_execute_document
    ):
        mock_execute_document.side_effect = self._fake_execute_document
        processamento = self._processamento()

        execute_processing(processamento, self.user, limite_documentos_por_execucao=3)

        documentos = processamento.documentos.all()
        # So os 3 do limite sao descobertos por este processamento — os
        # outros 2 arquivos da pasta nem geram DocumentoEntrada aqui (ficam
        # disponiveis pra proxima rodada descobrir do zero, sem sobrar
        # pendente esquecido dentro deste processamento ja concluido).
        self.assertEqual(documentos.count(), 3)
        self.assertEqual(
            documentos.filter(status=DocumentStatus.PROCESSADO).count(), 3
        )
        self.assertEqual(
            documentos.filter(status=DocumentStatus.PENDENTE).count(), 0
        )
        self.assertEqual(mock_execute_document.call_count, 3)

    def test_sem_limite_processa_todos_como_antes(self, mock_execute_document):
        mock_execute_document.side_effect = self._fake_execute_document
        processamento = self._processamento()

        execute_processing(processamento, self.user)

        documentos = processamento.documentos.all()
        self.assertEqual(
            documentos.filter(status=DocumentStatus.PROCESSADO).count(), 5
        )
        self.assertEqual(mock_execute_document.call_count, 5)

    def test_segunda_rodada_pega_os_que_sobraram(self, mock_execute_document):
        # Cada rodada da rotina automatica e um Processamento NOVO (ver
        # operational_execution.criar_e_iniciar_processamento_para_agente) —
        # nao a mesma instancia chamada de novo. rodada_2 descobre so os
        # arquivos que rodada_1 nao pegou (dedup por nome — ver
        # document_sources._arquivo_local_ja_processado_anteriormente).
        mock_execute_document.side_effect = self._fake_execute_document
        rodada_1 = self._processamento()
        rodada_2 = self._processamento()

        execute_processing(rodada_1, self.user, limite_documentos_por_execucao=3)
        execute_processing(rodada_2, self.user, limite_documentos_por_execucao=3)

        self.assertEqual(rodada_1.documentos.count(), 3)
        self.assertEqual(rodada_2.documentos.count(), 2)
        self.assertEqual(
            rodada_1.documentos.filter(status=DocumentStatus.PROCESSADO).count(), 3
        )
        self.assertEqual(
            rodada_2.documentos.filter(status=DocumentStatus.PROCESSADO).count(), 2
        )
        self.assertEqual(mock_execute_document.call_count, 5)


class RotinaAutomaticaAgentesViewTests(TestCase):
    """Tela Administrador > Rotina automatica: liga/desliga geral,
    intervalo global e historico de execucoes (ver operational_execution
    e selectors.listar_historico_rotina_automatica)."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-rotina", password="x", email="admin@teste.com"
        )
        self.client.force_login(self.admin)
        ConfiguracaoGeral.objects.all().delete()

    def test_usuario_nao_admin_nao_acessa(self):
        comum = User.objects.create_user(username="comum-rotina", password="x")
        self.client.force_login(comum)
        resp = self.client.get(reverse("portal_rotina_automatica"))
        self.assertEqual(resp.status_code, 403)

    def test_pagina_carrega_com_configuracao_padrao(self):
        resp = self.client.get(reverse("portal_rotina_automatica"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Rotina automática")

    def test_pagina_lista_historico_existente(self):
        agente, _ = _criar_agente(criado_por=self.admin)
        RotinaAutomaticaExecucao.objects.create(
            agente=agente,
            status=RotinaAutomaticaExecucaoStatus.SEM_DOCUMENTOS,
            iniciado_em=timezone.now(),
            motivo="Nenhum PDF pendente encontrado.",
        )
        resp = self.client.get(reverse("portal_rotina_automatica"))
        self.assertContains(resp, agente.nome)
        self.assertContains(resp, "Nenhum PDF pendente encontrado.")

    def test_pagina_exibe_heartbeat_da_ultima_verificacao(self):
        # ConfiguracaoGeral.rotina_automatica_ultima_verificacao_em setado
        # (ex.: pelo worker) precisa aparecer na tela, mesmo sem nenhum
        # registro no historico — e o que confirma pro usuario que o
        # worker esta de fato checando (ver UltimaVerificacaoHeartbeatTests).
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_ultima_verificacao_em = timezone.now()
        config.save(update_fields=["rotina_automatica_ultima_verificacao_em"])

        resp = self.client.get(reverse("portal_rotina_automatica"))

        self.assertContains(resp, "Última verificação do worker")

    def test_pagina_carrega_sem_heartbeat_ainda_registrado(self):
        # rotina_automatica_ultima_verificacao_em ainda None (worker nunca
        # chamou o comando) nao pode quebrar a pagina.
        resp = self.client.get(reverse("portal_rotina_automatica"))

        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Última verificação do worker")

    def test_salvar_liga_e_ajusta_intervalo_e_lote(self):
        resp = self.client.post(
            reverse("portal_rotina_automatica_salvar"),
            {
                "rotina_automatica_agentes_ativa": "1",
                "rotina_automatica_intervalo_minutos": "20",
                "rotina_automatica_lote_tamanho": "15",
            },
        )
        self.assertRedirects(resp, reverse("portal_rotina_automatica"))
        config = ConfiguracaoGeral.obter()
        self.assertTrue(config.rotina_automatica_agentes_ativa)
        self.assertEqual(config.rotina_automatica_intervalo_minutos, 20)
        self.assertEqual(config.rotina_automatica_lote_tamanho, 15)

    def test_salvar_limita_lote_ao_minimo_de_1(self):
        self.client.post(
            reverse("portal_rotina_automatica_salvar"),
            {
                "rotina_automatica_agentes_ativa": "1",
                "rotina_automatica_intervalo_minutos": "60",
                "rotina_automatica_lote_tamanho": "0",
            },
        )
        config = ConfiguracaoGeral.obter()
        self.assertEqual(config.rotina_automatica_lote_tamanho, 1)

    def test_salvar_limita_lote_ao_maximo_de_100(self):
        self.client.post(
            reverse("portal_rotina_automatica_salvar"),
            {
                "rotina_automatica_agentes_ativa": "1",
                "rotina_automatica_intervalo_minutos": "60",
                "rotina_automatica_lote_tamanho": "999",
            },
        )
        config = ConfiguracaoGeral.obter()
        self.assertEqual(config.rotina_automatica_lote_tamanho, 100)

    def test_salvar_com_horario_de_inicio_agenda_a_primeira_rodada(self):
        self.client.post(
            reverse("portal_rotina_automatica_salvar"),
            {
                "rotina_automatica_agentes_ativa": "1",
                "rotina_automatica_intervalo_minutos": "60",
                "rotina_automatica_lote_tamanho": "10",
                "rotina_automatica_inicio_em": "2026-08-20T19:20",
            },
        )
        config = ConfiguracaoGeral.obter()
        self.assertIsNotNone(config.rotina_automatica_inicio_em)
        inicio_local = timezone.localtime(config.rotina_automatica_inicio_em)
        self.assertEqual(inicio_local.hour, 19)
        self.assertEqual(inicio_local.minute, 20)
        # Novo horario de inicio (era None) — reseta o agendamento para o
        # novo horario valer na proxima checagem do worker.
        self.assertIsNone(config.rotina_automatica_proxima_execucao_em)

    def test_salvar_com_mesmo_horario_de_inicio_preserva_proxima_rodada(self):
        config = ConfiguracaoGeral.obter()
        proxima_original = timezone.now() + timedelta(minutes=45)
        config.rotina_automatica_proxima_execucao_em = proxima_original
        config.save(update_fields=["rotina_automatica_proxima_execucao_em"])
        # Primeiro save fixa o horario de inicio...
        self.client.post(
            reverse("portal_rotina_automatica_salvar"),
            {
                "rotina_automatica_agentes_ativa": "1",
                "rotina_automatica_intervalo_minutos": "60",
                "rotina_automatica_lote_tamanho": "10",
                "rotina_automatica_inicio_em": "2026-08-20T19:20",
            },
        )
        config.refresh_from_db()
        config.rotina_automatica_proxima_execucao_em = proxima_original
        config.save(update_fields=["rotina_automatica_proxima_execucao_em"])

        # ...segundo save com o MESMO horario nao deve resetar o
        # agendamento ja calculado (ex.: admin so ajustando o intervalo).
        self.client.post(
            reverse("portal_rotina_automatica_salvar"),
            {
                "rotina_automatica_agentes_ativa": "1",
                "rotina_automatica_intervalo_minutos": "90",
                "rotina_automatica_lote_tamanho": "10",
                "rotina_automatica_inicio_em": "2026-08-20T19:20",
            },
        )
        config.refresh_from_db()
        self.assertEqual(config.rotina_automatica_proxima_execucao_em, proxima_original)

    def test_salvar_removendo_horario_de_inicio_reseta_proxima_rodada(self):
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_inicio_em = timezone.now() + timedelta(hours=1)
        config.rotina_automatica_proxima_execucao_em = timezone.now() + timedelta(minutes=45)
        config.save(
            update_fields=["rotina_automatica_inicio_em", "rotina_automatica_proxima_execucao_em"]
        )

        self.client.post(
            reverse("portal_rotina_automatica_salvar"),
            {
                "rotina_automatica_agentes_ativa": "1",
                "rotina_automatica_intervalo_minutos": "60",
                "rotina_automatica_lote_tamanho": "10",
                # rotina_automatica_inicio_em ausente do POST = removido
            },
        )
        config.refresh_from_db()
        self.assertIsNone(config.rotina_automatica_inicio_em)
        self.assertIsNone(config.rotina_automatica_proxima_execucao_em)

    def test_salvar_com_horario_de_inicio_invalido_nao_quebra(self):
        resp = self.client.post(
            reverse("portal_rotina_automatica_salvar"),
            {
                "rotina_automatica_agentes_ativa": "1",
                "rotina_automatica_intervalo_minutos": "60",
                "rotina_automatica_lote_tamanho": "10",
                "rotina_automatica_inicio_em": "isso-nao-e-uma-data",
            },
        )
        self.assertEqual(resp.status_code, 302)
        config = ConfiguracaoGeral.obter()
        self.assertIsNone(config.rotina_automatica_inicio_em)

    def test_salvar_sem_marcar_o_toggle_desliga(self):
        config = ConfiguracaoGeral.obter()
        config.rotina_automatica_agentes_ativa = True
        config.save(update_fields=["rotina_automatica_agentes_ativa"])

        self.client.post(
            reverse("portal_rotina_automatica_salvar"),
            {"rotina_automatica_intervalo_minutos": "60"},
        )

        config.refresh_from_db()
        self.assertFalse(config.rotina_automatica_agentes_ativa)

    def test_salvar_limita_intervalo_ao_minimo_de_10(self):
        self.client.post(
            reverse("portal_rotina_automatica_salvar"),
            {
                "rotina_automatica_agentes_ativa": "1",
                "rotina_automatica_intervalo_minutos": "1",
            },
        )
        config = ConfiguracaoGeral.obter()
        self.assertEqual(config.rotina_automatica_intervalo_minutos, 10)

    def test_salvar_limita_intervalo_ao_maximo_de_1440(self):
        self.client.post(
            reverse("portal_rotina_automatica_salvar"),
            {
                "rotina_automatica_agentes_ativa": "1",
                "rotina_automatica_intervalo_minutos": "999999",
            },
        )
        config = ConfiguracaoGeral.obter()
        self.assertEqual(config.rotina_automatica_intervalo_minutos, 1440)
