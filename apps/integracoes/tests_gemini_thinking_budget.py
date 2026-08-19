"""
Testes de GeminiProviderAdapter._build_generation_config para o parametro
thinking_budget (ver AgenteConfiguracaoOperacional.enable_thinking_budget_reduction
e apps/processamentos/services/agent_execution.py::_build_execution_params).
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.integracoes.services.ai_providers.base import AIProviderServiceError
from apps.integracoes.services.ai_providers.gemini_adapter import GeminiProviderAdapter


class BuildGenerationConfigThinkingBudgetTests(SimpleTestCase):

    def setUp(self):
        # GeminiProviderAdapter.__init__ so guarda self.integration; os
        # metodos testados aqui nao usam nenhum atributo dela.
        self.adapter = GeminiProviderAdapter(None)

    def test_thinking_budget_zero_vira_thinkingconfig_aninhado(self):
        config = self.adapter._build_generation_config({"thinking_budget": 0})
        self.assertEqual(config["thinkingConfig"], {"thinkingBudget": 0})

    def test_thinking_budget_zero_nao_e_descartado_por_ser_falsy(self):
        # 0 e um valor valido (desabilita o raciocinio) — nao pode cair no
        # mesmo filtro `not in (None, "", [], {})` usado para os demais
        # campos do field_map, que trataria 0 como "ausente".
        config = self.adapter._build_generation_config({"thinking_budget": 0})
        self.assertIn("thinkingConfig", config)

    def test_ausencia_de_thinking_budget_nao_adiciona_thinkingconfig(self):
        config = self.adapter._build_generation_config({"temperature": 0.2})
        self.assertNotIn("thinkingConfig", config)

    def test_thinking_budget_convive_com_outros_parametros(self):
        config = self.adapter._build_generation_config(
            {"thinking_budget": 1024, "response_mime_type": "application/json"}
        )
        self.assertEqual(config["thinkingConfig"], {"thinkingBudget": 1024})
        self.assertEqual(config["responseMimeType"], "application/json")

    def test_execution_params_nao_dict_devolve_config_vazio(self):
        config = self.adapter._build_generation_config(None)
        self.assertEqual(config, {})


class PostJsonThinkingBudgetFallbackTests(SimpleTestCase):
    """gemini-2.5-pro (e outros modelos que "so funcionam em thinking mode")
    rejeitam thinkingBudget=0 com HTTP 400 — ver producao, agente JHS
    (Licitacao), 19/08/2026. O toggle promete nao ter efeito em modelos que
    nao suportam o ajuste (ver help_text de
    AgenteConfiguracaoOperacional.enable_thinking_budget_reduction); estes
    testes cobrem o fallback que faz essa promessa valer de verdade, em vez
    de quebrar a execucao inteira."""

    def setUp(self):
        self.adapter = GeminiProviderAdapter(None)
        self.erro_budget_invalido = AIProviderServiceError(
            'Falha HTTP 400 ao executar o agente no provedor: {\n'
            '  "error": {\n'
            '    "code": 400,\n'
            '    "message": "Budget 0 is invalid. This model only works in thinking mode.",\n'
            '    "status": "INVALID_ARGUMENT"\n'
            '  }\n'
            '}'
        )

    def test_refaz_sem_thinking_config_quando_modelo_nao_aceita_budget_zero(self):
        payload = {
            "contents": [{"parts": [{"text": "oi"}]}],
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
        }
        sucesso = ({"candidates": []}, "https://exemplo/url")
        with patch.object(
            self.adapter,
            "_post_json_request",
            side_effect=[self.erro_budget_invalido, sucesso],
        ) as mock_post:
            resultado = self.adapter._post_json("https://exemplo/url", payload)

        self.assertEqual(resultado, {"candidates": []})
        self.assertEqual(mock_post.call_count, 2)
        # A 2a tentativa nao pode mais conter thinkingConfig.
        segunda_chamada_payload = mock_post.call_args_list[1].args[1]
        self.assertNotIn("thinkingConfig", segunda_chamada_payload["generationConfig"])

    def test_nao_refaz_chamada_para_erro_sem_relacao_com_thinking_budget(self):
        payload = {
            "contents": [{"parts": [{"text": "oi"}]}],
            "generationConfig": {"thinkingConfig": {"thinkingBudget": 0}},
        }
        outro_erro = AIProviderServiceError("Falha HTTP 400 ao executar o agente no provedor: erro qualquer")
        with patch.object(
            self.adapter, "_post_json_request", side_effect=outro_erro
        ) as mock_post:
            with self.assertRaises(AIProviderServiceError):
                self.adapter._post_json("https://exemplo/url", payload)

        self.assertEqual(mock_post.call_count, 1)

    def test_nao_refaz_chamada_quando_payload_nao_tem_thinking_config(self):
        payload = {"contents": [{"parts": [{"text": "oi"}]}]}
        with patch.object(
            self.adapter,
            "_post_json_request",
            side_effect=self.erro_budget_invalido,
        ) as mock_post:
            with self.assertRaises(AIProviderServiceError):
                self.adapter._post_json("https://exemplo/url", payload)

        self.assertEqual(mock_post.call_count, 1)
