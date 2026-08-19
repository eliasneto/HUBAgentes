"""
Testes da leitura recursiva de subpastas (AgenteConfiguracaoOperacional.
include_subfolders): listagem recursiva local e no Google Drive (com
paginacao), derivacao de pasta_grupo a partir do caminho relativo, corte de
lote (ConfiguracaoGeral.max_pdfs_lote_subpastas) e retomada entre execucoes
sem reprocessar nem perder arquivos.
"""

import re
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from apps.agentes_ia.models import (
    AgenteConfiguracaoOperacional,
    AgenteIA,
    AgentDefaultInputSourceType,
    AgentDocumentExecutionMode,
    AgentStatus,
    AgentType,
)
from apps.core.models import ConfiguracaoGeral
from apps.integracoes.models import (
    AIProviderIntegration,
    IntegrationStatus,
    LocalStorageIntegration,
)
from apps.integracoes.services.google_drive import (
    GOOGLE_DRIVE_FOLDER_MIME,
    PDF_MIME,
    list_pdf_files_recursive_from_drive_folder_id,
)
from apps.integracoes.services.local_storage import list_pdf_files_from_relative_folder
from apps.processamentos.models import (
    DocumentoEntrada,
    DocumentStatus,
    Processamento,
    ProcessingInputSourceType,
)
from apps.processamentos.services.document_sources import (
    _pasta_mae_do_caminho,
    _LimiteLoteTracker,
    prepare_documentos,
)


# ---------------------------------------------------------------------------
# _pasta_mae_do_caminho
# ---------------------------------------------------------------------------

class PastaMaeDoCaminhoTests(SimpleTestCase):

    def test_arquivo_na_raiz_nao_tem_pasta_mae(self):
        self.assertEqual(_pasta_mae_do_caminho("edital.pdf"), "")

    def test_arquivo_em_1_nivel(self):
        self.assertEqual(_pasta_mae_do_caminho("janeiro/edital.pdf"), "janeiro")

    def test_arquivo_em_varios_niveis(self):
        self.assertEqual(
            _pasta_mae_do_caminho("2024/janeiro/contratos/edital.pdf"),
            "2024/janeiro/contratos",
        )


# ---------------------------------------------------------------------------
# _LimiteLoteTracker
# ---------------------------------------------------------------------------

class LimiteLoteTrackerTests(SimpleTestCase):

    def test_sem_limite_sempre_permite(self):
        tracker = _LimiteLoteTracker(None)
        for _ in range(50):
            self.assertTrue(tracker.pode_criar_mais())
            tracker.registrar_criado()
        self.assertFalse(tracker.atingiu_limite)

    def test_para_ao_atingir_limite(self):
        tracker = _LimiteLoteTracker(2)
        self.assertTrue(tracker.pode_criar_mais())
        tracker.registrar_criado()
        self.assertTrue(tracker.pode_criar_mais())
        tracker.registrar_criado()
        self.assertFalse(tracker.pode_criar_mais())
        self.assertTrue(tracker.atingiu_limite)

    def test_limite_zero_nao_cria_nenhum(self):
        tracker = _LimiteLoteTracker(0)
        self.assertFalse(tracker.pode_criar_mais())
        self.assertTrue(tracker.atingiu_limite)


# ---------------------------------------------------------------------------
# Listagem recursiva local (force_recursive)
# ---------------------------------------------------------------------------

