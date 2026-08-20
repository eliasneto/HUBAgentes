"""
Testes de `selectors._tokens_por_documento` — quebra do total de tokens do
processamento por documento, usada no painel "Ver tokens por documento" da
tela de Processamentos.
"""

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from apps.processamentos.models import (
    AIExecutionStatus,
    DocumentoEntrada,
    DocumentoSaidaProcessamento,
    DocumentStatus,
    ExecutionScopeType,
    OutputDocumentStatus,
    Processamento,
    ProcessamentoExecucaoIA,
    ProcessingInputSourceType,
)
from apps.processamentos.selectors import _tokens_por_documento


class TokensPorDocumentoTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="operador", password="x")
        self.processamento = Processamento.objects.create(
            codigo="PROC-TESTE-0001",
            iniciado_por=self.user,
        )

    def _documento(self, nome, **extra):
        defaults = {
            "processamento": self.processamento,
            "nome_arquivo": nome,
            "drive_file_id": "drive-id-" + nome,
            "source_type": ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
            "source_reference": "drive-id-" + nome,
        }
        defaults.update(extra)
        return DocumentoEntrada.objects.create(**defaults)

    def test_soma_tokens_de_todas_as_tentativas_do_mesmo_documento(self):
        documento = self._documento("relatorio.pdf")
        ProcessamentoExecucaoIA.objects.create(
            processamento=self.processamento,
            documento=documento,
            tentativa_numero=1,
            status=AIExecutionStatus.ERRO,
            scope_type=ExecutionScopeType.INDIVIDUAL,
            total_tokens=100,
        )
        execucao_ok = ProcessamentoExecucaoIA.objects.create(
            processamento=self.processamento,
            documento=documento,
            tentativa_numero=2,
            status=AIExecutionStatus.SUCESSO,
            scope_type=ExecutionScopeType.INDIVIDUAL,
            total_tokens=50,
        )
        execucao_ok.documentos_entrada.set([documento])

        linhas = _tokens_por_documento(self.processamento)

        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0].nome_arquivo, "relatorio.pdf")
        self.assertEqual(linhas[0].total_tokens, 150)

    def test_documento_sem_execucao_nao_aparece(self):
        self._documento("ainda_pendente.pdf")

        linhas = _tokens_por_documento(self.processamento)

        self.assertEqual(linhas, [])

    def test_grupo_gera_uma_linha_com_nomes_juntos(self):
        doc_c = self._documento("c.pdf")
        doc_d = self._documento("d.pdf")
        execucao_grupo = ProcessamentoExecucaoIA.objects.create(
            processamento=self.processamento,
            tentativa_numero=1,
            status=AIExecutionStatus.SUCESSO,
            scope_type=ExecutionScopeType.GRUPO,
            total_tokens=300,
        )
        execucao_grupo.documentos_entrada.set([doc_c, doc_d])

        linhas = _tokens_por_documento(self.processamento)

        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0].nome_arquivo, "Grupo: c.pdf, d.pdf")
        self.assertEqual(linhas[0].total_tokens, 300)

    def test_documento_com_erro_final_mostra_mensagem(self):
        documento = self._documento(
            "edital_com_erro.pdf",
            status=DocumentStatus.ERRO,
            mensagem_erro="A resposta da IA nao veio em JSON valido para este processamento.",
        )
        ProcessamentoExecucaoIA.objects.create(
            processamento=self.processamento,
            documento=documento,
            tentativa_numero=1,
            status=AIExecutionStatus.ERRO,
            scope_type=ExecutionScopeType.INDIVIDUAL,
            total_tokens=80,
        )

        linhas = _tokens_por_documento(self.processamento)

        self.assertEqual(len(linhas), 1)
        self.assertEqual(
            linhas[0].mensagem_erro,
            "A resposta da IA nao veio em JSON valido para este processamento.",
        )

    def test_documento_que_deu_certo_na_retentativa_nao_mostra_mensagem_antiga(self):
        # Falhou na 1a tentativa, mas a retentativa automatica de fim de lote
        # deu certo (ver agent_execution._execute_documents_individually) —
        # o status final e PROCESSADO e a mensagem de erro antiga foi limpa,
        # entao o resumo nao deve exibir mensagem nenhuma.
        documento = self._documento(
            "relatorio_recuperado.pdf",
            status=DocumentStatus.PROCESSADO,
            mensagem_erro="",
        )
        ProcessamentoExecucaoIA.objects.create(
            processamento=self.processamento,
            documento=documento,
            tentativa_numero=1,
            status=AIExecutionStatus.ERRO,
            scope_type=ExecutionScopeType.INDIVIDUAL,
            total_tokens=100,
        )
        execucao_ok = ProcessamentoExecucaoIA.objects.create(
            processamento=self.processamento,
            documento=documento,
            tentativa_numero=2,
            status=AIExecutionStatus.SUCESSO,
            scope_type=ExecutionScopeType.INDIVIDUAL,
            total_tokens=50,
        )
        execucao_ok.documentos_entrada.set([documento])

        linhas = _tokens_por_documento(self.processamento)

        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0].mensagem_erro, "")
        self.assertEqual(linhas[0].total_tokens, 150)

    def test_documentos_individuais_ordenados_por_nome(self):
        doc_b = self._documento("b.pdf")
        doc_a = self._documento("a.pdf")
        for documento, tokens in ((doc_b, 20), (doc_a, 10)):
            execucao = ProcessamentoExecucaoIA.objects.create(
                processamento=self.processamento,
                documento=documento,
                tentativa_numero=1,
                status=AIExecutionStatus.SUCESSO,
                scope_type=ExecutionScopeType.INDIVIDUAL,
                total_tokens=tokens,
            )
            execucao.documentos_entrada.set([documento])

        linhas = _tokens_por_documento(self.processamento)

        self.assertEqual([linha.nome_arquivo for linha in linhas], ["a.pdf", "b.pdf"])


