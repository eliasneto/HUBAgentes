"""
Loop de retentativa automatica quando o PROVEDOR de IA (nao o nosso sistema)
esta sobrecarregado — ex.: Gemini HTTP 503 "This model is currently
experiencing high demand". Ver Processamento.retentativa_sobrecarga_ativa,
agent_execution.retentar_processamentos_com_sobrecarga e o management command
retentar_processamentos_sobrecarga_provedor (chamado periodicamente pelo
worker, ver docker-compose.yml).

Caso real que motivou a mudanca: agente "JHS (Licitacao)", 19/08/2026 —
gemini-2.5-pro devolvendo 503 repetidamente ao processar varios PDFs
grandes em sequencia. O cliente as vezes precisa enviar ate 50 documentos
de uma vez; desistir depois de 1-2 tentativas rapidas descartava trabalho
que teria sucesso se tentado de novo mais tarde.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from apps.processamentos.models import DocumentStatus, ProcessingStatus
from apps.processamentos.services.agent_execution import (
    LIMITE_RETENTATIVA_SOBRECARGA,
    _eh_erro_modelo_sobrecarregado,
    _iniciar_retentativa_sobrecarga,
    _processar_rodada_retentativa_sobrecarga,
    _proximo_intervalo_retentativa_sobrecarga,
)
from apps.processamentos.services.stalled_processing import _is_candidate


class EhErroModeloSobrecarregadoTests(SimpleTestCase):
    def test_mensagem_gemini_high_demand_e_sobrecarga(self):
        msg = (
            'Falha HTTP 503 ao executar o agente no provedor: {"error": '
            '{"code": 503, "message": "This model is currently experiencing '
            'high demand. Spikes in demand are usually temporary. Please '
            'try again later.", "status": "UNAVAILABLE"}}'
        )
        self.assertTrue(_eh_erro_modelo_sobrecarregado(msg))

    def test_mensagem_generica_503_unavailable_e_sobrecarga(self):
        msg = 'Falha HTTP 503 ao executar o agente no provedor: {"status": "UNAVAILABLE"}'
        self.assertTrue(_eh_erro_modelo_sobrecarregado(msg))

    def test_budget_invalido_nao_e_sobrecarga(self):
        # HTTP 400, erro de configuracao (ver correcao 1.5.19) - nao deve
        # entrar no loop de 2h, e um erro definitivo diferente.
        msg = 'Falha HTTP 400 ao executar o agente no provedor: {"message": "Budget 0 is invalid."}'
        self.assertFalse(_eh_erro_modelo_sobrecarregado(msg))

    def test_timeout_de_conexao_nao_e_sobrecarga(self):
        msg = "Falha de conexao ao executar o agente no provedor: timed out"
        self.assertFalse(_eh_erro_modelo_sobrecarregado(msg))

    def test_mensagem_vazia_nao_e_sobrecarga(self):
        self.assertFalse(_eh_erro_modelo_sobrecarregado(""))
        self.assertFalse(_eh_erro_modelo_sobrecarregado(None))


class ProximoIntervaloRetentativaSobrecargaTests(SimpleTestCase):
    def test_cresce_a_cada_tentativa(self):
        intervalos = [
            _proximo_intervalo_retentativa_sobrecarga(n).total_seconds() / 60
            for n in range(6)
        ]
        self.assertEqual(intervalos, [2, 5, 10, 15, 20, 30])

    def test_estabiliza_no_teto_apos_a_lista_acabar(self):
        self.assertEqual(
            _proximo_intervalo_retentativa_sobrecarga(6),
            _proximo_intervalo_retentativa_sobrecarga(100),
        )
        self.assertEqual(
            _proximo_intervalo_retentativa_sobrecarga(100).total_seconds() / 60, 30
        )


class IsCandidateExcluiRetentativaSobrecargaTests(SimpleTestCase):
    """Sem essa exclusao, o detector de processamentos orfaos (timeout de
    5min) mataria o loop de retentativa por sobrecarga antes de completar
    uma unica rodada (intervalos chegam a 30min entre tentativas)."""

    def _processamento(self, *, status, retentativa_ativa):
        p = MagicMock()
        p.status = status
        p.retentativa_sobrecarga_ativa = retentativa_ativa
        return p

    def test_processamento_em_loop_de_sobrecarga_nunca_e_candidato(self):
        p = self._processamento(
            status=ProcessingStatus.EM_PROCESSAMENTO, retentativa_ativa=True
        )
        self.assertFalse(_is_candidate(p))

    def test_processamento_normal_em_processamento_continua_candidato(self):
        p = self._processamento(
            status=ProcessingStatus.EM_PROCESSAMENTO, retentativa_ativa=False
        )
        self.assertTrue(_is_candidate(p))

    def test_processamento_concluido_nunca_e_candidato_independente_da_flag(self):
        p = self._processamento(
            status=ProcessingStatus.CONCLUIDO_SUCESSO, retentativa_ativa=False
        )
        self.assertFalse(_is_candidate(p))


def _queryset_mock(itens):
    """MagicMock que se comporta como um QuerySet simples o bastante para
    _processar_rodada_retentativa_sobrecarga: list(qs) devolve `itens`,
    qs.exists() comeca refletindo se a lista NAO esta vazia (o teste pode
    sobrescrever depois, simulando o efeito das tentativas)."""
    qs = MagicMock()
    qs.__iter__.return_value = iter(itens)
    qs.exists.return_value = bool(itens)
    return qs


@patch("apps.processamentos.services.agent_execution._finalizar_loop_sobrecarga")
@patch("apps.processamentos.services.agent_execution._tentar_executar_documento_individual")
@patch("apps.processamentos.services.agent_execution._build_execution_params")
class ProcessarRodadaRetentativaSobrecargaTests(SimpleTestCase):
    def _processamento(self, *, iniciada_ha, documentos_erro_reprocessavel):
        p = MagicMock()
        p.retentativa_sobrecarga_iniciada_em = timezone.now() - iniciada_ha
        p.retentativa_sobrecarga_tentativas = 0
        p.ai_provider_integration_snapshot = None
        p.agente.ai_provider_integration = MagicMock()
        p.modelo_snapshot = "gemini-2.5-pro"
        p.documentos.filter.return_value = _queryset_mock(documentos_erro_reprocessavel)
        return p

    def test_desiste_apos_2h_sem_tentar_de_novo(
        self, mock_params, mock_tentar, mock_finalizar
    ):
        processamento = self._processamento(
            iniciada_ha=timedelta(hours=2, minutes=1),
            documentos_erro_reprocessavel=[MagicMock()],
        )

        resultado = _processar_rodada_retentativa_sobrecarga(
            processamento, agora=timezone.now()
        )

        self.assertEqual(resultado, "desistiu_apos_2h")
        mock_tentar.assert_not_called()
        mock_finalizar.assert_called_once_with(processamento, desistiu_por_timeout=True)

    def test_nao_desiste_um_minuto_antes_do_teto(
        self, mock_params, mock_tentar, mock_finalizar
    ):
        doc = MagicMock()
        processamento = self._processamento(
            iniciada_ha=LIMITE_RETENTATIVA_SOBRECARGA - timedelta(minutes=1),
            documentos_erro_reprocessavel=[doc],
        )
        # ainda ha 1 documento erro+reprocessavel depois de tentar -> reagenda
        processamento.documentos.filter.return_value.exists.return_value = True

        resultado = _processar_rodada_retentativa_sobrecarga(
            processamento, agora=timezone.now()
        )

        mock_tentar.assert_called_once()
        self.assertEqual(resultado, "tentando_de_novo")
        mock_finalizar.assert_not_called()

    def test_finaliza_quando_nao_ha_mais_documento_pendente(
        self, mock_params, mock_tentar, mock_finalizar
    ):
        processamento = self._processamento(
            iniciada_ha=timedelta(minutes=10),
            documentos_erro_reprocessavel=[MagicMock()],
        )
        # apos a tentativa, nao sobrou nenhum documento erro+reprocessavel
        processamento.documentos.filter.return_value.exists.return_value = False

        resultado = _processar_rodada_retentativa_sobrecarga(
            processamento, agora=timezone.now()
        )

        mock_tentar.assert_called_once()
        self.assertEqual(resultado, "concluido")
        mock_finalizar.assert_called_once_with(processamento)

    def test_sem_documentos_elegiveis_finaliza_direto_sem_tentar(
        self, mock_params, mock_tentar, mock_finalizar
    ):
        processamento = self._processamento(
            iniciada_ha=timedelta(minutes=10),
            documentos_erro_reprocessavel=[],
        )

        resultado = _processar_rodada_retentativa_sobrecarga(
            processamento, agora=timezone.now()
        )

        mock_tentar.assert_not_called()
        self.assertEqual(resultado, "concluido_sem_pendentes")
        mock_finalizar.assert_called_once_with(processamento)

    def test_reagenda_com_intervalo_crescente_a_cada_rodada(
        self, mock_params, mock_tentar, mock_finalizar
    ):
        doc = MagicMock()
        processamento = self._processamento(
            iniciada_ha=timedelta(minutes=10),
            documentos_erro_reprocessavel=[doc],
        )
        processamento.documentos.filter.return_value.exists.return_value = True
        # refresh_from_db no MagicMock e um no-op (nao ha banco real aqui) -
        # o valor setado abaixo simula a contagem de tentativas que o codigo
        # ve antes de incrementar.
        processamento.retentativa_sobrecarga_tentativas = 2

        antes = timezone.now()
        _processar_rodada_retentativa_sobrecarga(processamento, agora=antes)

        # tentativas incrementado de 2 -> 3, intervalo correspondente = 15min
        self.assertEqual(processamento.retentativa_sobrecarga_tentativas, 3)
        proxima = processamento.retentativa_sobrecarga_proxima_em
        self.assertAlmostEqual(
            (proxima - antes).total_seconds(), timedelta(minutes=15).total_seconds(),
            delta=5,
        )


class IniciarRetentativaSobrecargaTests(SimpleTestCase):
    """Ponto de entrada chamado por execute_processing quando o primeiro
    lote termina com erro de sobrecarga do provedor (ver
    _eh_erro_modelo_sobrecarregado) — liga o loop em vez de concluir com
    erro/atencao na hora."""

    @patch("apps.processamentos.services.agent_execution._registrar_atividade_processamento")
    def test_liga_o_loop_com_estado_inicial_correto(self, mock_registrar):
        processamento = MagicMock()

        antes = timezone.now()
        _iniciar_retentativa_sobrecarga(processamento)
        depois = timezone.now()

        self.assertTrue(processamento.retentativa_sobrecarga_ativa)
        self.assertEqual(processamento.retentativa_sobrecarga_tentativas, 0)
        self.assertTrue(
            antes <= processamento.retentativa_sobrecarga_iniciada_em <= depois
        )
        self.assertEqual(processamento.status, ProcessingStatus.EM_PROCESSAMENTO)
        # Nao seta mensagem_erro de proposito: o painel "Ver erro" do
        # front-end aparece sempre que esse campo nao esta vazio,
        # independente do status — mostraria um erro vermelho durante algo
        # que e so uma espera. O indicativo "em andamento" vem de
        # etapa_atual (ja registrado via _registrar_atividade_processamento,
        # mockado nesta classe de teste).
        mock_registrar.assert_called_once()
        self.assertIn(
            "sobrecarregado", mock_registrar.call_args.kwargs["etapa_atual"].lower()
        )
        # Primeira espera = 2min (ver _INTERVALOS_RETENTATIVA_SOBRECARGA_MINUTOS[0])
        primeira_espera = (
            processamento.retentativa_sobrecarga_proxima_em
            - processamento.retentativa_sobrecarga_iniciada_em
        )
        self.assertAlmostEqual(
            primeira_espera.total_seconds(), timedelta(minutes=2).total_seconds(), delta=2
        )
        processamento.save.assert_called_once()
