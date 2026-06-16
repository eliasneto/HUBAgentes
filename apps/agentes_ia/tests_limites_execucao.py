"""
V142-1 / V142-2: testes dos limites de execucoes simultaneas em
`calcular_disponibilidade_agente`.

Testa a ramificacao nova (limite por usuario com prioridade sobre o global,
limiares e 0 = sem limite) isolando as dependencias: o agente passa nos checks
iniciais, o bloqueio de configuracao e neutralizado e os contadores de
concorrencia sao passados ja computados (a contagem em si e um .count() padrao).
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.agentes_ia.models import (
    AgentStatus,
    AgentTriggerMode,
    AgentVisibility,
)
from apps.agentes_ia.services import calcular_disponibilidade_agente
from apps.integracoes.models import IntegrationStatus


def _agente_liberado():
    agente = MagicMock()
    agente.visibilidade = AgentVisibility.USUARIO
    agente.modo_acionamento = AgentTriggerMode.PORTAL
    agente.status = AgentStatus.ATIVO
    agente.permite_execucao_manual = True
    agente.ai_provider_integration.status = IntegrationStatus.ATIVA
    agente.modelo_preferencial = "modelo-teste"
    return agente


def _config(max_por_usuario, max_global):
    cfg = MagicMock()
    cfg.max_execucoes_por_usuario = max_por_usuario
    cfg.max_execucoes_simultaneas = max_global
    return cfg


class LimitesExecucaoTests(SimpleTestCase):

    def setUp(self):
        # Neutraliza o bloqueio por configuracao de origem do agente.
        p1 = patch(
            "apps.agentes_ia.services.obter_bloqueio_execucao_padrao",
            return_value="",
        )
        self.addCleanup(p1.stop)
        p1.start()

        # Evita tocar o banco no check final de execucao em andamento por agente:
        # com contadores pre-computados, esta e a unica query a Processamento.
        p2 = patch("apps.agentes_ia.services.Processamento")
        mock_processamento = p2.start()
        mock_processamento.objects.filter.return_value.exists.return_value = False
        self.addCleanup(p2.stop)

    def _disponibilidade(self, *, max_usuario, max_global, count_usuario, count_sistema):
        with patch(
            "apps.core.models.ConfiguracaoGeral.obter",
            return_value=_config(max_usuario, max_global),
        ):
            return calcular_disponibilidade_agente(
                _agente_liberado(),
                MagicMock(name="usuario"),
                execucoes_do_usuario=count_usuario,
                execucoes_no_sistema=count_sistema,
            )

    def test_liberado_quando_abaixo_dos_dois_limites(self):
        disp = self._disponibilidade(
            max_usuario=2, max_global=5, count_usuario=1, count_sistema=3
        )
        self.assertTrue(disp.pode_executar)
        self.assertEqual(disp.estado, "liberado")

    def test_bloqueia_por_limite_de_usuario(self):
        disp = self._disponibilidade(
            max_usuario=2, max_global=5, count_usuario=2, count_sistema=2
        )
        self.assertFalse(disp.pode_executar)
        self.assertIn("Voce ja atingiu o limite", disp.motivo)

    def test_bloqueia_por_limite_global(self):
        disp = self._disponibilidade(
            max_usuario=2, max_global=5, count_usuario=1, count_sistema=5
        )
        self.assertFalse(disp.pode_executar)
        self.assertIn("sistema ja tem muitos agentes", disp.motivo)

    def test_limite_de_usuario_tem_prioridade_sobre_o_global(self):
        # Ambos atingidos: a mensagem exibida deve ser a do usuario (V142-2).
        disp = self._disponibilidade(
            max_usuario=2, max_global=5, count_usuario=2, count_sistema=5
        )
        self.assertFalse(disp.pode_executar)
        self.assertIn("Voce ja atingiu o limite", disp.motivo)

    def test_zero_no_limite_de_usuario_desabilita_o_check(self):
        disp = self._disponibilidade(
            max_usuario=0, max_global=5, count_usuario=99, count_sistema=1
        )
        self.assertTrue(disp.pode_executar)

    def test_zero_no_limite_global_desabilita_o_check(self):
        disp = self._disponibilidade(
            max_usuario=2, max_global=0, count_usuario=1, count_sistema=99
        )
        self.assertTrue(disp.pode_executar)
