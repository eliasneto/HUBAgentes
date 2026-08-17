"""
Testes do descarte (soft-delete) de Processamento quando nenhum documento
chegou a ser selecionado para processamento (pasta vazia ou 100% ja
processada antes por este agente) — ver
`ProcessamentoExecutionError.sem_trabalho` e
`operational_execution._finalizar_processamento_sem_trabalho`.

O objetivo e nao "sujar" a tela de Processamentos do Portal com execucoes
onde nenhuma chamada de IA aconteceu, mantendo o registro no banco (visivel
via `Processamento.all_objects`, inclusive no Django Admin) para auditoria.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from apps.processamentos.models import Processamento, ProcessingStatus
from apps.processamentos.services.agent_execution import ProcessamentoExecutionError
from apps.processamentos.services.operational_execution import (
    _finalizar_processamento_sem_trabalho,
)


class ProcessamentoExecutionErrorSemTrabalhoTests(TestCase):

    def test_default_sem_trabalho_e_false(self):
        exc = ProcessamentoExecutionError("qualquer erro")
        self.assertFalse(exc.sem_trabalho)

    def test_sem_trabalho_pode_ser_marcado(self):
        exc = ProcessamentoExecutionError("nada pendente", sem_trabalho=True)
        self.assertTrue(exc.sem_trabalho)


class FinalizarProcessamentoSemTrabalhoTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username="operador", password="x")
        self.processamento = Processamento.objects.create(
            codigo="PROC-SEMTRABALHO-0001",
            iniciado_por=self.user,
        )

    def test_registra_status_e_mensagem_para_auditoria(self):
        _finalizar_processamento_sem_trabalho(
            self.processamento,
            "Todos os arquivos desta pasta ja foram processados anteriormente por este agente.",
            "detalhe tecnico",
        )
        self.processamento.refresh_from_db()
        self.assertEqual(self.processamento.status, ProcessingStatus.CONCLUIDO_ATENCAO)
        self.assertIn("ja foram processados", self.processamento.mensagem_erro)
        self.assertEqual(self.processamento.mensagem_erro_tecnico, "detalhe tecnico")
        self.assertIsNotNone(self.processamento.finalizado_em)

    def test_faz_soft_delete_sumindo_do_manager_padrao(self):
        _finalizar_processamento_sem_trabalho(self.processamento, "Nenhum PDF pendente.")

        self.assertFalse(
            Processamento.objects.filter(pk=self.processamento.pk).exists()
        )

    def test_continua_visivel_via_all_objects_para_auditoria(self):
        _finalizar_processamento_sem_trabalho(self.processamento, "Nenhum PDF pendente.")

        registro = Processamento.all_objects.get(pk=self.processamento.pk)
        self.assertIsNotNone(registro.deleted_at)
        self.assertEqual(registro.status, ProcessingStatus.CONCLUIDO_ATENCAO)
