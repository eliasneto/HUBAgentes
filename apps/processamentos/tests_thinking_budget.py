"""
Testes do toggle "Reduzir custo de raciocinio da IA"
(AgenteConfiguracaoOperacional.enable_thinking_budget_reduction).

Cobre o ponto de decisao _build_execution_params, que decide se
`thinking_budget=0` entra nos parametros de execucao repassados ao adapter
de IA. Nao cobre o adapter em si (ver
apps/integracoes/tests_gemini_thinking_budget.py).
"""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from apps.processamentos.models import ProcessingOutputFormat
from apps.processamentos.services.agent_execution import _build_execution_params


def _processamento(*, enable_thinking_budget_reduction, parametros_execucao=None, output_format=ProcessingOutputFormat.JSON):
    processamento = MagicMock()
    processamento.output_format = output_format
    processamento.agente.parametros_execucao = parametros_execucao or {}
    processamento.agente.configuracao_operacional.enable_thinking_budget_reduction = (
        enable_thinking_budget_reduction
    )
    return processamento


class BuildExecutionParamsThinkingBudgetTests(SimpleTestCase):

    def test_toggle_desligado_nao_inclui_thinking_budget(self):
        processamento = _processamento(enable_thinking_budget_reduction=False)
        params = _build_execution_params(processamento)
        self.assertNotIn("thinking_budget", params)

    def test_toggle_ligado_inclui_thinking_budget_zero(self):
        processamento = _processamento(enable_thinking_budget_reduction=True)
        params = _build_execution_params(processamento)
        self.assertEqual(params["thinking_budget"], 0)

    def test_sem_configuracao_operacional_nao_quebra_e_nao_inclui(self):
        processamento = MagicMock()
        processamento.output_format = ProcessingOutputFormat.JSON
        processamento.agente.parametros_execucao = {}
        processamento.agente.configuracao_operacional = None
        params = _build_execution_params(processamento)
        self.assertNotIn("thinking_budget", params)

    def test_nao_sobrescreve_thinking_budget_ja_definido_manualmente(self):
        # Se o agente ja define thinking_budget em parametros_execucao
        # (ajuste fino manual), o toggle nao deve pisar em cima.
        processamento = _processamento(
            enable_thinking_budget_reduction=True,
            parametros_execucao={"thinking_budget": 2048},
        )
        params = _build_execution_params(processamento)
        self.assertEqual(params["thinking_budget"], 2048)

    def test_funciona_tambem_para_formato_livre(self):
        # LIVRE pula o setdefault de response_mime_type, mas o toggle de
        # thinking budget e independente do formato de saida.
        processamento = _processamento(
            enable_thinking_budget_reduction=True,
            output_format=ProcessingOutputFormat.LIVRE,
        )
        params = _build_execution_params(processamento)
        self.assertEqual(params["thinking_budget"], 0)
        self.assertNotIn("response_mime_type", params)
