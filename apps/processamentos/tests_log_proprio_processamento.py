"""
ADR-001 Fase 3 (v2.0.0) — log proprio por processamento.

Reaproveita EventoAuditoria (ja existia, com FK opcional para Processamento)
numa tela dedicada por processamento (ver apps.core.views.ProcessamentoLogView
e apps.auditoria.selectors.listar_eventos_do_processamento), e passa a cobrir
pontos que antes nao geravam nenhum evento: criacao do processamento,
bloqueio por trava (por agente ou global, so quando quem foi bloqueado e uma
execucao MANUAL — a rotina automatica ja tem seu proprio registro em
RotinaAutomaticaExecucao, nao duplicado aqui), documento ignorado por
duplicidade, inicio/desistencia do loop de retentativa por sobrecarga do
provedor de IA.
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
from apps.auditoria.selectors import listar_eventos_do_processamento
from apps.core.models import ConfiguracaoGeral
from apps.integracoes.models import AIProviderIntegration, IntegrationStatus
from apps.processamentos.models import (
    DocumentoEntrada,
    DocumentStatus,
    Processamento,
    ProcessingInputSourceType,
)
from apps.processamentos.services.agent_execution import _finalizar_loop_sobrecarga
from apps.processamentos.services.document_sources import (
    _arquivo_local_ja_processado_anteriormente,
)
from apps.processamentos.services.operational_execution import (
    OperationalExecutionError,
    _tentar_adquirir_trava_execucao,
    _tentar_adquirir_trava_rotina_automatica_global,
    criar_e_iniciar_processamento_para_agente,
)


def _criar_agente_e_integracao(*, sufixo, criado_por):
    integracao = AIProviderIntegration.objects.create(
        nome=f"Integracao Log {sufixo}",
        api_key="chave-teste",
        status=IntegrationStatus.ATIVA,
        default_model="modelo-teste",
    )
    agente = AgenteIA.objects.create(
        nome=f"Agente Log {sufixo}",
        slug=f"agente-log-{sufixo}",
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
class ProcessamentoCriadoEBloqueiosGeramEventoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono-log", password="x")
        self.agente, self.configuracao = _criar_agente_e_integracao(
            sufixo="1", criado_por=self.user
        )
        self.cleaned_data = {
            "input_source_type": AgentDefaultInputSourceType.NONE,
            "output_format": "json",
            "output_destination": "internal_media",
            "document_execution_mode": "individual",
            "output_assembly_mode": "uma_por_entrada",
            "output_packaging_mode": "zip_se_multiplos",
            "prompt_parameters": [],
        }

    def test_processamento_criado_gera_evento(self, mock_execute):
        processamento = criar_e_iniciar_processamento_para_agente(
            agente=self.agente, actor=self.user, cleaned_data=self.cleaned_data
        )

        evento = EventoAuditoria.objects.get(
            processamento=processamento, acao="processamento_criado"
        )
        self.assertEqual(evento.actor, self.user)
        self.assertIn(processamento.codigo, evento.descricao)

    def test_bloqueio_manual_por_trava_de_agente_gera_evento(self, mock_execute):
        _tentar_adquirir_trava_execucao(self.configuracao)

        with self.assertRaises(OperationalExecutionError):
            criar_e_iniciar_processamento_para_agente(
                agente=self.agente, actor=self.user, cleaned_data=self.cleaned_data
            )

        evento = EventoAuditoria.objects.get(acao="execucao_bloqueada_trava_agente")
        self.assertIsNone(evento.processamento)
        self.assertEqual(evento.objeto_tipo, "AgenteIA")
        mock_execute.assert_not_called()

    def test_bloqueio_da_propria_rotina_automatica_nao_duplica_evento(self, mock_execute):
        # A rotina automatica bloqueada pela trava por agente ja fica
        # registrada em RotinaAutomaticaExecucao (status BLOQUEADA) — nao
        # deve gerar TAMBEM um EventoAuditoria (regra explicita da ADR-001,
        # evita duplicar o que ja tem tabela/tela propria).
        _tentar_adquirir_trava_execucao(self.configuracao)

        with self.assertRaises(OperationalExecutionError):
            criar_e_iniciar_processamento_para_agente(
                agente=self.agente,
                actor=self.user,
                cleaned_data=self.cleaned_data,
                origem_rotina_automatica=True,
            )

        self.assertFalse(
            EventoAuditoria.objects.filter(
                acao="execucao_bloqueada_trava_agente"
            ).exists()
        )

    def test_bloqueio_manual_por_trava_global_gera_evento(self, mock_execute):
        ConfiguracaoGeral.objects.all().delete()
        config = ConfiguracaoGeral.obter()
        _tentar_adquirir_trava_rotina_automatica_global(config)

        with self.assertRaises(OperationalExecutionError):
            criar_e_iniciar_processamento_para_agente(
                agente=self.agente, actor=self.user, cleaned_data=self.cleaned_data
            )

        evento = EventoAuditoria.objects.get(
            acao="execucao_bloqueada_rotina_automatica"
        )
        self.assertIsNone(evento.processamento)
        mock_execute.assert_not_called()


class DocumentoIgnoradoPorDuplicidadeGeraEventoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono-log-dedup", password="x")
        self.agente, _ = _criar_agente_e_integracao(sufixo="dedup", criado_por=self.user)

    def _processamento(self, sufixo):
        return Processamento.objects.create(
            codigo=f"PROC-LOG-DEDUP-{sufixo}",
            iniciado_por=self.user,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            local_relative_input_path="",
        )

    def test_arquivo_ja_processado_gera_evento_no_processamento_atual(self):
        rodada_1 = self._processamento("1")
        DocumentoEntrada.objects.create(
            processamento=rodada_1,
            nome_arquivo="edital.pdf",
            source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            source_reference="edital.pdf",
            status=DocumentStatus.PROCESSADO,
        )
        rodada_2 = self._processamento("2")

        ja_tratado = _arquivo_local_ja_processado_anteriormente(rodada_2, "edital.pdf")

        self.assertTrue(ja_tratado)
        evento = EventoAuditoria.objects.get(acao="documento_ignorado_duplicidade")
        # Fica no log do processamento que estava descobrindo AGORA, nao no
        # antigo que ja tratou o arquivo.
        self.assertEqual(evento.processamento_id, rodada_2.id)
        self.assertEqual(evento.payload["processamento_anterior_codigo"], rodada_1.codigo)


class FinalizarLoopSobrecargaGeraEventoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono-log-sobrecarga", password="x")
        self.agente, _ = _criar_agente_e_integracao(sufixo="sobrecarga", criado_por=self.user)
        self.processamento = Processamento.objects.create(
            codigo="PROC-LOG-SOBRECARGA-1",
            iniciado_por=self.user,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            retentativa_sobrecarga_ativa=True,
            retentativa_sobrecarga_iniciada_em=timezone.now(),
        )

    def test_desistencia_apos_teto_gera_evento(self):
        _finalizar_loop_sobrecarga(self.processamento, desistiu_por_timeout=True)

        evento = EventoAuditoria.objects.get(acao="retentativa_sobrecarga_desistiu")
        self.assertEqual(evento.processamento_id, self.processamento.id)

    def test_finalizacao_normal_nao_gera_evento_de_desistencia(self):
        _finalizar_loop_sobrecarga(self.processamento, desistiu_por_timeout=False)

        self.assertFalse(
            EventoAuditoria.objects.filter(
                acao="retentativa_sobrecarga_desistiu"
            ).exists()
        )


class ListarEventosDoProcessamentoTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono-log-selector", password="x")
        self.agente, _ = _criar_agente_e_integracao(sufixo="selector", criado_por=self.user)
        self.processamento = Processamento.objects.create(
            codigo="PROC-LOG-SELECTOR-1",
            iniciado_por=self.user,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
        )
        self.outro_processamento = Processamento.objects.create(
            codigo="PROC-LOG-SELECTOR-2",
            iniciado_por=self.user,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
        )

    def test_filtra_so_eventos_do_processamento_pedido(self):
        EventoAuditoria.objects.create(
            modulo="processamentos", acao="a", processamento=self.processamento
        )
        EventoAuditoria.objects.create(
            modulo="processamentos", acao="b", processamento=self.outro_processamento
        )

        log = listar_eventos_do_processamento(self.processamento)

        self.assertEqual(log.total, 1)
        self.assertEqual(log.eventos[0].acao, "a")

    def test_pagina_respeitando_per_page(self):
        for i in range(3):
            EventoAuditoria.objects.create(
                modulo="processamentos",
                acao=f"evento-{i}",
                processamento=self.processamento,
            )

        log = listar_eventos_do_processamento(self.processamento, per_page=2)

        self.assertEqual(log.total, 3)
        self.assertEqual(len(log.eventos), 2)
        self.assertEqual(log.total_paginas, 2)


class ProcessamentoLogViewTests(TestCase):
    def setUp(self):
        self.dono = User.objects.create_user(username="dono-log-view", password="x")
        self.outro_usuario = User.objects.create_user(username="outro-log-view", password="x")
        self.agente, _ = _criar_agente_e_integracao(sufixo="view", criado_por=self.dono)
        self.processamento = Processamento.objects.create(
            codigo="PROC-LOG-VIEW-1",
            iniciado_por=self.dono,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
        )
        EventoAuditoria.objects.create(
            modulo="processamentos",
            acao="processamento_criado",
            processamento=self.processamento,
            descricao="Processamento criado.",
        )
        self.url = reverse(
            "portal_processamento_log", kwargs={"codigo": self.processamento.codigo}
        )

    def test_dono_ve_o_proprio_log(self):
        self.client.force_login(self.dono)
        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Processamento criado.")

    def test_outro_usuario_nao_admin_recebe_404(self):
        self.client.force_login(self.outro_usuario)
        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, 404)

    def test_admin_ve_log_de_qualquer_processamento(self):
        admin = User.objects.create_superuser(
            username="admin-log-view", password="x", email="a@a.com"
        )
        self.client.force_login(admin)
        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, 200)
