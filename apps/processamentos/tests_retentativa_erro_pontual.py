"""
Retentativa de erro pontual do provedor de IA ENTRE RODADAS da rotina
automatica — diferente do loop de retentativa por sobrecarga (ver
tests_retentativa_sobrecarga_provedor.py, que mantem o MESMO Processamento
vivo ate o teto de agent_execution.LIMITE_RETENTATIVA_SOBRECARGA) e da
retentativa de fim de lote (ver tests_retentativa_fim_lote.py, que tenta de
novo dentro da MESMA rodada).

Aqui: um documento que falha por qualquer AIProviderServiceError na rotina
automatica fica PENDENTE (nao ERRO) em vez de finalizar na hora, e e
readotado com prioridade pela PROXIMA rodada da rotina (novo Processamento).
So na 2a falha consecutiva vira ERRO definitivo e para de ser redescoberto
automaticamente — so um reenvio manual com "forcar_reprocessamento" o traz
de volta. Ver DocumentoEntrada.tentativas_pontuais,
agent_execution._marcar_documento_pendente_retentativa e
document_sources.adotar_documentos_pendentes_de_retentativa.

Caso real que motivou a mudanca: agente "JHS (Licitacao)", 21/08/2026 —
gemini-2.5-pro recusando thinkingBudget=0 (ver tests_thinking_budget.py);
descartar o documento na 1a falha jogava fora trabalho que uma nova
tentativa, na rodada seguinte, resolveria sozinha.
"""

import inspect
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from apps.agentes_ia.models import (
    AgenteConfiguracaoOperacional,
    AgenteIA,
    AgentDefaultInputSourceType,
    AgentStatus,
    AgentType,
)
from apps.integracoes.services.ai_providers import AIProviderServiceError
from apps.integracoes.models import (
    AIProviderIntegration,
    IntegrationStatus,
    LocalStorageIntegration,
)
from apps.processamentos.models import (
    DocumentoEntrada,
    DocumentoSaidaProcessamento,
    DocumentStatus,
    ExecutionScopeType,
    OutputDocumentStatus,
    Processamento,
    ProcessingInputSourceType,
    ProcessingStatus,
)
from apps.processamentos.services.agent_execution import (
    ProcessamentoExecutionError,
    _execute_documents_as_group,
    _execute_documents_by_folder,
    _execute_documents_individually,
    _marcar_documento_pendente_retentativa,
    execute_processing,
)
from apps.processamentos.services.document_sources import (
    adotar_documentos_pendentes_de_retentativa,
)


class MarcarDocumentoPendenteRetentativaTests(SimpleTestCase):
    """Unidade isolada: so reescreve o status/contador do documento. O
    registro de auditoria da tentativa que falhou ja foi criado antes, por
    _mark_document_error (nao e responsabilidade desta funcao)."""

    def test_sobrescreve_erro_para_pendente_e_incrementa_contador(self):
        documento = MagicMock()
        documento.tentativas_pontuais = 0
        # Estado deixado por _mark_document_error logo antes desta chamada.
        documento.status = DocumentStatus.ERRO
        documento.mensagem_erro = "Falha HTTP 400 ao executar o agente no provedor"
        documento.erro_reprocessavel = False

        _marcar_documento_pendente_retentativa(documento)

        self.assertEqual(documento.status, DocumentStatus.PENDENTE)
        self.assertEqual(documento.mensagem_erro, "")
        self.assertTrue(documento.erro_reprocessavel)
        self.assertEqual(documento.tentativas_pontuais, 1)
        documento.save.assert_called_once_with(
            update_fields=[
                "status",
                "mensagem_erro",
                "erro_reprocessavel",
                "tentativas_pontuais",
                "updated_at",
            ]
        )


