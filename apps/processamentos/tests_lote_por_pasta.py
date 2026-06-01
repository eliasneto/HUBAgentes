"""
Testes para o modo LOTE_POR_PASTA:
- listagem de subpastas no local_storage
- agrupamento por pasta_grupo no agent_execution
- _usa_execucao_por_pasta detecta o modo correto
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.agentes_ia.models import (
    AgentDocumentExecutionMode,
    AgentOutputAssemblyMode,
)
from apps.integracoes.services.local_storage import (
    list_subfolders_from_relative_folder,
    list_pdf_files_from_subfolder,
)
from apps.processamentos.services.agent_execution import (
    _usa_execucao_individual,
    _usa_execucao_por_pasta,
)


def _make_processamento(execution_mode, assembly_mode):
    proc = MagicMock()
    proc.document_execution_mode_snapshot = execution_mode
    proc.output_assembly_mode_snapshot = assembly_mode
    return proc


# ---------------------------------------------------------------------------
# Testes de _usa_execucao_por_pasta e _usa_execucao_individual
# ---------------------------------------------------------------------------

class ModoExecucaoTests(TestCase):

    def test_lote_por_pasta_com_saida_final_usa_por_pasta(self):
        proc = _make_processamento(
            AgentDocumentExecutionMode.LOTE_POR_PASTA,
            AgentOutputAssemblyMode.UMA_SAIDA_FINAL,
        )
        self.assertTrue(_usa_execucao_por_pasta(proc))
        self.assertFalse(_usa_execucao_individual(proc))

    def test_lote_por_pasta_com_uma_por_entrada_nao_usa_por_pasta(self):
        proc = _make_processamento(
            AgentDocumentExecutionMode.LOTE_POR_PASTA,
            AgentOutputAssemblyMode.UMA_POR_ENTRADA,
        )
        self.assertFalse(_usa_execucao_por_pasta(proc))
        # UMA_POR_ENTRADA força individual
        self.assertTrue(_usa_execucao_individual(proc))

    def test_grupo_unico_nao_usa_por_pasta(self):
        proc = _make_processamento(
            AgentDocumentExecutionMode.GRUPO_UNICO,
            AgentOutputAssemblyMode.UMA_SAIDA_FINAL,
        )
        self.assertFalse(_usa_execucao_por_pasta(proc))
        self.assertFalse(_usa_execucao_individual(proc))

    def test_individual_nao_usa_por_pasta(self):
        proc = _make_processamento(
            AgentDocumentExecutionMode.INDIVIDUAL,
            AgentOutputAssemblyMode.UMA_POR_ENTRADA,
        )
        self.assertFalse(_usa_execucao_por_pasta(proc))
        self.assertTrue(_usa_execucao_individual(proc))


# ---------------------------------------------------------------------------
# Testes de listagem de subpastas no local_storage
# ---------------------------------------------------------------------------

class ListarSubpastasTests(TestCase):

    def _make_integration(self, base_path, recursive=False):
        integration = MagicMock()
        integration.base_path = str(base_path)
        integration.recursive_scan = recursive
        return integration

    def test_lista_subpastas_corretamente(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "janeiro").mkdir()
            (base / "fevereiro").mkdir()
            (base / "arquivo.pdf").touch()

            integration = self._make_integration(base)
            subpastas = list_subfolders_from_relative_folder(integration, "")
            nomes = [p.name for p in subpastas]

        self.assertIn("janeiro", nomes)
        self.assertIn("fevereiro", nomes)
        self.assertNotIn("arquivo.pdf", nomes)

    def test_sem_subpastas_retorna_lista_vazia(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "edital.pdf").touch()

            integration = self._make_integration(base)
            subpastas = list_subfolders_from_relative_folder(integration, "")

        self.assertEqual(subpastas, [])

    def test_lista_pdfs_de_subpasta(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            jan = base / "janeiro"
            jan.mkdir()
            (jan / "edital.pdf").write_bytes(b"pdf")
            (jan / "contrato.pdf").write_bytes(b"pdf")
            (jan / "readme.txt").write_bytes(b"txt")

            integration = self._make_integration(base)
            arquivos = list_pdf_files_from_subfolder(integration, "", jan)
            nomes = [f["name"] for f in arquivos]

        self.assertIn("edital.pdf", nomes)
        self.assertIn("contrato.pdf", nomes)
        self.assertNotIn("readme.txt", nomes)

    def test_pdfs_de_subpasta_tem_pasta_grupo_correto(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            jan = base / "janeiro"
            jan.mkdir()
            (jan / "edital.pdf").write_bytes(b"pdf")

            integration = self._make_integration(base)
            arquivos = list_pdf_files_from_subfolder(integration, "", jan)

        self.assertEqual(len(arquivos), 1)
        relative = arquivos[0]["relative_path"]
        self.assertTrue(relative.startswith("janeiro/"))


# ---------------------------------------------------------------------------
# Testes de agrupamento por pasta_grupo no _execute_documents_by_folder
# ---------------------------------------------------------------------------

class AgrupamentoPorPastaTests(TestCase):

    def _make_documento(self, pasta_grupo, nome="edital.pdf"):
        doc = MagicMock()
        doc.pasta_grupo = pasta_grupo
        doc.nome_arquivo = nome
        doc.status = "pendente"
        return doc

    @patch("apps.processamentos.services.agent_execution._execute_document_group")
    @patch("apps.processamentos.services.agent_execution._mark_document_group_error")
    @patch("apps.processamentos.services.agent_execution._log_group_execution_error")
    def test_documentos_agrupados_por_pasta(self, mock_log, mock_mark, mock_group):
        from apps.processamentos.services.agent_execution import _execute_documents_by_folder

        mock_group.return_value = {"output_record": MagicMock()}

        proc = MagicMock()
        docs = [
            self._make_documento("janeiro", "jan_edital.pdf"),
            self._make_documento("janeiro", "jan_contrato.pdf"),
            self._make_documento("fevereiro", "fev_edital.pdf"),
        ]

        resultado = _execute_documents_by_folder(
            processamento=proc,
            documentos=docs,
            integration=MagicMock(),
            model_name="modelo",
            execution_params={},
            actor=MagicMock(),
        )

        # Deve chamar _execute_document_group 2x: uma para janeiro, uma para fevereiro
        self.assertEqual(mock_group.call_count, 2)
        self.assertEqual(len(resultado["output_records"]), 2)
        self.assertEqual(resultado["total_success"], 3)
        self.assertEqual(resultado["total_errors"], 0)

    @patch("apps.processamentos.services.agent_execution._execute_document_group")
    @patch("apps.processamentos.services.agent_execution._mark_document_group_error")
    @patch("apps.processamentos.services.agent_execution._log_group_execution_error")
    def test_erro_em_uma_pasta_nao_para_as_outras(self, mock_log, mock_mark, mock_group):
        from apps.processamentos.services.agent_execution import _execute_documents_by_folder
        from apps.integracoes.services.ai_providers import AIProviderServiceError

        mock_group.side_effect = [
            AIProviderServiceError("erro na IA"),
            {"output_record": MagicMock()},
        ]

        proc = MagicMock()
        docs = [
            self._make_documento("janeiro", "jan_edital.pdf"),
            self._make_documento("fevereiro", "fev_edital.pdf"),
        ]

        resultado = _execute_documents_by_folder(
            processamento=proc,
            documentos=docs,
            integration=MagicMock(),
            model_name="modelo",
            execution_params={},
            actor=MagicMock(),
        )

        self.assertEqual(mock_group.call_count, 2)
        self.assertEqual(len(resultado["output_records"]), 1)
        self.assertEqual(resultado["total_errors"], 1)
        self.assertEqual(resultado["total_success"], 1)

    @patch("apps.processamentos.services.agent_execution._execute_document_group")
    def test_sem_documentos_retorna_vazio(self, mock_group):
        from apps.processamentos.services.agent_execution import _execute_documents_by_folder

        resultado = _execute_documents_by_folder(
            processamento=MagicMock(),
            documentos=[],
            integration=MagicMock(),
            model_name="modelo",
            execution_params={},
            actor=MagicMock(),
        )

        mock_group.assert_not_called()
        self.assertEqual(resultado["output_records"], [])
        self.assertEqual(resultado["total_success"], 0)
