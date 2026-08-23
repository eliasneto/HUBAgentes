"""
Biel com acesso a IA — ConfiguracaoGeral.biel_ia_ativa/biel_ai_provider_integration/
biel_ia_modelo (Administrador > Configuracoes Gerais). Regra: palavra-chave
responde primeiro, sem custo, pra tudo que ja esta mapeado em _KNOWLEDGE_BASE;
a IA so entra quando nada bate (score 0) e o toggle esta ligado, respondendo
com base na propria documentacao (grounding) em vez de conhecimento livre —
reduz risco de inventar funcionalidade que nao existe. Qualquer falha (sem
integracao configurada, erro do provedor, excecao inesperada) cai de volta
pro "nao encontrei isso" de sempre, sem expor erro tecnico ao usuario.
"""

import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase

from apps.core.models import ConfiguracaoGeral
from apps.custos.models import ConfiguracaoFinanceira, PrecificacaoModelo
from apps.doc_system.views import _RESPOSTA_PADRAO
from apps.integracoes.models import AIProviderIntegration, IntegrationStatus
from apps.integracoes.services.ai_providers.base import (
    AIProviderExecutionResult,
    AIProviderServiceError,
)


def _resultado_ia(texto, usage_metadata=None):
    return AIProviderExecutionResult(
        output_text=texto,
        response_payload={},
        usage_metadata=usage_metadata or {},
        request_url="",
        response_mime_type="",
        summary="",
    )


class BielChatViewTests(TestCase):
    CHAT_URL = "/biel/chat/"

    def setUp(self):
        self.user = User.objects.create_user(username="usuario-biel", password="x")
        self.client.force_login(self.user)
        self.integracao = AIProviderIntegration.objects.create(
            nome="Integracao Biel",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-padrao",
        )

    def _perguntar(self, mensagem):
        resp = self.client.post(
            self.CHAT_URL,
            data=json.dumps({"mensagem": mensagem}),
            content_type="application/json",
        )
        return resp, json.loads(resp.content)

    def _ligar_ia(self, *, integracao=None, modelo=""):
        config = ConfiguracaoGeral.obter()
        config.biel_ia_ativa = True
        config.biel_ai_provider_integration = integracao
        config.biel_ia_modelo = modelo
        config.save()
        return config

    @patch("apps.integracoes.services.ai_providers.get_ai_provider_adapter")
    def test_palavra_chave_responde_sem_chamar_ia_mesmo_com_ia_ligada(self, mock_get_adapter):
        self._ligar_ia(integracao=self.integracao)

        resp, data = self._perguntar("oi")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Biel", data["resposta"])
        mock_get_adapter.assert_not_called()

    @patch("apps.integracoes.services.ai_providers.get_ai_provider_adapter")
    def test_toggle_desligado_nunca_chama_ia(self, mock_get_adapter):
        config = ConfiguracaoGeral.obter()
        config.biel_ia_ativa = False
        config.biel_ai_provider_integration = self.integracao
        config.save()

        resp, data = self._perguntar("pergunta sem nenhuma palavra-chave mapeada aqui")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["resposta"], _RESPOSTA_PADRAO["resposta"])
        mock_get_adapter.assert_not_called()

    @patch("apps.integracoes.services.ai_providers.get_ai_provider_adapter")
    def test_toggle_ligado_sem_integracao_escolhida_nao_quebra(self, mock_get_adapter):
        self._ligar_ia(integracao=None)

        resp, data = self._perguntar("pergunta sem nenhuma palavra-chave mapeada aqui")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["resposta"], _RESPOSTA_PADRAO["resposta"])
        mock_get_adapter.assert_not_called()

    @patch("apps.integracoes.services.ai_providers.get_ai_provider_adapter")
    def test_score_zero_com_ia_ligada_chama_adapter_e_usa_modelo_padrao_da_integracao(
        self, mock_get_adapter
    ):
        self._ligar_ia(integracao=self.integracao)
        mock_adapter = MagicMock()
        mock_adapter.execute_prompt_without_document.return_value = _resultado_ia(
            "Resposta gerada pela IA com base na documentacao."
        )
        mock_get_adapter.return_value = mock_adapter

        resp, data = self._perguntar("pergunta sem nenhuma palavra-chave mapeada aqui")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["resposta"], "Resposta gerada pela IA com base na documentacao.")
        self.assertIsNone(data["link"])
        mock_get_adapter.assert_called_once_with(self.integracao)
        kwargs = mock_adapter.execute_prompt_without_document.call_args.kwargs
        self.assertEqual(kwargs["model_name"], "modelo-padrao")
        self.assertIn("pergunta sem nenhuma palavra-chave", kwargs["prompt"])

    @patch("apps.integracoes.services.ai_providers.get_ai_provider_adapter")
    def test_modelo_customizado_sobrescreve_o_padrao_da_integracao(self, mock_get_adapter):
        self._ligar_ia(integracao=self.integracao, modelo="modelo-escolhido")
        mock_adapter = MagicMock()
        mock_adapter.execute_prompt_without_document.return_value = _resultado_ia("ok")
        mock_get_adapter.return_value = mock_adapter

        self._perguntar("pergunta sem nenhuma palavra-chave mapeada aqui")

        kwargs = mock_adapter.execute_prompt_without_document.call_args.kwargs
        self.assertEqual(kwargs["model_name"], "modelo-escolhido")

    @patch("apps.integracoes.services.ai_providers.get_ai_provider_adapter")
    def test_erro_do_provedor_cai_no_fallback_sem_expor_erro_tecnico(self, mock_get_adapter):
        self._ligar_ia(integracao=self.integracao)
        mock_adapter = MagicMock()
        mock_adapter.execute_prompt_without_document.side_effect = AIProviderServiceError(
            "Falha HTTP 401 ao executar o agente no provedor"
        )
        mock_get_adapter.return_value = mock_adapter

        resp, data = self._perguntar("pergunta sem nenhuma palavra-chave mapeada aqui")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["resposta"], _RESPOSTA_PADRAO["resposta"])

    @patch("apps.integracoes.services.ai_providers.get_ai_provider_adapter")
    def test_excecao_inesperada_cai_no_fallback(self, mock_get_adapter):
        self._ligar_ia(integracao=self.integracao)
        mock_get_adapter.side_effect = RuntimeError("boom")

        resp, data = self._perguntar("pergunta sem nenhuma palavra-chave mapeada aqui")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["resposta"], _RESPOSTA_PADRAO["resposta"])

    def test_endpoint_exige_login(self):
        self.client.logout()

        resp = self.client.post(
            self.CHAT_URL,
            data=json.dumps({"mensagem": "oi"}),
            content_type="application/json",
        )

        self.assertNotEqual(resp.status_code, 200)


