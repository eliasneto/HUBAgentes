"""
ADR-001 Fase 4 (v2.0.0) — reexecutar o MESMO Processamento (regra 2) e
trava permanente apos 2 falhas (regra 3).

Processamento CONCLUIDO_ERRO ganha um botao "Executar" nele mesmo (nao cria
um Processamento novo). So existe 1 reexecucao possivel: se ela tambem
terminar em CONCLUIDO_ERRO, `bloqueado_permanentemente` vira True e o botao
some para sempre — o arquivo pode rodar de novo, mas so criando um
Processamento NOVO (Executar no agente). CONCLUIDO_SUCESSO e
CONCLUIDO_ATENCAO contam como "concluido" (decisao do usuario, 29/08/2026):
nao ganham botao, e terminar em CONCLUIDO_ATENCAO na reexecucao NAO trava
permanentemente (o status ja esconde o botao sozinho).
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.agentes_ia.models import (
    AgenteConfiguracaoOperacional,
    AgenteIA,
    AgentDefaultInputSourceType,
    AgentInputPolicy,
    AgentStatus,
    AgentType,
)
from apps.auditoria.models import EventoAuditoria
from apps.core.models import ConfiguracaoGeral
from apps.integracoes.models import AIProviderIntegration, IntegrationStatus
from apps.processamentos.models import (
    DocumentoEntrada,
    DocumentStatus,
    Processamento,
    ProcessingInputSourceType,
    ProcessingStatus,
)
from apps.processamentos.services.document_sources import DocumentSourcePreparationError
from apps.processamentos.services.operational_execution import (
    OperationalExecutionError,
    _tentar_adquirir_trava_execucao,
    _tentar_adquirir_trava_rotina_automatica_global,
    reexecutar_processamento_existente,
)


def _criar_agente(*, sufixo, criado_por):
    integracao = AIProviderIntegration.objects.create(
        nome=f"Integracao Reexec {sufixo}",
        api_key="chave-teste",
        status=IntegrationStatus.ATIVA,
        default_model="modelo-teste",
    )
    agente = AgenteIA.objects.create(
        nome=f"Agente Reexec {sufixo}",
        slug=f"agente-reexec-{sufixo}",
        tipo=AgentType.GENERICO,
        ai_provider_integration=integracao,
        status=AgentStatus.ATIVO,
        prompt_base="prompt de teste",
        created_by=criado_por,
    )
    configuracao = AgenteConfiguracaoOperacional.objects.create(
        agente=agente,
        input_policy=AgentInputPolicy.SEM_ENTRADA,
        default_input_source_type=AgentDefaultInputSourceType.NONE,
    )
    return agente, configuracao


@patch("apps.processamentos.services.operational_execution.execute_processing")
class ReexecutarProcessamentoExistenteTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono-reexec", password="x")
        self.agente, self.configuracao = _criar_agente(sufixo="1", criado_por=self.user)

    def _processamento(self, *, status, bloqueado_permanentemente=False, sufixo="1"):
        return Processamento.objects.create(
            codigo=f"PROC-REEXEC-{sufixo}",
            iniciado_por=self.user,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            status=status,
            bloqueado_permanentemente=bloqueado_permanentemente,
        )

    def test_rejeita_reexecutar_concluido_sucesso(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_SUCESSO)

        with self.assertRaises(OperationalExecutionError):
            reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        mock_execute.assert_not_called()

    def test_rejeita_reexecutar_concluido_atencao(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ATENCAO)

        with self.assertRaises(OperationalExecutionError):
            reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        mock_execute.assert_not_called()

    def test_rejeita_reexecutar_ja_bloqueado_permanentemente(self, mock_execute):
        processamento = self._processamento(
            status=ProcessingStatus.CONCLUIDO_ERRO, bloqueado_permanentemente=True
        )

        with self.assertRaises(OperationalExecutionError) as ctx:
            reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        self.assertIn("nao pode mais ser executado", str(ctx.exception).lower())
        mock_execute.assert_not_called()

    def test_reset_documentos_em_erro_para_pendente_antes_de_executar(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)
        doc = DocumentoEntrada.objects.create(
            processamento=processamento,
            nome_arquivo="falha.pdf",
            source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            source_reference="falha.pdf",
            status=DocumentStatus.ERRO,
            mensagem_erro="erro antigo",
        )

        reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentStatus.PENDENTE)
        self.assertEqual(doc.mensagem_erro, "")

    def test_sucesso_na_reexecucao_nao_bloqueia(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)

        def _marcar_sucesso(proc, actor, **kwargs):
            proc.status = ProcessingStatus.CONCLUIDO_SUCESSO
            proc.save(update_fields=["status"])

        mock_execute.side_effect = _marcar_sucesso

        resultado = reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        self.assertEqual(resultado.status, ProcessingStatus.CONCLUIDO_SUCESSO)
        self.assertFalse(resultado.bloqueado_permanentemente)

    def test_erro_na_reexecucao_bloqueia_permanentemente(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)
        mock_execute.side_effect = DocumentSourcePreparationError("Falha real de novo")

        with self.assertRaises(OperationalExecutionError):
            reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        processamento.refresh_from_db()
        self.assertEqual(processamento.status, ProcessingStatus.CONCLUIDO_ERRO)
        self.assertTrue(processamento.bloqueado_permanentemente)
        self.assertTrue(
            EventoAuditoria.objects.filter(
                processamento=processamento,
                acao="processamento_bloqueado_permanentemente",
            ).exists()
        )

    def test_atencao_na_reexecucao_nao_bloqueia_permanentemente(self, mock_execute):
        # concluido_atencao ja conta como "concluido" (decisao do usuario) —
        # o status sozinho ja esconde o botao "Executar", sem precisar
        # travar permanentemente.
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)
        mock_execute.side_effect = DocumentSourcePreparationError("Nenhum PDF pendente")

        with self.assertRaises(OperationalExecutionError):
            reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        processamento.refresh_from_db()
        self.assertEqual(processamento.status, ProcessingStatus.CONCLUIDO_ATENCAO)
        self.assertFalse(processamento.bloqueado_permanentemente)

    def test_sem_trabalho_na_reexecucao_nao_faz_soft_delete(self, mock_execute):
        # Reexecutar um Processamento que ja existe nunca deve faze-lo
        # desaparecer da tela do usuario (ver permitir_sem_trabalho=False).
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)
        erro = DocumentSourcePreparationError("Sem documentos elegiveis")
        erro.sem_trabalho = True
        mock_execute.side_effect = erro

        with self.assertRaises(OperationalExecutionError) as ctx:
            reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        self.assertFalse(getattr(ctx.exception, "sem_trabalho", False))
        # Ainda existe (nao foi soft-deleted) e travou permanentemente, como
        # qualquer outro erro de reexecucao.
        processamento_ainda_existe = Processamento.objects.filter(pk=processamento.pk).exists()
        self.assertTrue(processamento_ainda_existe)
        processamento.refresh_from_db()
        self.assertTrue(processamento.bloqueado_permanentemente)

    def test_gera_evento_de_reexecucao_iniciada(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)

        reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        self.assertTrue(
            EventoAuditoria.objects.filter(
                processamento=processamento, acao="reexecucao_manual_iniciada"
            ).exists()
        )

    def test_respeita_trava_por_agente(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)
        _tentar_adquirir_trava_execucao(self.configuracao)

        with self.assertRaises(OperationalExecutionError):
            reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        mock_execute.assert_not_called()

    def test_respeita_trava_global_da_rotina_automatica(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)
        ConfiguracaoGeral.objects.all().delete()
        config = ConfiguracaoGeral.obter()
        _tentar_adquirir_trava_rotina_automatica_global(config)

        with self.assertRaises(OperationalExecutionError):
            reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        mock_execute.assert_not_called()

    def test_agente_removido_nao_pode_reexecutar(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)
        Processamento.objects.filter(pk=processamento.pk).update(agente=None)
        processamento.refresh_from_db()

        with self.assertRaises(OperationalExecutionError):
            reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        mock_execute.assert_not_called()


class ProcessamentoReexecutarViewTests(TestCase):
    def setUp(self):
        self.dono = User.objects.create_user(username="dono-reexec-view", password="x")
        self.outro_usuario = User.objects.create_user(username="outro-reexec-view", password="x")
        self.agente, _ = _criar_agente(sufixo="view", criado_por=self.dono)

    def _processamento(self, *, status, bloqueado_permanentemente=False):
        return Processamento.objects.create(
            codigo="PROC-REEXEC-VIEW-1",
            iniciado_por=self.dono,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            status=status,
            bloqueado_permanentemente=bloqueado_permanentemente,
        )

    @patch("apps.processamentos.services.operational_execution.execute_processing")
    def test_dono_reexecuta_com_sucesso(self, mock_execute):
        def _marcar_sucesso(proc, actor, **kwargs):
            proc.status = ProcessingStatus.CONCLUIDO_SUCESSO
            proc.save(update_fields=["status"])

        mock_execute.side_effect = _marcar_sucesso
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)
        self.client.force_login(self.dono)

        resp = self.client.post(
            reverse("portal_processamento_executar", kwargs={"codigo": processamento.codigo}),
            follow=True,
        )

        self.assertRedirects(resp, reverse("portal_processamentos"))
        processamento.refresh_from_db()
        self.assertEqual(processamento.status, ProcessingStatus.CONCLUIDO_SUCESSO)

    def test_outro_usuario_nao_admin_recebe_404(self):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)
        self.client.force_login(self.outro_usuario)

        resp = self.client.post(
            reverse("portal_processamento_executar", kwargs={"codigo": processamento.codigo})
        )

        self.assertEqual(resp.status_code, 404)

    def test_bloqueado_permanentemente_mostra_mensagem_de_erro(self):
        processamento = self._processamento(
            status=ProcessingStatus.CONCLUIDO_ERRO, bloqueado_permanentemente=True
        )
        self.client.force_login(self.dono)

        resp = self.client.post(
            reverse("portal_processamento_executar", kwargs={"codigo": processamento.codigo}),
            follow=True,
        )

        mensagens = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("nao pode mais ser executado" in m.lower() for m in mensagens))