class ListagemRecursivaLocalTests(SimpleTestCase):

    def _make_integration(self, base_path, recursive_scan=False):
        integration = MagicMock()
        integration.base_path = str(base_path)
        integration.recursive_scan = recursive_scan
        integration.allowed_extensions = ["pdf"]
        return integration

    def _montar_arvore(self, base: Path):
        (base / "raiz.pdf").write_bytes(b"pdf")
        nivel1 = base / "2024"
        nivel1.mkdir()
        (nivel1 / "resumo.pdf").write_bytes(b"pdf")
        nivel2 = nivel1 / "janeiro"
        nivel2.mkdir()
        (nivel2 / "edital.pdf").write_bytes(b"pdf")
        nivel3 = nivel2 / "contratos"
        nivel3.mkdir()
        (nivel3 / "contrato.pdf").write_bytes(b"pdf")

    def test_force_recursive_encontra_arquivos_em_qualquer_profundidade(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._montar_arvore(base)
            integration = self._make_integration(base, recursive_scan=False)

            arquivos = list_pdf_files_from_relative_folder(
                integration, "", force_recursive=True
            )

        nomes = {f["name"] for f in arquivos}
        self.assertEqual(nomes, {"raiz.pdf", "resumo.pdf", "edital.pdf", "contrato.pdf"})

        por_nome = {f["name"]: f["relative_path"] for f in arquivos}
        self.assertEqual(por_nome["contrato.pdf"], "2024/janeiro/contratos/contrato.pdf")
        self.assertEqual(por_nome["edital.pdf"], "2024/janeiro/edital.pdf")

    def test_sem_force_recursive_e_sem_recursive_scan_so_ve_a_raiz(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._montar_arvore(base)
            integration = self._make_integration(base, recursive_scan=False)

            arquivos = list_pdf_files_from_relative_folder(integration, "")

        nomes = {f["name"] for f in arquivos}
        self.assertEqual(nomes, {"raiz.pdf"})

    def test_recursive_scan_da_integracao_continua_funcionando_sem_force(self):
        # force_recursive=False mas a integracao tem recursive_scan=True —
        # comportamento pre-existente nao pode regredir.
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._montar_arvore(base)
            integration = self._make_integration(base, recursive_scan=True)

            arquivos = list_pdf_files_from_relative_folder(integration, "")

        nomes = {f["name"] for f in arquivos}
        self.assertEqual(nomes, {"raiz.pdf", "resumo.pdf", "edital.pdf", "contrato.pdf"})


# ---------------------------------------------------------------------------
# Listagem recursiva do Google Drive (BFS + paginacao)
# ---------------------------------------------------------------------------

class _FakeExecutable:
    def __init__(self, payload):
        self._payload = payload

    def execute(self):
        return self._payload


class _FakeDriveFiles:
    """Simula `service.files()` do SDK do Google, devolvendo paginas
    pre-definidas por pasta (para exercitar o loop de nextPageToken)."""

    _FOLDER_ID_PATTERN = re.compile(r"'([^']+)' in parents")

    def __init__(self, pages_by_folder):
        self._pages_by_folder = pages_by_folder
        self.chamadas = []

    def list(self, q, fields, pageSize, pageToken=None):
        folder_id = self._FOLDER_ID_PATTERN.search(q).group(1)
        self.chamadas.append((folder_id, pageToken))
        pages = self._pages_by_folder[folder_id]
        page_index = 0 if pageToken is None else int(pageToken)
        page = pages[page_index]
        payload = {"files": page}
        if page_index + 1 < len(pages):
            payload["nextPageToken"] = str(page_index + 1)
        return _FakeExecutable(payload)


class _FakeDriveService:
    def __init__(self, files_helper):
        self._files_helper = files_helper

    def files(self):
        return self._files_helper


def _pdf(item_id, name):
    return {"id": item_id, "name": name, "mimeType": PDF_MIME}


def _pasta(item_id, name):
    return {"id": item_id, "name": name, "mimeType": GOOGLE_DRIVE_FOLDER_MIME}


class ListagemRecursivaDriveTests(SimpleTestCase):

    def _patch_service(self, pages_by_folder):
        fake_service = _FakeDriveService(_FakeDriveFiles(pages_by_folder))
        return patch(
            "apps.integracoes.services.google_drive.build_drive_service",
            return_value=fake_service,
        )

    def test_varre_subpastas_em_qualquer_profundidade_com_paginacao(self):
        pages_by_folder = {
            "root": [[_pdf("r1", "raiz.pdf"), _pasta("A", "A")]],
            # 2 paginas na pasta A, para exercitar nextPageToken.
            "A": [[_pdf("a1", "a1.pdf")], [_pasta("B", "B")]],
            "B": [[_pdf("b1", "b1.pdf")]],
        }
        with self._patch_service(pages_by_folder):
            arquivos = list_pdf_files_recursive_from_drive_folder_id(
                MagicMock(), "root"
            )

        por_nome = {f["name"]: f["relative_path"] for f in arquivos}
        self.assertEqual(
            por_nome,
            {
                "raiz.pdf": "raiz.pdf",
                "a1.pdf": "A/a1.pdf",
                "b1.pdf": "A/B/b1.pdf",
            },
        )

    def test_max_files_interrompe_a_varredura_antes_de_esgotar_a_arvore(self):
        pages_by_folder = {
            "root": [[_pdf("r1", "raiz.pdf"), _pasta("A", "A")]],
            "A": [[_pdf("a1", "a1.pdf")]],
        }
        with self._patch_service(pages_by_folder):
            arquivos = list_pdf_files_recursive_from_drive_folder_id(
                MagicMock(), "root", max_files=1
            )

        self.assertEqual(len(arquivos), 1)
        self.assertEqual(arquivos[0]["name"], "raiz.pdf")


# ---------------------------------------------------------------------------
# document_sources.prepare_documentos com include_subfolders=True (local)
# ---------------------------------------------------------------------------

class PrepararDocumentosSubpastasLocalTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="operador", password="x")
        self.ai_integration = AIProviderIntegration.objects.create(
            nome="IA Teste",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-teste",
        )
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.local_integration = LocalStorageIntegration.objects.create(
            nome="Pasta Teste",
            base_path=str(self.base_path),
            status=IntegrationStatus.ATIVA,
            allowed_extensions=["pdf"],
        )

    def tearDown(self):
        ConfiguracaoGeral.objects.all().delete()

    def _criar_agente(self, *, include_subfolders, document_execution_mode=AgentDocumentExecutionMode.INDIVIDUAL):
        agente = AgenteIA.objects.create(
            nome="Agente Teste",
            slug=f"agente-teste-{AgenteIA.objects.count()}",
            tipo=AgentType.GENERICO,
            ai_provider_integration=self.ai_integration,
            status=AgentStatus.ATIVO,
            prompt_base="prompt",
        )
        AgenteConfiguracaoOperacional.objects.create(
            agente=agente,
            default_input_source_type=AgentDefaultInputSourceType.LOCAL_FOLDER,
            default_local_storage_integration=self.local_integration,
            include_subfolders=include_subfolders,
            document_execution_mode=document_execution_mode,
        )
        return agente

    def _criar_processamento(self, agente, *, document_execution_mode=AgentDocumentExecutionMode.INDIVIDUAL):
        return Processamento.objects.create(
            codigo=f"PROC-TESTE-{Processamento.objects.count()}",
            iniciado_por=self.user,
            agente=agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            local_storage_integration=self.local_integration,
            local_relative_input_path="",
            document_execution_mode_snapshot=document_execution_mode,
        )

    def _montar_arvore(self, quantidade_por_pasta=1):
        """Cria N pastas ('p0', 'p1', ...) cada uma com `quantidade_por_pasta`
        PDFs de nome unico, todas abaixo da raiz — nenhum arquivo solto."""
        for i in range(quantidade_por_pasta):
            pasta = self.base_path / f"p{i}"
            pasta.mkdir()
            (pasta / f"doc{i}.pdf").write_bytes(b"pdf")

    def test_sem_include_subfolders_ignora_arquivos_em_subpastas(self):
        agente = self._criar_agente(include_subfolders=False)
        self._montar_arvore(3)
        processamento = self._criar_processamento(agente)

        resultado = prepare_documentos(processamento)

        self.assertEqual(resultado["created"], 0)
        self.assertFalse(resultado.get("atingiu_limite_lote", False))

    def test_com_include_subfolders_encontra_arquivos_em_subpastas(self):
        agente = self._criar_agente(include_subfolders=True)
        self._montar_arvore(3)
        processamento = self._criar_processamento(agente)

        resultado = prepare_documentos(processamento)

        self.assertEqual(resultado["created"], 3)
        self.assertFalse(resultado["atingiu_limite_lote"])
        nomes = set(
            DocumentoEntrada.objects.filter(processamento=processamento).values_list(
                "nome_arquivo", flat=True
            )
        )
        self.assertEqual(nomes, {"doc0.pdf", "doc1.pdf", "doc2.pdf"})

    def test_pasta_grupo_evita_colisao_de_nomes_iguais_em_subpastas_diferentes(self):
        agente = self._criar_agente(include_subfolders=True)
        (self.base_path / "jan").mkdir()
        (self.base_path / "jan" / "relatorio.pdf").write_bytes(b"pdf-jan")
        (self.base_path / "fev").mkdir()
        (self.base_path / "fev" / "relatorio.pdf").write_bytes(b"pdf-fev")
        processamento = self._criar_processamento(agente)

        resultado = prepare_documentos(processamento)

        # Mesmo nome em pastas diferentes: os dois sao criados (nao ha
        # colisao de dedup), diferenciados por pasta_grupo.
        self.assertEqual(resultado["created"], 2)
        grupos = set(
            DocumentoEntrada.objects.filter(processamento=processamento).values_list(
                "pasta_grupo", flat=True
            )
        )
        self.assertEqual(grupos, {"jan", "fev"})

    def test_corte_de_lote_e_continuacao_sem_reprocessar(self):
        agente = self._criar_agente(include_subfolders=True)
        self._montar_arvore(5)
        config_geral = ConfiguracaoGeral.obter()
        config_geral.max_pdfs_lote_subpastas = 2
        config_geral.save()

        processamento_1 = self._criar_processamento(agente)
        resultado_1 = prepare_documentos(processamento_1)

        self.assertEqual(resultado_1["created"], 2)
        self.assertTrue(resultado_1["atingiu_limite_lote"])

        # Simula a execucao de IA tendo processado com sucesso os 2 do lote 1.
        DocumentoEntrada.objects.filter(processamento=processamento_1).update(
            status=DocumentStatus.PROCESSADO
        )

        # Lote 2 ("clique" seguinte, disparado pela continuacao automatica):
        # o limite de 2 continua valendo, entao ainda sobra 1 arquivo.
        processamento_2 = self._criar_processamento(agente)
        resultado_2 = prepare_documentos(processamento_2)

        self.assertEqual(resultado_2["created"], 2)
        self.assertEqual(resultado_2["ignorados"], 2)  # os 2 do lote 1
        self.assertTrue(resultado_2["atingiu_limite_lote"])
        DocumentoEntrada.objects.filter(processamento=processamento_2).update(
            status=DocumentStatus.PROCESSADO
        )

        # Lote 3: esgota o ultimo arquivo restante, sem repetir nenhum.
        processamento_3 = self._criar_processamento(agente)
        resultado_3 = prepare_documentos(processamento_3)

        self.assertEqual(resultado_3["created"], 1)
        self.assertEqual(resultado_3["ignorados"], 4)  # os 4 dos lotes 1 e 2
        self.assertFalse(resultado_3["atingiu_limite_lote"])

        nomes_por_lote = [
            set(
                DocumentoEntrada.objects.filter(processamento=p).values_list(
                    "nome_arquivo", flat=True
                )
            )
            for p in (processamento_1, processamento_2, processamento_3)
        ]
        self.assertEqual(nomes_por_lote[0] & nomes_por_lote[1], set())
        self.assertEqual(nomes_por_lote[1] & nomes_por_lote[2], set())
        self.assertEqual(nomes_por_lote[0] & nomes_por_lote[2], set())
        self.assertEqual(
            nomes_por_lote[0] | nomes_por_lote[1] | nomes_por_lote[2],
            {"doc0.pdf", "doc1.pdf", "doc2.pdf", "doc3.pdf", "doc4.pdf"},
        )

    def test_sem_limite_configurado_processa_tudo_de_uma_vez(self):
        agente = self._criar_agente(include_subfolders=True)
        self._montar_arvore(5)
        config_geral = ConfiguracaoGeral.obter()
        config_geral.max_pdfs_lote_subpastas = 0  # 0 = sem limite
        config_geral.save()

        processamento = self._criar_processamento(agente)
        resultado = prepare_documentos(processamento)

        self.assertEqual(resultado["created"], 5)
        self.assertFalse(resultado["atingiu_limite_lote"])

    def test_modo_lote_por_pasta_ignora_arquivos_soltos_na_raiz(self):
        agente = self._criar_agente(
            include_subfolders=True,
            document_execution_mode=AgentDocumentExecutionMode.LOTE_POR_PASTA,
        )
        (self.base_path / "solto.pdf").write_bytes(b"pdf")
        pasta = self.base_path / "2024" / "janeiro"
        pasta.mkdir(parents=True)
        (pasta / "edital.pdf").write_bytes(b"pdf")
        processamento = self._criar_processamento(
            agente, document_execution_mode=AgentDocumentExecutionMode.LOTE_POR_PASTA
        )

        resultado = prepare_documentos(processamento)

        self.assertEqual(resultado["created"], 1)
        documento = DocumentoEntrada.objects.get(processamento=processamento)
        self.assertEqual(documento.nome_arquivo, "edital.pdf")
        self.assertEqual(documento.pasta_grupo, "2024/janeiro")