class DownloadUrlPorDocumentoTests(TestCase):
    """download_url deixa baixar o arquivo de UM documento individual assim
    que ele termina, sem esperar o processamento inteiro (que pode ter
    dezenas de outros documentos ainda rodando)."""

    def setUp(self):
        self.user = User.objects.create_user(username="operador2", password="x")
        self.processamento = Processamento.objects.create(
            codigo="PROC-TESTE-DOWNLOAD",
            iniciado_por=self.user,
        )

    def _documento(self, nome, **extra):
        defaults = {
            "processamento": self.processamento,
            "nome_arquivo": nome,
            "drive_file_id": "drive-id-" + nome,
            "source_type": ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
            "source_reference": "drive-id-" + nome,
        }
        defaults.update(extra)
        return DocumentoEntrada.objects.create(**defaults)

    def test_documento_processado_com_saida_ganha_download_url(self):
        documento = self._documento("relatorio.pdf", status=DocumentStatus.PROCESSADO)
        execucao = ProcessamentoExecucaoIA.objects.create(
            processamento=self.processamento,
            documento=documento,
            tentativa_numero=1,
            status=AIExecutionStatus.SUCESSO,
            scope_type=ExecutionScopeType.INDIVIDUAL,
            total_tokens=50,
        )
        execucao.documentos_entrada.set([documento])
        saida = DocumentoSaidaProcessamento(
            processamento=self.processamento,
            documento=documento,
            execucao_ia=execucao,
            status=OutputDocumentStatus.GERADO,
        )
        saida.arquivo.save("relatorio.json", ContentFile(b'{"ok": true}'), save=False)
        saida.save()

        linhas = _tokens_por_documento(self.processamento)

        self.assertEqual(len(linhas), 1)
        self.assertEqual(
            linhas[0].download_url,
            reverse(
                "portal_processamento_download_documento",
                kwargs={"codigo": self.processamento.codigo, "saida_id": saida.id},
            ),
        )

    def test_documento_com_erro_nao_tem_download_url(self):
        documento = self._documento(
            "com_erro.pdf",
            status=DocumentStatus.ERRO,
            mensagem_erro="falhou",
        )
        ProcessamentoExecucaoIA.objects.create(
            processamento=self.processamento,
            documento=documento,
            tentativa_numero=1,
            status=AIExecutionStatus.ERRO,
            scope_type=ExecutionScopeType.INDIVIDUAL,
            total_tokens=10,
        )

        linhas = _tokens_por_documento(self.processamento)

        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0].download_url, "")

    def test_documento_processado_sem_saida_ainda_nao_tem_download_url(self):
        # Estado transitorio possivel entre marcar PROCESSADO e persistir a
        # saida (mesma transacao no codigo real, mas o seletor nao deve
        # quebrar se checado nesse meio-tempo).
        documento = self._documento("sem_saida.pdf", status=DocumentStatus.PROCESSADO)
        execucao = ProcessamentoExecucaoIA.objects.create(
            processamento=self.processamento,
            documento=documento,
            tentativa_numero=1,
            status=AIExecutionStatus.SUCESSO,
            scope_type=ExecutionScopeType.INDIVIDUAL,
            total_tokens=10,
        )
        execucao.documentos_entrada.set([documento])

        linhas = _tokens_por_documento(self.processamento)

        self.assertEqual(linhas[0].download_url, "")

    def test_grupo_nunca_tem_download_url(self):
        doc_c = self._documento("c.pdf")
        doc_d = self._documento("d.pdf")
        execucao_grupo = ProcessamentoExecucaoIA.objects.create(
            processamento=self.processamento,
            tentativa_numero=1,
            status=AIExecutionStatus.SUCESSO,
            scope_type=ExecutionScopeType.GRUPO,
            total_tokens=300,
        )
        execucao_grupo.documentos_entrada.set([doc_c, doc_d])

        linhas = _tokens_por_documento(self.processamento)

        self.assertEqual(linhas[0].download_url, "")


