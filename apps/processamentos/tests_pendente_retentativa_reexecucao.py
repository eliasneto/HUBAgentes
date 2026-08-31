"""
ADR-001 Fase 5b (v2.0.0, regra 6) — status ProcessingStatus.PENDENTE_RETENTATIVA
e a 2a/ultima chance automatica para um Processamento individual que adiou
seu unico documento na 1a falha por erro pontual do provedor de IA.

Isto cobre so a fatia "status + reexecucao automatica com trava" da Fase
5b — a reescrita da descoberta para criar 1 Processamento por arquivo (a
parte de maior risco/escopo do plano) ainda nao foi implementada nesta
sessao.
"""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
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
    _reexecutar_processamento_pendente_retentativa,
    _tentar_adquirir_trava_execucao,
    _tentar_adquirir_trava_rotina_automatica_global,
    reexecutar_processamento_existente,
)


def _criar_agente(*, sufixo, criado_por):
    integracao = AIProviderIntegration.objects.create(
        nome=f"Integracao Pendente {sufixo}",
        api_key="chave-teste",
        status=IntegrationStatus.ATIVA,
        default_model="modelo-teste",
    )
    agente = AgenteIA.objects.create(
        nome=f"Agente Pendente {sufixo}",
        slug=f"agente-pendente-{sufixo}",
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
class ReexecutarProcessamentoPendenteRetentativaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono-pendente", password="x")
        self.agente, self.configuracao = _criar_agente(sufixo="1", criado_por=self.user)

    def _processamento(self, *, status, sufixo="1"):
        proc = Processamento.objects.create(
            codigo=f"PROC-PENDENTE-{sufixo}",
            iniciado_por=self.user,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            status=status,
        )
        DocumentoEntrada.objects.create(
            processamento=proc,
            nome_arquivo="falha.pdf",
            source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            source_reference="falha.pdf",
            status=DocumentStatus.PENDENTE,
            tentativas_pontuais=1,
        )
        return proc

    def test_rejeita_status_diferente_de_pendente_retentativa(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)

        with self.assertRaises(OperationalExecutionError):
            _reexecutar_processamento_pendente_retentativa(
                processamento=processamento, actor=self.user
            )

        mock_execute.assert_not_called()

    def test_sucesso_marca_concluido_sucesso(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.PENDENTE_RETENTATIVA)

        def _marcar_sucesso(proc, actor, **kwargs):
            proc.documentos.update(status=DocumentStatus.PROCESSADO)
            proc.status = ProcessingStatus.CONCLUIDO_SUCESSO
            proc.save(update_fields=["status"])

        mock_execute.side_effect = _marcar_sucesso

        resultado = _reexecutar_processamento_pendente_retentativa(
            processamento=processamento, actor=self.user
        )

        self.assertEqual(resultado.status, ProcessingStatus.CONCLUIDO_SUCESSO)
        self.assertFalse(resultado.bloqueado_permanentemente)

    def test_segunda_falha_vira_erro_definitivo_e_trava_permanentemente(self, mock_execute):
        # Regra 6: so 1 chance extra — se tambem falhar (qualquer motivo),
        # vira Erro definitivo e o Processamento nao roda mais.
        processamento = self._processamento(status=ProcessingStatus.PENDENTE_RETENTATIVA)
        mock_execute.side_effect = DocumentSourcePreparationError("Falha de novo")

        with self.assertRaises(OperationalExecutionError):
            _reexecutar_processamento_pendente_retentativa(
                processamento=processamento, actor=self.user
            )

        processamento.refresh_from_db()
        self.assertEqual(processamento.status, ProcessingStatus.CONCLUIDO_ERRO)
        self.assertTrue(processamento.bloqueado_permanentemente)

    def test_gera_evento_de_retentativa_iniciada(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.PENDENTE_RETENTATIVA)

        _reexecutar_processamento_pendente_retentativa(
            processamento=processamento, actor=self.user
        )

        self.assertTrue(
            EventoAuditoria.objects.filter(
                processamento=processamento, acao="retentativa_pendente_iniciada"
            ).exists()
        )

    def test_respeita_trava_por_agente(self, mock_execute):
        processamento = self._processamento(status=ProcessingStatus.PENDENTE_RETENTATIVA)
        _tentar_adquirir_trava_execucao(self.configuracao)

        with self.assertRaises(OperationalExecutionError):
            _reexecutar_processamento_pendente_retentativa(
                processamento=processamento, actor=self.user
            )

        mock_execute.assert_not_called()

    def test_nao_e_bloqueada_pela_propria_trava_global_da_rotina(self, mock_execute):
        # origem_rotina_automatica=True (interno) -- a rotina nao se
        # autobloqueia com a trava global que ela mesma segura durante o
        # ciclo (Fase 2).
        processamento = self._processamento(status=ProcessingStatus.PENDENTE_RETENTATIVA)
        ConfiguracaoGeral.objects.all().delete()
        config = ConfiguracaoGeral.obter()
        _tentar_adquirir_trava_rotina_automatica_global(config)

        _reexecutar_processamento_pendente_retentativa(
            processamento=processamento, actor=self.user
        )

        mock_execute.assert_called_once()

    def test_manual_tambem_pode_reexecutar_pendente_retentativa(self, mock_execute):
        # ADR-001 Fase 5b: eligibilidade do botao "Executar" manual foi
        # ampliada para tambem cobrir PENDENTE_RETENTATIVA, nao so
        # CONCLUIDO_ERRO (Fase 4) -- usuario pode forcar a retentativa antes
        # da proxima rotina.
        processamento = self._processamento(status=ProcessingStatus.PENDENTE_RETENTATIVA)

        reexecutar_processamento_existente(processamento=processamento, actor=self.user)

        mock_execute.assert_called_once()
        self.assertTrue(
            EventoAuditoria.objects.filter(
                processamento=processamento, acao="reexecucao_manual_iniciada"
            ).exists()
        )
