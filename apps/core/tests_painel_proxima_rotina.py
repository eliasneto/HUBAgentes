"""
Tela inicial do portal (menu_inicial.html / PortalPainelView) — horario da
proxima rotina automatica de agentes exibido no topo (canto superior
direito da topbar), pra qualquer usuario logado saber quando os documentos
pendentes serao verificados de novo, sem precisar entrar em Administrador >
Rotina automatica.

So aparece com o interruptor geral ligado (rotina_automatica_agentes_ativa):
com o interruptor desligado, ConfiguracaoGeral.rotina_automatica_proxima_
execucao_em pode estar desatualizado (executar_rotinas_automaticas_agentes
nao toca esse campo enquanto desligado — ver operational_execution.py) e
mostrar esse valor pareceria uma rodada real que nao vai acontecer.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.models import ConfiguracaoGeral


class PainelProximaRotinaAutomaticaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="usuario-painel", password="x")
        self.client.force_login(self.user)
        self.config = ConfiguracaoGeral.obter()

    def test_mostra_proxima_execucao_quando_interruptor_ligado(self):
        proxima = timezone.now() + timedelta(minutes=42)
        self.config.rotina_automatica_agentes_ativa = True
        self.config.rotina_automatica_proxima_execucao_em = proxima
        self.config.save(
            update_fields=[
                "rotina_automatica_agentes_ativa",
                "rotina_automatica_proxima_execucao_em",
            ]
        )

        resp = self.client.get(reverse("portal_painel"))

        self.assertEqual(resp.context["proxima_rotina_automatica_em"], proxima)
        self.assertContains(resp, "Próxima rotina automática")

    def test_nao_mostra_nada_com_interruptor_geral_desligado(self):
        # Mesmo com um valor antigo (potencialmente desatualizado) no campo.
        self.config.rotina_automatica_agentes_ativa = False
        self.config.rotina_automatica_proxima_execucao_em = timezone.now() + timedelta(
            minutes=10
        )
        self.config.save(
            update_fields=[
                "rotina_automatica_agentes_ativa",
                "rotina_automatica_proxima_execucao_em",
            ]
        )

        resp = self.client.get(reverse("portal_painel"))

        self.assertIsNone(resp.context["proxima_rotina_automatica_em"])
        self.assertNotContains(resp, "Próxima rotina automática")

    def test_usa_horario_de_inicio_agendado_quando_ainda_nao_rodou(self):
        inicio_agendado = timezone.now() + timedelta(hours=3)
        self.config.rotina_automatica_agentes_ativa = True
        self.config.rotina_automatica_proxima_execucao_em = None
        self.config.rotina_automatica_inicio_em = inicio_agendado
        self.config.save(
            update_fields=[
                "rotina_automatica_agentes_ativa",
                "rotina_automatica_proxima_execucao_em",
                "rotina_automatica_inicio_em",
            ]
        )

        resp = self.client.get(reverse("portal_painel"))

        self.assertEqual(resp.context["proxima_rotina_automatica_em"], inicio_agendado)

    def test_sem_proxima_execucao_nem_inicio_agendado_nao_mostra_nada(self):
        self.config.rotina_automatica_agentes_ativa = True
        self.config.rotina_automatica_proxima_execucao_em = None
        self.config.rotina_automatica_inicio_em = None
        self.config.save(
            update_fields=[
                "rotina_automatica_agentes_ativa",
                "rotina_automatica_proxima_execucao_em",
                "rotina_automatica_inicio_em",
            ]
        )

        resp = self.client.get(reverse("portal_painel"))

        self.assertIsNone(resp.context["proxima_rotina_automatica_em"])
        self.assertNotContains(resp, "Próxima rotina automática")

    def test_horario_de_inicio_no_passado_e_ignorado(self):
        # Ja passou e o worker ainda nao rodou pra atualizar proxima_execucao
        # (janela curta, mas possivel) — nao mostra um horario ja vencido.
        self.config.rotina_automatica_agentes_ativa = True
        self.config.rotina_automatica_proxima_execucao_em = None
        self.config.rotina_automatica_inicio_em = timezone.now() - timedelta(minutes=5)
        self.config.save(
            update_fields=[
                "rotina_automatica_agentes_ativa",
                "rotina_automatica_proxima_execucao_em",
                "rotina_automatica_inicio_em",
            ]
        )

        resp = self.client.get(reverse("portal_painel"))

        self.assertIsNone(resp.context["proxima_rotina_automatica_em"])