class UsoDaIADoBielAcumuladoresTests(TestCase):
    """ConfiguracaoGeral.biel_tokens_*/biel_custo_*_total — acumuladores
    exibidos em Administrador > Configurações Gerais, pra dar visibilidade
    do custo do Biel no dia a dia (ver apps.doc_system.views.
    _acumular_uso_biel)."""

    CHAT_URL = "/biel/chat/"

    def setUp(self):
        self.user = User.objects.create_user(username="usuario-uso-biel", password="x")
        self.client.force_login(self.user)
        self.integracao = AIProviderIntegration.objects.create(
            nome="Integracao Uso Biel",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-padrao",
        )
        config = ConfiguracaoGeral.obter()
        config.biel_ia_ativa = True
        config.biel_ai_provider_integration = self.integracao
        config.save()

    def _perguntar(self):
        return self.client.post(
            self.CHAT_URL,
            data=json.dumps({"mensagem": "pergunta sem nenhuma palavra-chave mapeada aqui"}),
            content_type="application/json",
        )

    @patch("apps.integracoes.services.ai_providers.get_ai_provider_adapter")
    def test_acumula_tokens_mesmo_sem_precificacao_cadastrada(self, mock_get_adapter):
        mock_adapter = MagicMock()
        mock_adapter.execute_prompt_without_document.return_value = _resultado_ia(
            "ok",
            usage_metadata={
                "promptTokenCount": 100,
                "candidatesTokenCount": 40,
                "totalTokenCount": 140,
            },
        )
        mock_get_adapter.return_value = mock_adapter

        self._perguntar()

        config = ConfiguracaoGeral.obter()
        self.assertEqual(config.biel_tokens_input_total, 100)
        self.assertEqual(config.biel_tokens_output_total, 40)
        # Sem PrecificacaoModelo/ConfiguracaoFinanceira cadastradas, custo
        # fica zerado — os tokens continuam contando normalmente.
        self.assertEqual(config.biel_custo_usd_total, Decimal("0"))
        self.assertEqual(config.biel_custo_brl_total, Decimal("0"))

    @patch("apps.integracoes.services.ai_providers.get_ai_provider_adapter")
    def test_acumula_custo_quando_ha_precificacao_e_cotacao(self, mock_get_adapter):
        PrecificacaoModelo.objects.create(
            nome_modelo="modelo-padrao",
            preco_input_por_milhao=Decimal("1"),
            preco_output_por_milhao=Decimal("2"),
            ativo=True,
        )
        ConfiguracaoFinanceira.objects.create(cotacao_dolar=Decimal("5"))
        mock_adapter = MagicMock()
        mock_adapter.execute_prompt_without_document.return_value = _resultado_ia(
            "ok",
            usage_metadata={
                "promptTokenCount": 1_000_000,
                "candidatesTokenCount": 1_000_000,
                "totalTokenCount": 2_000_000,
            },
        )
        mock_get_adapter.return_value = mock_adapter

        self._perguntar()

        config = ConfiguracaoGeral.obter()
        # 1M de entrada a US$1/milhao + 1M de saida a US$2/milhao = US$3.
        self.assertEqual(config.biel_custo_usd_total, Decimal("3.000000"))
        self.assertEqual(config.biel_custo_brl_total, Decimal("15.0000"))

    @patch("apps.integracoes.services.ai_providers.get_ai_provider_adapter")
    def test_acumula_em_chamadas_sucessivas_sem_sobrescrever(self, mock_get_adapter):
        mock_adapter = MagicMock()
        mock_adapter.execute_prompt_without_document.return_value = _resultado_ia(
            "ok",
            usage_metadata={
                "promptTokenCount": 10,
                "candidatesTokenCount": 5,
                "totalTokenCount": 15,
            },
        )
        mock_get_adapter.return_value = mock_adapter

        self._perguntar()
        self._perguntar()

        config = ConfiguracaoGeral.obter()
        self.assertEqual(config.biel_tokens_input_total, 20)
        self.assertEqual(config.biel_tokens_output_total, 10)

    @patch("apps.integracoes.services.ai_providers.get_ai_provider_adapter")
    def test_erro_do_provedor_nao_acumula_nada(self, mock_get_adapter):
        mock_adapter = MagicMock()
        mock_adapter.execute_prompt_without_document.side_effect = AIProviderServiceError(
            "Falha HTTP 401 ao executar o agente no provedor"
        )
        mock_get_adapter.return_value = mock_adapter

        self._perguntar()

        config = ConfiguracaoGeral.obter()
        self.assertEqual(config.biel_tokens_input_total, 0)
        self.assertEqual(config.biel_tokens_output_total, 0)
