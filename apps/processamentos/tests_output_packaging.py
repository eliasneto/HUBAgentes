"""
Testes de entrada e saída: arquivo único vs ZIP.

Cobre _deve_empacotar_em_zip e publicar_saida_final com todos os cenários
documentados em DATA_CONTRACTS.md.
"""

from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import TestCase

from apps.agentes_ia.models import AgentOutputAssemblyMode, AgentOutputPackagingMode
from apps.processamentos.models import ProcessingOutputFormat
from apps.processamentos.services.output_packaging import (
    OutputPackagingError,
    _deve_empacotar_em_zip,
    publicar_saida_final,
)


def _make_output_record(nome="saida.json", formato=ProcessingOutputFormat.JSON, com_arquivo=True):
    record = MagicMock()
    record.arquivo_nome = nome
    record.formato = formato
    if com_arquivo:
        record.arquivo.name = f"processamentos/PROC-001/saidas/{nome}"
        record.arquivo.open.return_value.__enter__ = lambda s: s
        record.arquivo.open.return_value.__exit__ = MagicMock(return_value=False)
        record.arquivo.open.return_value.read.return_value = b"conteudo_fake"
    else:
        record.arquivo = None
    return record


def _make_processamento(codigo="PROC-001"):
    proc = MagicMock()
    proc.codigo = codigo
    return proc


# ---------------------------------------------------------------------------
# Testes unitários de _deve_empacotar_em_zip (sem banco de dados)
# ---------------------------------------------------------------------------

class DeveEmpacoatarEmZipTests(TestCase):

    # --- SEMPRE_ZIP ---

    def test_sempre_zip_com_um_arquivo(self):
        resultado = _deve_empacotar_em_zip(
            output_records=[_make_output_record()],
            output_packaging_mode=AgentOutputPackagingMode.SEMPRE_ZIP,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
            source_document_count=1,
        )
        self.assertTrue(resultado, "SEMPRE_ZIP deve empacotar mesmo com 1 arquivo")

    def test_sempre_zip_com_varios_arquivos(self):
        records = [_make_output_record(f"saida_{i}.json") for i in range(3)]
        resultado = _deve_empacotar_em_zip(
            output_records=records,
            output_packaging_mode=AgentOutputPackagingMode.SEMPRE_ZIP,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
            source_document_count=3,
        )
        self.assertTrue(resultado, "SEMPRE_ZIP deve empacotar sempre")

    # --- ZIP_SE_MULTIPLOS + UMA_POR_ENTRADA ---

    def test_zip_se_multiplos_uma_por_entrada_com_um_documento(self):
        resultado = _deve_empacotar_em_zip(
            output_records=[_make_output_record()],
            output_packaging_mode=AgentOutputPackagingMode.ZIP_SE_MULTIPLOS,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
            source_document_count=1,
        )
        self.assertFalse(resultado, "ZIP_SE_MULTIPLOS + 1 documento deve retornar arquivo unico")

    def test_zip_se_multiplos_uma_por_entrada_com_varios_documentos(self):
        records = [_make_output_record(f"saida_{i}.json") for i in range(3)]
        resultado = _deve_empacotar_em_zip(
            output_records=records,
            output_packaging_mode=AgentOutputPackagingMode.ZIP_SE_MULTIPLOS,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
            source_document_count=3,
        )
        self.assertTrue(resultado, "ZIP_SE_MULTIPLOS + varios documentos deve empacotar em ZIP")

    def test_zip_se_multiplos_uma_por_entrada_limite_exato_dois(self):
        records = [_make_output_record(f"saida_{i}.json") for i in range(2)]
        resultado = _deve_empacotar_em_zip(
            output_records=records,
            output_packaging_mode=AgentOutputPackagingMode.ZIP_SE_MULTIPLOS,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
            source_document_count=2,
        )
        self.assertTrue(resultado, "ZIP_SE_MULTIPLOS + 2 documentos ja deve empacotar")

    # --- ZIP_SE_MULTIPLOS + UMA_SAIDA_FINAL (usa len(output_records)) ---

    def test_zip_se_multiplos_uma_saida_final_com_um_record(self):
        resultado = _deve_empacotar_em_zip(
            output_records=[_make_output_record()],
            output_packaging_mode=AgentOutputPackagingMode.ZIP_SE_MULTIPLOS,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_SAIDA_FINAL,
            source_document_count=5,
        )
        self.assertFalse(resultado, "ZIP_SE_MULTIPLOS + 1 output_record deve ser arquivo unico")

    def test_zip_se_multiplos_uma_saida_final_com_varios_records(self):
        records = [_make_output_record(f"saida_{i}.json") for i in range(2)]
        resultado = _deve_empacotar_em_zip(
            output_records=records,
            output_packaging_mode=AgentOutputPackagingMode.ZIP_SE_MULTIPLOS,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_SAIDA_FINAL,
            source_document_count=1,
        )
        self.assertTrue(resultado, "ZIP_SE_MULTIPLOS + varios output_records deve empacotar")

    # --- ARQUIVO_UNICO ---

    def test_arquivo_unico_nunca_empacota(self):
        records = [_make_output_record(f"saida_{i}.json") for i in range(5)]
        resultado = _deve_empacotar_em_zip(
            output_records=records,
            output_packaging_mode=AgentOutputPackagingMode.ARQUIVO_UNICO,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_SAIDA_FINAL,
            source_document_count=5,
        )
        self.assertFalse(resultado, "ARQUIVO_UNICO nunca deve empacotar em ZIP")