class ProcessamentoDocumentoDownloadViewTests(TestCase):
    def setUp(self):
        self.dono = User.objects.create_user(username="dono", password="x")
        self.outro_usuario = User.objects.create_user(username="outro", password="x")
        self.admin = User.objects.create_user(
            username="admin_teste", password="x", is_superuser=True
        )
        self.processamento = Processamento.objects.create(
            codigo="PROC-TESTE-DOWNLOAD-VIEW",
            iniciado_por=self.dono,
        )
        self.documento = DocumentoEntrada.objects.create(
            processamento=self.processamento,
            nome_arquivo="relatorio.pdf",
            drive_file_id="drive-id",
            source_type=ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
            source_reference="drive-id",
            status=DocumentStatus.PROCESSADO,
        )
        self.saida = DocumentoSaidaProcessamento(
            processamento=self.processamento,
            documento=self.documento,
            status=OutputDocumentStatus.GERADO,
        )
        self.saida.arquivo.save(
            "relatorio.json", ContentFile(b'{"ok": true}'), save=False
        )
        self.saida.save()

    def _url(self):
        return reverse(
            "portal_processamento_download_documento",
            kwargs={"codigo": self.processamento.codigo, "saida_id": self.saida.id},
        )

    def test_dono_consegue_baixar(self):
        self.client.force_login(self.dono)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)

    def test_admin_consegue_baixar_de_qualquer_usuario(self):
        self.client.force_login(self.admin)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)

    def test_outro_usuario_nao_consegue_baixar(self):
        self.client.force_login(self.outro_usuario)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 404)

    def test_sem_login_redireciona(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 302)

    def test_saida_sem_arquivo_devolve_404(self):
        self.saida.arquivo.delete(save=False)
        self.saida.arquivo = None
        self.saida.save()
        self.client.force_login(self.dono)

        resp = self.client.get(self._url())

        self.assertEqual(resp.status_code, 404)
