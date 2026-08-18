"""
Testes de GeminiProviderAdapter._build_generation_config para o parametro
thinking_budget (ver AgenteConfiguracaoOperacional.enable_thinking_budget_reduction
e apps/processamentos/services/agent_execution.py::_build_execution_params).
"""

from django.test import SimpleTestCase

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
