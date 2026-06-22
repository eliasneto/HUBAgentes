"""
Reprocesso seletivo: só erros transitórios (que se resolvem sozinhos) são
reprocessados automaticamente. Erros que exigem intervenção manual permanecem
em ERRO e não são re-tentados — salvo se o arquivo de origem mudou.
"""

from django.test import SimpleTestCase

from apps.integracoes.services.ai_providers.base import AIProviderServiceError
from apps.processamentos.models import DocumentoEntrada, DocumentStatus
from apps.processamentos.services.agent_execution import ProcessamentoExecutionError
from apps.processamentos.services.document_sources import _update_documento_if_needed


class FlagRetryableExcecoesTests(SimpleTestCase):

    def test_ai_provider_error_padrao_nao_reprocessavel(self):
        self.assertFalse(AIProviderServiceError("falha").retryable)

    def test_ai_provider_error_transitorio(self):
        self.assertTrue(AIProviderServiceError("indisponivel", retryable=True).retryable)

    def test_processamento_error_padrao_nao_reprocessavel(self):
        # JSON inválido / truncado: não se resolve sozinho.
        self.assertFalse(ProcessamentoExecutionError("json invalido").retryable)


class ResetReprocessoSeletivoTests(SimpleTestCase):

    def _doc(self, *, reprocessavel, **extra):
        doc = DocumentoEntrada(
            status=DocumentStatus.ERRO,
            erro_reprocessavel=reprocessavel,
            nome_arquivo="edital.pdf",
            mensagem_erro="falhou",
            **extra,
        )
        doc.save = lambda *a, **k: None  # evita acesso ao banco
        return doc

    def test_erro_transitorio_volta_para_pendente(self):
        doc = self._doc(reprocessavel=True)
        _update_documento_if_needed(doc, {})
        self.assertEqual(doc.status, DocumentStatus.PENDENTE)
        self.assertEqual(doc.mensagem_erro, "")

    def test_erro_permanente_permanece_em_erro(self):
        doc = self._doc(reprocessavel=False)
        _update_documento_if_needed(doc, {})
        self.assertEqual(doc.status, DocumentStatus.ERRO)
        self.assertEqual(doc.mensagem_erro, "falhou")

    def test_erro_permanente_reprocessa_se_arquivo_mudou(self):
        doc = self._doc(reprocessavel=False, checksum="antigo")
        _update_documento_if_needed(doc, {"checksum": "novo"})
        self.assertEqual(doc.status, DocumentStatus.PENDENTE)
