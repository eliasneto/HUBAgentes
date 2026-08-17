"""
Testes de `selectors._tokens_por_documento` — quebra do total de tokens do
processamento por documento, usada no painel "Ver tokens por documento" da
tela de Processamentos.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from apps.processamentos.models import (
    AIExecutionStatus,
    DocumentoEntrada,
    DocumentStatus,
    ExecutionScopeType,
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
