"""
ADR-001 Fase 5b (v2.0.0, regra 1) — end-to-end via AgenteExecucaoView: um
agente em modo Individual (document_execution_mode=INDIVIDUAL ou
output_assembly_mode=UMA_POR_ENTRADA) cria 1 Processamento por arquivo num
unico clique em "Executar", e redireciona pra tela de Processamentos ja
filtrada pelos codigos criados (UX decidida com o usuario em 29/08/2026).
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse

from apps.agentes_ia.models import (
    AgenteConfiguracaoOperacional,
    AgenteIA,
    AgentDefaultInputSourceType,
    AgentDocumentExecutionMode,
    AgentInputPolicy,
    AgentOutputAssemblyMode,
    AgentStatus,
    AgentTriggerMode,
    AgentType,
    AgentVisibility,
)
from apps.integracoes.models import AIProviderIntegration, IntegrationStatus, LocalStorageIntegration
from apps.processamentos.models import (
    DocumentoSaidaProcessamento,
    DocumentStatus,
    ExecutionScopeType,
    OutputDocumentStatus,
    Processamento,
    ProcessingStatus,
)


def _fake_execute_document_sucesso(*, processamento, documento, **kwargs):
    output_record = DocumentoSaidaProcessamento(
        processamento=processamento,
        documento=documento,
        status=OutputDocumentStatus.GERADO,
        scope_type=ExecutionScopeType.INDIVIDUAL,
    )
    output_record.arquivo.save(
        f"{documento.nome_arquivo}.json", ContentFile(b'{"ok": true}'), save=False
    )
    output_record.save()
    documento.status = DocumentStatus.PROCESSADO
    documento.save(update_fields=["status"])
    return {"output_record": output_record}


class ExecucaoIndividualPorArquivoViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono-view-individual", password="x")
        self.client.force_login(self.user)
        self.ai_integration = AIProviderIntegration.objects.create(
            nome="Integracao View Individual",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-teste",
        )
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.local_integration = LocalStorageIntegration.objects.create(
            nome="Pasta View Individual",
            base_path=str(self.base_path),
            status=IntegrationStatus.ATIVA,
            allowed_extensions=["pdf"],
        )
        self.agente = AgenteIA.objects.create(
            nome="Agente View Individual",
            slug="agente-view-individual",
            tipo=AgentType.GENERICO,
            ai_provider_integration=self.ai_integration,
            status=AgentStatus.ATIVO,
            visibilidade=AgentVisibility.USUARIO,
            modo_acionamento=AgentTriggerMode.PORTAL,
            prompt_base="prompt",
            created_by=self.user,
        )
        AgenteConfiguracaoOperacional.objects.create(
            agente=self.agente,
            input_policy=AgentInputPolicy.FIXA,
            default_input_source_type=AgentDefaultInputSourceType.LOCAL_FOLDER,
            default_local_storage_integration=self.local_integration,
            document_execution_mode=AgentDocumentExecutionMode.INDIVIDUAL,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
        )
        self.url = reverse("portal_agente_executar", kwargs={"slug": self.agente.slug})

    def _criar_arquivo(self, nome):
        (self.base_path / nome).write_bytes(b"pdf")

    def test_cria_1_processamento_por_arquivo_e_redireciona_filtrado(self):
        self._criar_arquivo("a.pdf")
        self._criar_arquivo("b.pdf")

        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=_fake_execute_document_sucesso,
        ):
            resp = self.client.post(self.url, follow=True)

        processamentos = Processamento.objects.filter(agente=self.agente)
        self.assertEqual(processamentos.count(), 2)
        for p in processamentos:
            self.assertEqual(p.documentos.count(), 1)
            self.assertEqual(p.status, ProcessingStatus.CONCLUIDO_SUCESSO)

        codigos = set(processamentos.values_list("codigo", flat=True))
        redirect_url = resp.redirect_chain[0][0]
        self.assertTrue(redirect_url.startswith(reverse("portal_processamentos")))
        codigos_na_url = set(redirect_url.split("codigos=")[1].split(","))
        self.assertEqual(codigos_na_url, codigos)

    def test_ajax_retorna_redirect_url(self):
        self._criar_arquivo("a.pdf")

        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=_fake_execute_document_sucesso,
        ):
            resp = self.client.post(
                self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest"
            )

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("redirect_url", data)
        self.assertTrue(data["redirect_url"].startswith(reverse("portal_processamentos")))

    def test_pasta_vazia_mostra_mensagem_e_nao_cria_processamento(self):
        resp = self.client.post(self.url, follow=True)

        self.assertEqual(Processamento.objects.filter(agente=self.agente).count(), 0)
        mensagens = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("Nenhum arquivo novo" in m for m in mensagens))

    def test_agente_grupo_unico_continua_com_1_processamento_so(self):
        # Regressao: agente NAO individual continua no caminho antigo.
        self.agente.configuracao_operacional.document_execution_mode = (
            AgentDocumentExecutionMode.GRUPO_UNICO
        )
        self.agente.configuracao_operacional.output_assembly_mode = (
            AgentOutputAssemblyMode.UMA_SAIDA_FINAL
        )
        self.agente.configuracao_operacional.save(
            update_fields=["document_execution_mode", "output_assembly_mode"]
        )
        self._criar_arquivo("a.pdf")
        self._criar_arquivo("b.pdf")

        with patch(
            "apps.processamentos.services.agent_execution._execute_document_group"
        ) as mock_grupo:
            mock_grupo.return_value = {
                "output_records": [],
                "total_success": 2,
                "total_errors": 0,
                "last_error_message": "",
                "last_technical_error_message": "",
            }
            self.client.post(self.url)

        self.assertEqual(Processamento.objects.filter(agente=self.agente).count(), 1)