class ExecucaoEmGrupoOuPastaNaoAdiaTests(SimpleTestCase):
    """A retentativa entre rotinas so existe no modo de execucao individual
    (mesmo recorte que o loop de sobrecarga ja usa, ver
    agent_execution.execute_processing) — grupo/pasta nem recebem o
    parametro, por construcao."""

    def test_execucao_por_pasta_nao_tem_parametro_de_adiamento(self):
        assinatura = inspect.signature(_execute_documents_by_folder)
        self.assertNotIn("permite_adiamento_erro_pontual", assinatura.parameters)

    def test_execucao_em_grupo_nao_tem_parametro_de_adiamento(self):
        assinatura = inspect.signature(_execute_documents_as_group)
        self.assertNotIn("permite_adiamento_erro_pontual", assinatura.parameters)

    def test_execucao_individual_aceita_o_parametro_desligado_por_padrao(self):
        assinatura = inspect.signature(_execute_documents_individually)
        self.assertIn("permite_adiamento_erro_pontual", assinatura.parameters)
        self.assertFalse(
            assinatura.parameters["permite_adiamento_erro_pontual"].default
        )


class AdotarDocumentosPendentesDeRetentativaTests(TestCase):
    """Testa so a query/reatribuicao, sem rodar execute_processing inteiro."""

    def setUp(self):
        self.user = User.objects.create_user(username="dono-adocao", password="x")
        self.ai_integration = AIProviderIntegration.objects.create(
            nome="Integracao Adocao",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-teste",
        )
        self.agente = AgenteIA.objects.create(
            nome="Agente Adocao",
            slug="agente-adocao",
            tipo=AgentType.GENERICO,
            ai_provider_integration=self.ai_integration,
            status=AgentStatus.ATIVO,
            prompt_base="prompt",
        )

    def _processamento(self, sufixo, *, agente=None):
        return Processamento.objects.create(
            codigo=f"PROC-ADOCAO-{sufixo}",
            iniciado_por=self.user,
            agente=agente or self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
        )

    def _documento_pendente_retentativa(self, processamento, nome, *, tentativas=1, ha=None):
        documento = DocumentoEntrada.objects.create(
            processamento=processamento,
            nome_arquivo=nome,
            source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            source_reference=nome,
            status=DocumentStatus.PENDENTE,
            tentativas_pontuais=tentativas,
        )
        if ha is not None:
            DocumentoEntrada.objects.filter(pk=documento.pk).update(
                updated_at=timezone.now() - ha
            )
        return documento

    def test_reatribui_documento_pendente_de_rodada_anterior(self):
        rodada_1 = self._processamento("1")
        novo = self._processamento("2")
        documento = self._documento_pendente_retentativa(rodada_1, "doc.pdf")

        adotados = adotar_documentos_pendentes_de_retentativa(novo, limite=10)

        documento.refresh_from_db()
        self.assertEqual(adotados, 1)
        self.assertEqual(documento.processamento_id, novo.id)
        self.assertEqual(documento.status, DocumentStatus.PENDENTE)

    def test_nao_adota_documento_pendente_de_1a_tentativa(self):
        # tentativas_pontuais=0 == nunca falhou antes: e um PENDENTE comum
        # (arquivo novo ainda nao executado), nao uma retentativa.
        rodada_1 = self._processamento("1")
        novo = self._processamento("2")
        self._documento_pendente_retentativa(rodada_1, "doc.pdf", tentativas=0)

        adotados = adotar_documentos_pendentes_de_retentativa(novo, limite=10)

        self.assertEqual(adotados, 0)

    def test_nao_adota_documento_ja_definitivamente_com_erro(self):
        rodada_1 = self._processamento("1")
        novo = self._processamento("2")
        documento = self._documento_pendente_retentativa(rodada_1, "doc.pdf")
        documento.status = DocumentStatus.ERRO
        documento.save(update_fields=["status"])

        adotados = adotar_documentos_pendentes_de_retentativa(novo, limite=10)

        self.assertEqual(adotados, 0)

    def test_respeita_limite_e_prioriza_os_mais_antigos(self):
        rodada_1 = self._processamento("1")
        novo = self._processamento("2")
        mais_antigo = self._documento_pendente_retentativa(
            rodada_1, "antigo.pdf", ha=timedelta(hours=2)
        )
        mais_novo = self._documento_pendente_retentativa(
            rodada_1, "novo.pdf", ha=timedelta(minutes=1)
        )

        adotados = adotar_documentos_pendentes_de_retentativa(novo, limite=1)

        self.assertEqual(adotados, 1)
        mais_antigo.refresh_from_db()
        mais_novo.refresh_from_db()
        self.assertEqual(mais_antigo.processamento_id, novo.id)
        self.assertEqual(mais_novo.processamento_id, rodada_1.id)

    def test_nao_adota_de_outro_agente(self):
        outro_agente = AgenteIA.objects.create(
            nome="Outro Agente",
            slug="outro-agente-adocao",
            tipo=AgentType.GENERICO,
            ai_provider_integration=self.ai_integration,
            status=AgentStatus.ATIVO,
            prompt_base="prompt",
        )
        rodada_1 = self._processamento("outro", agente=outro_agente)
        novo = self._processamento("2")
        self._documento_pendente_retentativa(rodada_1, "doc.pdf")

        adotados = adotar_documentos_pendentes_de_retentativa(novo, limite=10)

        self.assertEqual(adotados, 0)

    def test_limite_zero_ou_none_nao_adota(self):
        rodada_1 = self._processamento("1")
        novo = self._processamento("2")
        self._documento_pendente_retentativa(rodada_1, "doc.pdf")

        self.assertEqual(adotar_documentos_pendentes_de_retentativa(novo, limite=0), 0)
        self.assertEqual(adotar_documentos_pendentes_de_retentativa(novo, limite=None), 0)


