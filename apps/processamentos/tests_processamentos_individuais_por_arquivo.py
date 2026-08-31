"""
ADR-001 Fase 5b (v2.0.0, regras 1, 4, 5, 6) — cada arquivo (novo ou
retomado) ganha seu PROPRIO Processamento, nunca compartilhado, para
agentes em modo Individual (document_execution_mode=INDIVIDUAL ou
output_assembly_mode=UMA_POR_ENTRADA — ver agent_execution.
_usa_execucao_individual). GRUPO_UNICO/LOTE_POR_PASTA continuam usando
criar_e_iniciar_processamento_para_agente, sem nenhuma mudanca.

Ver document_sources._descobrir_e_criar_processamentos_individuais
(reaproveita 100% do prepare_documentos existente via um Processamento
"staging" descartavel) e operational_execution.
criar_e_iniciar_processamentos_individuais_para_agente (orquestracao por
rodada: trava adquirida 1 vez, pendentes retomados com prioridade, depois
descoberta de arquivos novos).
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import TestCase

from apps.agentes_ia.models import (
    AgenteConfiguracaoOperacional,
    AgenteIA,
    AgentDefaultInputSourceType,
    AgentDocumentExecutionMode,
    AgentOutputAssemblyMode,
    AgentStatus,
    AgentType,
)
from apps.integracoes.services.ai_providers import AIProviderServiceError
from apps.integracoes.models import AIProviderIntegration, IntegrationStatus, LocalStorageIntegration
from apps.agentes_ia.services import montar_payload_execucao_padrao
from apps.processamentos.models import (
    DocumentoSaidaProcessamento,
    DocumentStatus,
    ExecutionScopeType,
    OutputDocumentStatus,
    Processamento,
    ProcessingStatus,
)
from apps.core.models import ConfiguracaoGeral
from apps.processamentos.models import RotinaAutomaticaExecucao, RotinaAutomaticaExecucaoStatus
from apps.processamentos.services.operational_execution import (
    _agente_usa_execucao_individual,
    _descobrir_e_criar_processamentos_individuais,
    _tentar_adquirir_trava_execucao,
    criar_e_iniciar_processamentos_individuais_para_agente,
    executar_rotinas_automaticas_agentes,
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


def _levanta_erro_provedor(**kwargs):
    raise AIProviderServiceError("Falha HTTP 400 ao executar o agente no provedor")


class AgenteUsaExecucaoIndividualTests(TestCase):
    def test_modo_individual_e_individual(self):
        configuracao = AgenteConfiguracaoOperacional(
            document_execution_mode=AgentDocumentExecutionMode.INDIVIDUAL,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_SAIDA_FINAL,
        )
        self.assertTrue(_agente_usa_execucao_individual(configuracao))

    def test_assembly_uma_por_entrada_e_individual(self):
        configuracao = AgenteConfiguracaoOperacional(
            document_execution_mode=AgentDocumentExecutionMode.LOTE_POR_PASTA,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
        )
        self.assertTrue(_agente_usa_execucao_individual(configuracao))

    def test_grupo_unico_nao_e_individual(self):
        configuracao = AgenteConfiguracaoOperacional(
            document_execution_mode=AgentDocumentExecutionMode.LOTE_POR_PASTA,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_SAIDA_FINAL,
        )
        self.assertFalse(_agente_usa_execucao_individual(configuracao))


class _BaseComPastaLocal(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono-individual", password="x")
        self.ai_integration = AIProviderIntegration.objects.create(
            nome=f"Integracao Individual {self.id()}",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-teste",
        )
        self._tmpdir = tempfile.TemporaryDirectory()
        self.base_path = Path(self._tmpdir.name)
        self.addCleanup(self._tmpdir.cleanup)
        self.local_integration = LocalStorageIntegration.objects.create(
            nome=f"Pasta Individual {self.id()}",
            base_path=str(self.base_path),
            status=IntegrationStatus.ATIVA,
            allowed_extensions=["pdf"],
        )
        self.agente = AgenteIA.objects.create(
            nome="Agente Individual",
            slug=f"agente-individual-{self.id()}",
            tipo=AgentType.GENERICO,
            ai_provider_integration=self.ai_integration,
            status=AgentStatus.ATIVO,
            prompt_base="prompt",
            created_by=self.user,
        )
        self.configuracao = AgenteConfiguracaoOperacional.objects.create(
            agente=self.agente,
            default_input_source_type=AgentDefaultInputSourceType.LOCAL_FOLDER,
            default_local_storage_integration=self.local_integration,
            document_execution_mode=AgentDocumentExecutionMode.INDIVIDUAL,
            output_assembly_mode=AgentOutputAssemblyMode.UMA_POR_ENTRADA,
        )

    def _criar_arquivo(self, nome):
        (self.base_path / nome).write_bytes(b"pdf")

    def _cleaned_data(self):
        return montar_payload_execucao_padrao(self.agente)


class DescobrirECriarProcessamentosIndividuaisTests(_BaseComPastaLocal):
    def test_cria_1_processamento_por_arquivo_descoberto(self):
        self._criar_arquivo("a.pdf")
        self._criar_arquivo("b.pdf")
        self._criar_arquivo("c.pdf")

        novos = _descobrir_e_criar_processamentos_individuais(
            agente=self.agente, actor=self.user, cleaned_data=self._cleaned_data()
        )

        self.assertEqual(len(novos), 3)
        nomes = set()
        for processamento in novos:
            self.assertEqual(processamento.documentos.count(), 1)
            self.assertEqual(processamento.status, ProcessingStatus.EM_FILA)
            nomes.add(processamento.documentos.first().nome_arquivo)
        self.assertEqual(nomes, {"a.pdf", "b.pdf", "c.pdf"})

    def test_staging_e_apagado_apos_a_descoberta(self):
        self._criar_arquivo("a.pdf")
        total_antes = Processamento.all_objects.count()

        novos = _descobrir_e_criar_processamentos_individuais(
            agente=self.agente, actor=self.user, cleaned_data=self._cleaned_data()
        )

        # +1 (o Processamento dedicado de "a.pdf") — o staging nao sobra.
        self.assertEqual(Processamento.all_objects.count(), total_antes + 1)
        self.assertEqual(len(novos), 1)

    def test_respeita_o_limite_de_novos_processamentos(self):
        self._criar_arquivo("a.pdf")
        self._criar_arquivo("b.pdf")
        self._criar_arquivo("c.pdf")

        novos = _descobrir_e_criar_processamentos_individuais(
            agente=self.agente, actor=self.user, cleaned_data=self._cleaned_data(), limite=2
        )

        self.assertEqual(len(novos), 2)

    def test_arquivo_ja_processado_por_este_agente_nao_ganha_novo_processamento(self):
        self._criar_arquivo("a.pdf")
        primeira_rodada = _descobrir_e_criar_processamentos_individuais(
            agente=self.agente, actor=self.user, cleaned_data=self._cleaned_data()
        )
        doc = primeira_rodada[0].documentos.first()
        doc.status = DocumentStatus.PROCESSADO
        doc.save(update_fields=["status"])

        segunda_rodada = _descobrir_e_criar_processamentos_individuais(
            agente=self.agente, actor=self.user, cleaned_data=self._cleaned_data()
        )

        self.assertEqual(segunda_rodada, [])


class CriarEIniciarProcessamentosIndividuaisParaAgenteTests(_BaseComPastaLocal):
    def test_cria_e_executa_1_processamento_por_arquivo(self):
        self._criar_arquivo("a.pdf")
        self._criar_arquivo("b.pdf")

        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=_fake_execute_document_sucesso,
        ):
            tocados = criar_e_iniciar_processamentos_individuais_para_agente(
                agente=self.agente, actor=self.user, cleaned_data=self._cleaned_data()
            )

        self.assertEqual(len(tocados), 2)
        for processamento in tocados:
            self.assertEqual(processamento.status, ProcessingStatus.CONCLUIDO_SUCESSO)
            self.assertEqual(processamento.documentos.count(), 1)

    def test_processamento_pendente_retentativa_e_reexecutado_com_prioridade(self):
        self._criar_arquivo("novo.pdf")
        pendente = Processamento.objects.create(
            codigo="PROC-INDIV-PENDENTE-1",
            iniciado_por=self.user,
            agente=self.agente,
            input_source_type="local_folder",
            local_storage_integration=self.local_integration,
            local_relative_input_path="",
            status=ProcessingStatus.PENDENTE_RETENTATIVA,
        )
        from apps.processamentos.models import DocumentoEntrada, ProcessingInputSourceType

        DocumentoEntrada.objects.create(
            processamento=pendente,
            nome_arquivo="pendente.pdf",
            source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            source_reference="pendente.pdf",
            status=DocumentStatus.PENDENTE,
            tentativas_pontuais=1,
        )
        self._criar_arquivo("pendente.pdf")

        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=_fake_execute_document_sucesso,
        ):
            tocados = criar_e_iniciar_processamentos_individuais_para_agente(
                agente=self.agente,
                actor=self.user,
                cleaned_data=self._cleaned_data(),
                limite_documentos_por_execucao=10,
                origem_rotina_automatica=True,
            )

        codigos = {p.codigo for p in tocados}
        self.assertIn("PROC-INDIV-PENDENTE-1", codigos)
        pendente.refresh_from_db()
        self.assertEqual(pendente.status, ProcessingStatus.CONCLUIDO_SUCESSO)
        nomes_processados = {p.documentos.first().nome_arquivo for p in tocados}
        self.assertEqual(nomes_processados, {"pendente.pdf", "novo.pdf"})

    def test_lote_limita_pendentes_mais_novos_juntos(self):
        from apps.processamentos.models import DocumentoEntrada, ProcessingInputSourceType

        for i in range(2):
            pendente = Processamento.objects.create(
                codigo=f"PROC-INDIV-LOTE-PENDENTE-{i}",
                iniciado_por=self.user,
                agente=self.agente,
                input_source_type="local_folder",
                local_storage_integration=self.local_integration,
                local_relative_input_path="",
                status=ProcessingStatus.PENDENTE_RETENTATIVA,
            )
            DocumentoEntrada.objects.create(
                processamento=pendente,
                nome_arquivo=f"pendente{i}.pdf",
                source_type=ProcessingInputSourceType.LOCAL_FOLDER,
                source_reference=f"pendente{i}.pdf",
                status=DocumentStatus.PENDENTE,
                tentativas_pontuais=1,
            )
            self._criar_arquivo(f"pendente{i}.pdf")
        self._criar_arquivo("novo1.pdf")
        self._criar_arquivo("novo2.pdf")

        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=_fake_execute_document_sucesso,
        ):
            tocados = criar_e_iniciar_processamentos_individuais_para_agente(
                agente=self.agente,
                actor=self.user,
                cleaned_data=self._cleaned_data(),
                limite_documentos_por_execucao=3,
                origem_rotina_automatica=True,
            )

        # 2 pendentes (prioridade) + 1 novo = 3 (teto da rodada).
        self.assertEqual(len(tocados), 3)

    def test_trava_por_agente_e_adquirida_uma_unica_vez_por_rodada(self):
        self._criar_arquivo("a.pdf")
        self._criar_arquivo("b.pdf")
        self._criar_arquivo("c.pdf")

        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=_fake_execute_document_sucesso,
        ), patch(
            "apps.processamentos.services.operational_execution._tentar_adquirir_trava_execucao",
            wraps=_tentar_adquirir_trava_execucao,
        ) as spy_trava:
            criar_e_iniciar_processamentos_individuais_para_agente(
                agente=self.agente, actor=self.user, cleaned_data=self._cleaned_data()
            )

        spy_trava.assert_called_once()

    def test_erro_em_1_arquivo_nao_interrompe_o_resto_da_rodada(self):
        self._criar_arquivo("falha.pdf")
        self._criar_arquivo("sucesso.pdf")

        def _executar(*, processamento, documento, **kwargs):
            if documento.nome_arquivo == "falha.pdf":
                return _levanta_erro_provedor()
            return _fake_execute_document_sucesso(
                processamento=processamento, documento=documento, **kwargs
            )

        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=_executar,
        ):
            tocados = criar_e_iniciar_processamentos_individuais_para_agente(
                agente=self.agente, actor=self.user, cleaned_data=self._cleaned_data()
            )

        self.assertEqual(len(tocados), 2)
        status_por_arquivo = {
            p.documentos.first().nome_arquivo: p.status for p in tocados
        }
        self.assertEqual(status_por_arquivo["sucesso.pdf"], ProcessingStatus.CONCLUIDO_SUCESSO)
        # Execucao manual (sem limite_documentos_por_execucao) nao adia erro
        # pontual do provedor — vira erro definitivo na hora, como sempre.
        self.assertEqual(status_por_arquivo["falha.pdf"], ProcessingStatus.CONCLUIDO_ERRO)


class RotinaAutomaticaComAgenteIndividualEndToEndTests(_BaseComPastaLocal):
    """ADR-001 Fase 5b (v2.0.0) — executar_rotinas_automaticas_agentes de
    ponta a ponta com um agente Individual real: confirma que a rodada
    (RotinaAutomaticaExecucao) liga N Processamentos via o campo novo
    (Processamento.rotina_automatica_execucao, Fase 5a) em vez do
    OneToOneField legado (que fica None)."""

    def setUp(self):
        super().setUp()
        self.configuracao.execucao_automatica_ativa = True
        self.configuracao.save(update_fields=["execucao_automatica_ativa"])
        ConfiguracaoGeral.objects.all().delete()
        config_geral = ConfiguracaoGeral.obter()
        config_geral.rotina_automatica_agentes_ativa = True
        config_geral.rotina_automatica_lote_tamanho = 10
        config_geral.save(
            update_fields=["rotina_automatica_agentes_ativa", "rotina_automatica_lote_tamanho"]
        )

    def test_rodada_liga_n_processamentos_via_campo_novo(self):
        self._criar_arquivo("a.pdf")
        self._criar_arquivo("b.pdf")

        with patch(
            "apps.processamentos.services.agent_execution._execute_document",
            side_effect=_fake_execute_document_sucesso,
        ):
            executar_rotinas_automaticas_agentes()

        rodada = RotinaAutomaticaExecucao.objects.get(agente=self.agente)
        self.assertEqual(rodada.status, RotinaAutomaticaExecucaoStatus.EXECUTADA)
        self.assertIsNone(rodada.processamento_id)  # legado, nao populado
        self.assertEqual(rodada.processamentos_da_rodada.count(), 2)
        self.assertEqual(rodada.total_documentos, 2)
        self.assertEqual(rodada.total_sucesso, 2)
        for processamento in rodada.processamentos_da_rodada.all():
            self.assertEqual(processamento.documentos.count(), 1)
            self.assertEqual(processamento.status, ProcessingStatus.CONCLUIDO_SUCESSO)

    def test_pasta_vazia_registra_sem_documentos(self):
        executar_rotinas_automaticas_agentes()

        rodada = RotinaAutomaticaExecucao.objects.get(agente=self.agente)
        self.assertEqual(rodada.status, RotinaAutomaticaExecucaoStatus.SEM_DOCUMENTOS)
        self.assertEqual(rodada.processamentos_da_rodada.count(), 0)