# ---------------------------------------------------------------------------
# Testes de publicar_saida_final
# ---------------------------------------------------------------------------

class PublicarSaidaFinalTests(TestCase):

    def test_sem_records_retorna_false(self):
        processamento = _make_processamento()
        resultado = publicar_saida_final(
            processamento=processamento,
            output_records=[],
            output_packaging_mode=AgentOutputPackagingMode.SEMPRE_ZIP,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
            source_document_count=0,
        )
        self.assertFalse(resultado)

    def test_arquivo_unico_copia_referencia_do_record(self):
        processamento = _make_processamento()
        record = _make_output_record(nome="resultado.json", formato=ProcessingOutputFormat.JSON)
        record.arquivo.name = "processamentos/PROC-001/saidas/resultado.json"

        resultado = publicar_saida_final(
            processamento=processamento,
            output_records=[record],
            output_packaging_mode=AgentOutputPackagingMode.ARQUIVO_UNICO,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_SAIDA_FINAL,
            source_document_count=1,
        )

        self.assertTrue(resultado)
        self.assertEqual(processamento.arquivo_saida.name, record.arquivo.name)
        self.assertEqual(processamento.arquivo_saida_formato, ProcessingOutputFormat.JSON)

    def test_record_sem_arquivo_levanta_erro(self):
        processamento = _make_processamento()
        record = _make_output_record(com_arquivo=False)

        with self.assertRaises(OutputPackagingError):
            publicar_saida_final(
                processamento=processamento,
                output_records=[record],
                output_packaging_mode=AgentOutputPackagingMode.ARQUIVO_UNICO,
                output_assembly_mode=AgentOutputAssemblyMode.UMA_SAIDA_FINAL,
                source_document_count=1,
            )

    @patch("apps.processamentos.services.output_packaging._render_zip")
    def test_sempre_zip_chama_render_zip(self, mock_render_zip):
        mock_render_zip.return_value = ("resultado.zip", b"zipbytes")
        processamento = _make_processamento()
        record = _make_output_record()

        resultado = publicar_saida_final(
            processamento=processamento,
            output_records=[record],
            output_packaging_mode=AgentOutputPackagingMode.SEMPRE_ZIP,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
            source_document_count=1,
        )

        self.assertTrue(resultado)
        mock_render_zip.assert_called_once()
        self.assertEqual(processamento.arquivo_saida_formato, ProcessingOutputFormat.ZIP)
        self.assertEqual(processamento.arquivo_saida_nome, "resultado.zip")

    @patch("apps.processamentos.services.output_packaging._render_zip")
    def test_zip_se_multiplos_com_varios_documentos_empacota(self, mock_render_zip):
        mock_render_zip.return_value = ("resultado.zip", b"zipbytes")
        processamento = _make_processamento()
        records = [_make_output_record(f"saida_{i}.json") for i in range(3)]

        resultado = publicar_saida_final(
            processamento=processamento,
            output_records=records,
            output_packaging_mode=AgentOutputPackagingMode.ZIP_SE_MULTIPLOS,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
            source_document_count=3,
        )

        self.assertTrue(resultado)
        mock_render_zip.assert_called_once()
        self.assertEqual(processamento.arquivo_saida_formato, ProcessingOutputFormat.ZIP)

    def test_zip_se_multiplos_com_um_documento_nao_empacota(self):
        processamento = _make_processamento()
        record = _make_output_record(nome="unico.json", formato=ProcessingOutputFormat.JSON)
        record.arquivo.name = "processamentos/PROC-001/saidas/unico.json"

        resultado = publicar_saida_final(
            processamento=processamento,
            output_records=[record],
            output_packaging_mode=AgentOutputPackagingMode.ZIP_SE_MULTIPLOS,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
            source_document_count=1,
        )

        self.assertTrue(resultado)
        self.assertEqual(processamento.arquivo_saida_formato, ProcessingOutputFormat.JSON)
        self.assertNotEqual(processamento.arquivo_saida_nome, ProcessingOutputFormat.ZIP)
