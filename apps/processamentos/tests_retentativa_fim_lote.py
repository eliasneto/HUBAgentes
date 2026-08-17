"""
Retentativa automatica de fim de lote (modo INDIVIDUAL): documentos que falham
com um erro retryable (vindo da propria IA/provedor — timeout, instabilidade,
resposta truncada ou em JSON invalido) ganham uma segunda tentativa ao final
do lote, em vez de ficarem ERRO na primeira falha. Documentos com erro
nao-retryable (configuracao, credenciais, formato nao suportado) nao entram
nessa segunda passada.

Caso real que motivou a mudanca: PROC-20260817131407-E8C8D2BB — lote de 5
PDFs em modo individual, 4 processados com sucesso e o 5o falhou com
"A resposta da IA nao veio em JSON valido para este processamento". Falha de
conteudo nao-deterministica da IA, nao um problema permanente do documento.
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.integracoes.services.ai_providers import AIProviderServiceError
from apps.processamentos.services.agent_execution import (
    _execute_documents_individually,
    _parse_structured_output,
    ProcessamentoExecutionError,
)


def _proc_com_contagem(quantidade):
    """Processamento simulado cujo execucoes_ia.filter(...).count() devolve
    `quantidade` — controla _documento_excedeu_tentativas sem tocar o banco."""
    proc = MagicMock()
    proc.execucoes_ia.filter.return_value.count.return_value = quantidade
    return proc


def _documento(nome="edital.pdf"):
    doc = MagicMock()
    doc.nome_arquivo = nome
    return doc


class ParseStructuredOutputRetryableTests(SimpleTestCase):
    """A falha vem do conteudo da resposta da IA, nao de configuracao do
    agente/documento — deve ser elegivel a retentativa (ver
    _execute_documents_individually)."""

    def test_json_invalido_e_retryable(self):
        with self.assertRaises(ProcessamentoExecutionError) as ctx:
            _parse_structured_output("isso nao e json { incompleto")
        self.assertTrue(ctx.exception.retryable)

    def test_resposta_vazia_e_retryable(self):
        with self.assertRaises(ProcessamentoExecutionError) as ctx:
            _parse_structured_output("")
        self.assertTrue(ctx.exception.retryable)

    def test_json_valido_nao_levanta_erro(self):
        resultado = _parse_structured_output('{"status": "ok"}')
        self.assertEqual(resultado, {"status": "ok"})


@patch("apps.processamentos.services.agent_execution.obter_ou_criar_configuracao_operacional")
@patch("apps.processamentos.services.agent_execution._log_execution_error")
@patch("apps.processamentos.services.agent_execution._mark_document_error")
@patch("apps.processamentos.services.agent_execution._execute_document")
class RetentativaFimDeLoteTests(SimpleTestCase):

    def _config(self, max_tentativas):
        config = MagicMock()
        config.max_tentativas = max_tentativas
        return config

    def test_erro_retryable_e_reprocessado_com_sucesso_na_segunda_passada(
        self, mock_execute, mock_mark_error, mock_log, mock_config
    ):
        mock_config.return_value = self._config(3)
        mock_execute.side_effect = [
            AIProviderServiceError("indisponivel", retryable=True),
            {"output_record": MagicMock()},
        ]

        proc = _proc_com_contagem(0)
        doc = _documento()

        resultado = _execute_documents_individually(
            processamento=proc,
            documentos=[doc],
            integration=MagicMock(),
            model_name="modelo",
            execution_params={},
            actor=MagicMock(),
        )

        self.assertEqual(mock_execute.call_count, 2)
        self.assertEqual(resultado["total_success"], 1)
        self.assertEqual(resultado["total_errors"], 0)
        self.assertEqual(len(resultado["output_records"]), 1)

    def test_erro_nao_retryable_nao_ganha_segunda_tentativa(
        self, mock_execute, mock_mark_error, mock_log, mock_config
    ):
        mock_config.return_value = self._config(3)
        mock_execute.side_effect = ProcessamentoExecutionError(
            "formato de saida nao suportado"
        )  # retryable=False por padrao

        proc = _proc_com_contagem(0)
        doc = _documento()

        resultado = _execute_documents_individually(
            processamento=proc,
            documentos=[doc],
            integration=MagicMock(),
            model_name="modelo",
            execution_params={},
            actor=MagicMock(),
        )

        # So a 1a passada: erro de configuracao nao repete sozinho.
        self.assertEqual(mock_execute.call_count, 1)
        self.assertEqual(resultado["total_success"], 0)
        self.assertEqual(resultado["total_errors"], 1)

    def test_erro_retryable_que_falha_de_novo_conta_como_erro_final(
        self, mock_execute, mock_mark_error, mock_log, mock_config
    ):
        mock_config.return_value = self._config(3)
        mock_execute.side_effect = [
            AIProviderServiceError("indisponivel", retryable=True),
            AIProviderServiceError("indisponivel de novo", retryable=True),
        ]

        proc = _proc_com_contagem(0)
        doc = _documento()

        resultado = _execute_documents_individually(
            processamento=proc,
            documentos=[doc],
            integration=MagicMock(),
            model_name="modelo",
            execution_params={},
            actor=MagicMock(),
        )

        # Uma unica retentativa automatica: tenta 2x no total, nao mais.
        self.assertEqual(mock_execute.call_count, 2)
        self.assertEqual(resultado["total_success"], 0)
        self.assertEqual(resultado["total_errors"], 1)
        self.assertIn("indisponivel de novo", resultado["last_error_message"])

    def test_erro_retryable_nao_retenta_se_ja_excedeu_max_tentativas(
        self, mock_execute, mock_mark_error, mock_log, mock_config
    ):
        # max_tentativas=1: a checagem antes da 1a tentativa passa (nenhuma
        # execucao registrada ainda), mas apos a falha a tentativa que acabou
        # de rodar ja conta como a unica permitida — nao ganha a retentativa
        # de fim de lote. Patch direto em _documento_excedeu_tentativas para
        # simular a contagem real (que so muda porque _mark_document_error
        # cria um novo registro — aqui mockado, entao nao muda sozinha).
        mock_config.return_value = self._config(1)
        mock_execute.side_effect = AIProviderServiceError(
            "indisponivel", retryable=True
        )

        proc = MagicMock()
        doc = _documento()

        with patch(
            "apps.processamentos.services.agent_execution._documento_excedeu_tentativas",
            side_effect=[False, True],
        ) as mock_excedeu:
            resultado = _execute_documents_individually(
                processamento=proc,
                documentos=[doc],
                integration=MagicMock(),
                model_name="modelo",
                execution_params={},
                actor=MagicMock(),
            )

        self.assertEqual(mock_excedeu.call_count, 2)
        self.assertEqual(mock_execute.call_count, 1)
        self.assertEqual(resultado["total_success"], 0)
        self.assertEqual(resultado["total_errors"], 1)

    def test_um_documento_falha_outro_passa_direto(
        self, mock_execute, mock_mark_error, mock_log, mock_config
    ):
        mock_config.return_value = self._config(3)
        mock_execute.side_effect = [
            {"output_record": MagicMock()},  # doc 1: sucesso de primeira
            AIProviderServiceError("indisponivel", retryable=True),  # doc 2: falha
            {"output_record": MagicMock()},  # doc 2: sucesso na retentativa
        ]

        proc = _proc_com_contagem(0)
        doc1 = _documento("doc1.pdf")
        doc2 = _documento("doc2.pdf")

        resultado = _execute_documents_individually(
            processamento=proc,
            documentos=[doc1, doc2],
            integration=MagicMock(),
            model_name="modelo",
            execution_params={},
            actor=MagicMock(),
        )

        self.assertEqual(mock_execute.call_count, 3)
        self.assertEqual(resultado["total_success"], 2)
        self.assertEqual(resultado["total_errors"], 0)
        self.assertEqual(len(resultado["output_records"]), 2)
