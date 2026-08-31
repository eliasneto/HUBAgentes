"""
Percentual exibido na tela de Processamentos (selectors._calcular_percentual).

Bug relatado testando no servidor local (30/08/2026): um Processamento
individual (1 documento, ver ADR-001 Fase 5b) que terminava em erro ficava
com a barra de progresso zerada para sempre, como se nada tivesse
acontecido — mesmo tendo rodado o processo inteiro. `_total_processados`
so contava documentos PROCESSADO, nunca ERRO, entao um Processamento
CONCLUIDO_ERRO com 0 documentos PROCESSADO calculava 0%. Corrigido: todo
status terminal (concluido_sucesso/erro/atencao/cancelado) mostra 100%,
porque o CICLO de execucao terminou — nao porque todo documento teve
sucesso. PENDENTE_RETENTATIVA fica de fora de proposito (ainda vai rodar
de novo).
"""

from django.contrib.auth.models import User
from django.test import TestCase

from apps.agentes_ia.models import AgenteIA, AgentStatus, AgentType
from apps.integracoes.models import AIProviderIntegration, IntegrationStatus
from apps.processamentos.models import (
    DocumentoEntrada,
    DocumentStatus,
    Processamento,
    ProcessingInputSourceType,
    ProcessingStatus,
)
from apps.processamentos.selectors import _calcular_percentual


class CalcularPercentualTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono-percentual", password="x")
        integracao = AIProviderIntegration.objects.create(
            nome="Integracao Percentual",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-teste",
        )
        self.agente = AgenteIA.objects.create(
            nome="Agente Percentual",
            slug="agente-percentual",
            tipo=AgentType.GENERICO,
            ai_provider_integration=integracao,
            status=AgentStatus.ATIVO,
            prompt_base="prompt",
        )

    def _processamento(self, *, status, total_documentos=1):
        processamento = Processamento.objects.create(
            codigo=f"PROC-PCT-{Processamento.objects.count()}",
            iniciado_por=self.user,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            status=status,
            total_documentos=total_documentos,
        )
        return processamento

    def _documento(self, processamento, *, status, nome="doc.pdf"):
        return DocumentoEntrada.objects.create(
            processamento=processamento,
            nome_arquivo=nome,
            source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            source_reference=nome,
            status=status,
        )

    def test_concluido_erro_com_1_documento_mostra_100_por_cento(self):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO)
        self._documento(processamento, status=DocumentStatus.ERRO)

        self.assertEqual(_calcular_percentual(processamento), 100)

    def test_concluido_sucesso_mostra_100_por_cento(self):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_SUCESSO)
        self._documento(processamento, status=DocumentStatus.PROCESSADO)

        self.assertEqual(_calcular_percentual(processamento), 100)

    def test_concluido_atencao_mostra_100_por_cento(self):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ATENCAO)

        self.assertEqual(_calcular_percentual(processamento), 100)

    def test_concluido_erro_multi_documento_com_falha_parcial_mostra_100_por_cento(self):
        processamento = self._processamento(status=ProcessingStatus.CONCLUIDO_ERRO, total_documentos=3)
        self._documento(processamento, status=DocumentStatus.PROCESSADO, nome="a.pdf")
        self._documento(processamento, status=DocumentStatus.ERRO, nome="b.pdf")
        self._documento(processamento, status=DocumentStatus.PENDENTE, nome="c.pdf")

        self.assertEqual(_calcular_percentual(processamento), 100)

    def test_em_fila_ainda_nao_iniciado_mostra_0_por_cento(self):
        processamento = self._processamento(status=ProcessingStatus.EM_FILA)
        self._documento(processamento, status=DocumentStatus.PENDENTE)

        self.assertEqual(_calcular_percentual(processamento), 0)

    def test_pendente_retentativa_nao_mostra_100_por_cento(self):
        # Ainda vai rodar de novo na proxima rotina — 100% seria enganoso.
        processamento = self._processamento(status=ProcessingStatus.PENDENTE_RETENTATIVA)
        self._documento(processamento, status=DocumentStatus.PENDENTE)

        self.assertEqual(_calcular_percentual(processamento), 0)

    def test_em_processamento_com_subprogresso_continua_incremental(self):
        # Regressao: o calculo de sub-progresso durante EM_PROCESSAMENTO
        # (ver Processamento.progresso_etapa_percentual) nao foi afetado.
        processamento = self._processamento(status=ProcessingStatus.EM_PROCESSAMENTO)
        processamento.progresso_etapa_percentual = 40
        processamento.save(update_fields=["progresso_etapa_percentual"])
        self._documento(processamento, status=DocumentStatus.EM_PROCESSAMENTO)

        self.assertEqual(_calcular_percentual(processamento), 40)
