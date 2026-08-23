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
    # Modelo generico usado quando o teste nao quer exercitar a checagem de
    # compatibilidade em si (ver ModeloIncompativelTests abaixo) — qualquer
    # modelo fora de MODELOS_SEM_SUPORTE_A_REDUCAO_DE_THINKING serve.
    MODELO_COMPATIVEL = "gemini-2.5-flash"

    def test_toggle_desligado_nao_inclui_thinking_budget(self):
        processamento = _processamento(enable_thinking_budget_reduction=False)
        params = _build_execution_params(processamento, model_name=self.MODELO_COMPATIVEL)
        self.assertNotIn("thinking_budget", params)

    def test_toggle_ligado_inclui_thinking_budget_zero(self):
        processamento = _processamento(enable_thinking_budget_reduction=True)
        params = _build_execution_params(processamento, model_name=self.MODELO_COMPATIVEL)
        self.assertEqual(params["thinking_budget"], 0)

    def test_sem_configuracao_operacional_nao_quebra_e_nao_inclui(self):
        processamento = MagicMock()
        processamento.output_format = ProcessingOutputFormat.JSON
        processamento.agente.parametros_execucao = {}
        processamento.agente.configuracao_operacional = None
        params = _build_execution_params(processamento, model_name=self.MODELO_COMPATIVEL)
        self.assertNotIn("thinking_budget", params)

    def test_nao_sobrescreve_thinking_budget_ja_definido_manualmente(self):
        # Se o agente ja define thinking_budget em parametros_execucao
        # (ajuste fino manual), o toggle nao deve pisar em cima.
        processamento = _processamento(
            enable_thinking_budget_reduction=True,
            parametros_execucao={"thinking_budget": 2048},
        )
        params = _build_execution_params(processamento, model_name=self.MODELO_COMPATIVEL)
        self.assertEqual(params["thinking_budget"], 2048)

    def test_funciona_tambem_para_formato_livre(self):
        # LIVRE pula o setdefault de response_mime_type, mas o toggle de
        # thinking budget e independente do formato de saida.
        processamento = _processamento(
            enable_thinking_budget_reduction=True,
            output_format=ProcessingOutputFormat.LIVRE,
        )
        params = _build_execution_params(processamento, model_name=self.MODELO_COMPATIVEL)
        self.assertEqual(params["thinking_budget"], 0)
        self.assertNotIn("response_mime_type", params)


class ModeloIncompativelComReducaoDeThinkingTests(SimpleTestCase):
    """gemini-2.5-pro rejeita thinkingBudget=0 (HTTP 400 "Budget 0 is
    invalid..."). Antes dessa checagem, TODO documento processado por um
    agente com o toggle ligado nesse modelo pagava uma chamada HTTP inteira
    desperdicada (a que falha) antes da retentativa que de fato funciona —
    caso real: agente JHS/Licitacao, 21/08/2026, lote de 6 documentos
    esbarrou no timeout de 600s do servidor por causa dessa lentidao
    extra, processando so 5. Ver gemini_adapter.
    suporta_reducao_de_thinking_budget."""

    def test_modelo_incompativel_nao_inclui_thinking_budget_mesmo_com_toggle_ligado(self):
        processamento = _processamento(enable_thinking_budget_reduction=True)
        params = _build_execution_params(processamento, model_name="gemini-2.5-pro")
        self.assertNotIn("thinking_budget", params)

    def test_modelo_incompativel_e_case_insensitive(self):
        processamento = _processamento(enable_thinking_budget_reduction=True)
        params = _build_execution_params(processamento, model_name="Gemini-2.5-Pro")
        self.assertNotIn("thinking_budget", params)

    def test_modelo_incompativel_com_prefixo_models_tambem_e_reconhecido(self):
        processamento = _processamento(enable_thinking_budget_reduction=True)
        params = _build_execution_params(processamento, model_name="models/gemini-2.5-pro")
        self.assertNotIn("thinking_budget", params)

    def test_modelo_compativel_gemini_flash_inclui_thinking_budget(self):
        processamento = _processamento(enable_thinking_budget_reduction=True)
        params = _build_execution_params(processamento, model_name="gemini-2.5-flash")
        self.assertEqual(params["thinking_budget"], 0)

    def test_outro_provedor_nao_relacionado_ao_gemini_inclui_thinking_budget(self):
        # A checagem e so sobre o NOME do modelo — adapters que nao sao
        # Gemini ja ignoram thinking_budget silenciosamente (ver
        # docstring de _build_execution_params), entao nao ha necessidade
        # de checar o provedor aqui.
        processamento = _processamento(enable_thinking_budget_reduction=True)
        params = _build_execution_params(processamento, model_name="gpt-4o")
        self.assertEqual(params["thinking_budget"], 0)

    def test_modelo_vazio_nao_quebra_e_inclui_thinking_budget(self):
        processamento = _processamento(enable_thinking_budget_reduction=True)
        params = _build_execution_params(processamento, model_name="")
        self.assertEqual(params["thinking_budget"], 0)
