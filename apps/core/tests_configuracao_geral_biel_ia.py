"""
Tela Administrador > Configurações Gerais — campos novos pra IA no
assistente Biel (ConfiguracaoGeral.biel_ia_ativa/biel_ai_provider_integration/
biel_ia_modelo). Ver apps/doc_system/tests_biel_ia.py para o comportamento
do chat em si; aqui só a tela de configuração (salvar/carregar os campos e
o filtro de integrações ativas no dropdown).
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.core.models import ConfiguracaoGeral
from apps.integracoes.models import AIProviderIntegration, IntegrationStatus


class ConfiguracaoGeralBielIATests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-config-geral", password="x", email="a@a.com"
        )
        self.client.force_login(self.admin)
        self.integracao_ativa = AIProviderIntegration.objects.create(
            nome="Integracao Ativa",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-padrao",
        )
        self.integracao_inativa = AIProviderIntegration.objects.create(
            nome="Integracao Inativa",
            api_key="chave-teste-2",
            status=IntegrationStatus.INATIVA,
            default_model="modelo-padrao-2",
        )

    def test_pagina_so_lista_integracoes_ativas_no_dropdown(self):
        resp = self.client.get(reverse("portal_configuracao_geral"))

        self.assertEqual(resp.status_code, 200)
        integracoes = list(resp.context["ai_integrations"])
        self.assertIn(self.integracao_ativa, integracoes)
        self.assertNotIn(self.integracao_inativa, integracoes)

    def test_salvar_liga_ia_com_integracao_e_modelo(self):
        self.client.post(
            reverse("portal_configuracao_geral_salvar"),
            data={
                "visibilidade_dashboard": "administrador",
                "dias_retencao_arquivos": "30",
                "max_execucoes_simultaneas": "5",
                "max_execucoes_por_usuario": "2",
                "max_pdfs_lote_subpastas": "25",
                "intervalo_entre_documentos_ia_segundos": "2",
                "biel_ia_ativa": "1",
                "biel_ai_provider_integration": str(self.integracao_ativa.id),
                "biel_ia_modelo": "gpt-4o-mini",
            },
        )

        config = ConfiguracaoGeral.obter()
        self.assertTrue(config.biel_ia_ativa)
        self.assertEqual(config.biel_ai_provider_integration_id, self.integracao_ativa.id)
        self.assertEqual(config.biel_ia_modelo, "gpt-4o-mini")

    def test_salvar_sem_marcar_toggle_desliga_ia(self):
        config = ConfiguracaoGeral.obter()
        config.biel_ia_ativa = True
        config.biel_ai_provider_integration = self.integracao_ativa
        config.save()

        self.client.post(
            reverse("portal_configuracao_geral_salvar"),
            data={
                "visibilidade_dashboard": "administrador",
                "dias_retencao_arquivos": "30",
                "max_execucoes_simultaneas": "5",
                "max_execucoes_por_usuario": "2",
                "max_pdfs_lote_subpastas": "25",
                "intervalo_entre_documentos_ia_segundos": "2",
                # biel_ia_ativa ausente == checkbox desmarcado
                "biel_ai_provider_integration": str(self.integracao_ativa.id),
            },
        )

        config.refresh_from_db()
        self.assertFalse(config.biel_ia_ativa)

    def test_salvar_integracao_inativa_ou_inexistente_nao_associa_nenhuma(self):
        self.client.post(
            reverse("portal_configuracao_geral_salvar"),
            data={
                "visibilidade_dashboard": "administrador",
                "dias_retencao_arquivos": "30",
                "max_execucoes_simultaneas": "5",
                "max_execucoes_por_usuario": "2",
                "max_pdfs_lote_subpastas": "25",
                "intervalo_entre_documentos_ia_segundos": "2",
                "biel_ia_ativa": "1",
                "biel_ai_provider_integration": str(self.integracao_inativa.id),
            },
        )

        config = ConfiguracaoGeral.obter()
        self.assertTrue(config.biel_ia_ativa)
        self.assertIsNone(config.biel_ai_provider_integration)

    def test_salvar_sem_escolher_integracao_mantem_ia_ligada_sem_integracao(self):
        self.client.post(
            reverse("portal_configuracao_geral_salvar"),
            data={
                "visibilidade_dashboard": "administrador",
                "dias_retencao_arquivos": "30",
                "max_execucoes_simultaneas": "5",
                "max_execucoes_por_usuario": "2",
                "max_pdfs_lote_subpastas": "25",
                "intervalo_entre_documentos_ia_segundos": "2",
                "biel_ia_ativa": "1",
                "biel_ai_provider_integration": "",
            },
        )

        config = ConfiguracaoGeral.obter()
        self.assertTrue(config.biel_ia_ativa)
        self.assertIsNone(config.biel_ai_provider_integration)


class ZerarUsoBielViewTests(TestCase):
    """Botão "Zerar contador" na mesma tela — zera os acumuladores de
    tokens/custo do Biel (ver UsoDaIADoBielAcumuladoresTests em
    apps/doc_system/tests_biel_ia.py para quem os popula)."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-zerar-biel", password="x", email="a@a.com"
        )
        self.client.force_login(self.admin)
        config = ConfiguracaoGeral.obter()
        config.biel_tokens_input_total = 1000
        config.biel_tokens_output_total = 500
        config.biel_custo_usd_total = Decimal("3.5")
        config.biel_custo_brl_total = Decimal("17.5")
        config.save()

    def test_zerar_reseta_todos_os_acumuladores_e_marca_a_data(self):
        resp = self.client.post(reverse("portal_configuracao_geral_biel_zerar_uso"))

        self.assertRedirects(resp, reverse("portal_configuracao_geral"))
        config = ConfiguracaoGeral.obter()
        self.assertEqual(config.biel_tokens_input_total, 0)
        self.assertEqual(config.biel_tokens_output_total, 0)
        self.assertEqual(config.biel_custo_usd_total, Decimal("0"))
        self.assertEqual(config.biel_custo_brl_total, Decimal("0"))
        self.assertIsNotNone(config.biel_uso_zerado_em)

    def test_exige_administrador(self):
        self.client.logout()
        usuario_comum = User.objects.create_user(username="comum-zerar-biel", password="x")
        self.client.force_login(usuario_comum)

        resp = self.client.post(reverse("portal_configuracao_geral_biel_zerar_uso"))

        self.assertEqual(resp.status_code, 403)
        config = ConfiguracaoGeral.obter()
        self.assertEqual(config.biel_tokens_input_total, 1000)