class RetentativaErroPontualEndToEndTests(TestCase):
    """Ciclo completo via execute_processing, como a rotina automatica
    realmente chama (ver operational_execution._executar_rotina_automatica_agente),
    reaproveitando o mesmo padrao de fixture de
    LimiteDocumentosPorExecucaoTests (tests_rotina_automatica_agentes.py)."""

    def setUp(self):
        self.user = User.objects.create_user(username="dono-pontual", password="x")
        self.ai_integration = AIProviderIntegration.objects.create(
            nome="Integracao Pontual",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-teste",
        )
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.local_integration = LocalStorageIntegration.objects.create(
            nome="Pasta Pontual",
            base_path=str(self.base_path),
            status=IntegrationStatus.ATIVA,
            allowed_extensions=["pdf"],
        )
        self.agente = AgenteIA.objects.create(
            nome="Agente Pontual",
            slug="agente-pontual",
            tipo=AgentType.GENERICO,
            ai_provider_integration=self.ai_integration,
            status=AgentStatus.ATIVO,
            prompt_base="prompt",
        )
        AgenteConfiguracaoOperacional.objects.create(
            agente=self.agente,
            default_input_source_type=AgentDefaultInputSourceType.LOCAL_FOLDER,
            default_local_storage_integration=self.local_integration,
        )
        (self.base_path / "falha.pdf").write_bytes(b"pdf")

    def _processamento(self, sufixo):
        return Processamento.objects.create(
            codigo=f"PROC-PONTUAL-{sufixo}",
            iniciado_por=self.user,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            local_storage_integration=self.local_integration,
            local_relative_input_path="",
        )

    @staticmethod
    def _levanta_erro_provedor(**kwargs):
        raise AIProviderServiceError("Falha HTTP 400 ao executar o agente no provedor")

    @staticmethod
    def _fake_execute_document_sucesso(*, processamento, documento, **kwargs):
        # Mesmo padrao de LimiteDocumentosPorExecucaoTests
        # (tests_rotina_automatica_agentes.py): gera uma saida real (nao um
        # MagicMock), ja que publicar_saida_final le bytes de verdade do
        # arquivo ao montar o ZIP final.
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

    def test_1a_falha_na_rotina_automatica_fica_pendente_sem_virar_erro(self):
        processamento = self._processamento("1")
        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=self._levanta_erro_provedor,
        ):
            execute_processing(processamento, self.user, limite_documentos_por_execucao=10)

        documento = processamento.documentos.get(nome_arquivo="falha.pdf")
        self.assertEqual(documento.status, DocumentStatus.PENDENTE)
        self.assertEqual(documento.tentativas_pontuais, 1)
        # Nao conta como erro do lote — processamento fecha sucesso mesmo
        # com o unico documento ainda pendente (status por documento, nao
        # trava o processamento pai).
        processamento.refresh_from_db()
        self.assertEqual(processamento.status, ProcessingStatus.CONCLUIDO_SUCESSO)

    def test_execucao_manual_nao_adia_erro_do_provedor(self):
        processamento = self._processamento("manual")
        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=self._levanta_erro_provedor,
        ):
            # Sem limite_documentos_por_execucao == execucao manual (ver
            # apps/core/views.py, que nunca passa esse parametro).
            execute_processing(processamento, self.user)

        documento = processamento.documentos.get(nome_arquivo="falha.pdf")
        self.assertEqual(documento.status, DocumentStatus.ERRO)
        self.assertEqual(documento.tentativas_pontuais, 0)

    def test_ciclo_completo_pendente_depois_erro_definitivo_depois_ignorado(self):
        # Rodada 1: 1a falha -> PENDENTE.
        rodada_1 = self._processamento("1")
        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=self._levanta_erro_provedor,
        ):
            execute_processing(rodada_1, self.user, limite_documentos_por_execucao=10)
        documento = rodada_1.documentos.get(nome_arquivo="falha.pdf")
        self.assertEqual(documento.status, DocumentStatus.PENDENTE)
        self.assertEqual(documento.tentativas_pontuais, 1)

        # Rodada 2 (rotina seguinte, novo Processamento): readota o mesmo
        # DocumentoEntrada (nao cria um novo) e, falhando de novo, vira erro
        # definitivo.
        rodada_2 = self._processamento("2")
        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=self._levanta_erro_provedor,
        ):
            execute_processing(rodada_2, self.user, limite_documentos_por_execucao=10)

        documento.refresh_from_db()
        self.assertEqual(documento.processamento_id, rodada_2.id)
        self.assertEqual(rodada_1.documentos.count(), 0)
        self.assertEqual(documento.status, DocumentStatus.ERRO)
        self.assertEqual(documento.tentativas_pontuais, 1)

        # Rodada 3: a varredura de pasta nao recria "falha.pdf" do zero —
        # nenhum documento pendente, sem_trabalho.
        rodada_3 = self._processamento("3")
        with self.assertRaises(ProcessamentoExecutionError) as ctx:
            execute_processing(rodada_3, self.user, limite_documentos_por_execucao=10)
        self.assertTrue(getattr(ctx.exception, "sem_trabalho", False))
        self.assertEqual(rodada_3.documentos.count(), 0)

        # "forcar_reprocessamento" (mesmo checkbox manual ja existente) e o
        # unico jeito de trazer o arquivo de volta depois do erro definitivo.
        rodada_4 = self._processamento("4")
        rodada_4.forcar_reprocessamento = True
        rodada_4.save(update_fields=["forcar_reprocessamento"])
        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=self._fake_execute_document_sucesso,
        ):
            execute_processing(rodada_4, self.user, limite_documentos_por_execucao=10)
        novo_documento = rodada_4.documentos.get(nome_arquivo="falha.pdf")
        self.assertNotEqual(novo_documento.id, documento.id)
        self.assertEqual(novo_documento.tentativas_pontuais, 0)
        self.assertEqual(novo_documento.status, DocumentStatus.PROCESSADO)

    def test_rodada_com_um_sucesso_e_um_adiado_fecha_sucesso(self):
        (self.base_path / "sucesso.pdf").write_bytes(b"pdf")
        processamento = self._processamento("misto")

        def _fake_execute_document(*, processamento, documento, **kwargs):
            if documento.nome_arquivo == "falha.pdf":
                raise AIProviderServiceError(
                    "Falha HTTP 400 ao executar o agente no provedor"
                )
            return self._fake_execute_document_sucesso(
                processamento=processamento, documento=documento, **kwargs
            )

        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=_fake_execute_document,
        ):
            execute_processing(processamento, self.user, limite_documentos_por_execucao=10)

        processamento.refresh_from_db()
        self.assertEqual(processamento.status, ProcessingStatus.CONCLUIDO_SUCESSO)
        self.assertEqual(
            processamento.documentos.filter(status=DocumentStatus.PROCESSADO).count(), 1
        )
        self.assertEqual(
            processamento.documentos.filter(status=DocumentStatus.PENDENTE).count(), 1
        )
