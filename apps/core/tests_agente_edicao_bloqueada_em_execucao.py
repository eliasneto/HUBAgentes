"""
ADR-001 Fase 1 — bloqueio de "Editar" enquanto o agente esta em execucao.

Reaproveita o mesmo campo/janela de auto-recuperacao da trava de
concorrencia por agente ja existente (`AgenteConfiguracaoOperacional.
execucao_em_andamento` / `execucao_em_andamento_desde`,
`operational_execution.LIMITE_TRAVA_EXECUCAO_MINUTOS`) — ver
`apps.agentes_ia.services.agente_bloqueado_por_execucao`. So cobre o
formulario de edicao no portal operacional: Excluir e o Django admin
(/admin/) ficam fora desta regra (decisao explicita do usuario, 29/08/2026).
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.agentes_ia.models import (
    AgenteConfiguracaoOperacional,
    AgenteIA,
    AgentStatus,
    AgentType,
)
from apps.integracoes.models import AIProviderIntegration, IntegrationStatus
from apps.processamentos.services.operational_execution import (
    LIMITE_TRAVA_EXECUCAO_MINUTOS,
)


class AgenteEdicaoBloqueadaEmExecucaoTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-edicao", password="x", email="admin@teste.com"
        )
        self.client.force_login(self.admin)

        self.ai_integration = AIProviderIntegration.objects.create(
            nome="Integracao Edicao",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-teste",
        )
        self.agente = AgenteIA.objects.create(
            nome="Agente Edicao",
            slug="agente-edicao",
            tipo=AgentType.GENERICO,
            ai_provider_integration=self.ai_integration,
            status=AgentStatus.ATIVO,
            prompt_base="prompt original",
        )
        self.configuracao = AgenteConfiguracaoOperacional.objects.create(
            agente=self.agente
        )
        self.editar_url = reverse("portal_agente_editar", kwargs={"slug": self.agente.slug})

    def _marcar_em_execucao(self, *, ha=timedelta(minutes=1)):
        self.configuracao.execucao_em_andamento = True
        self.configuracao.execucao_em_andamento_desde = timezone.now() - ha
        self.configuracao.save(
            update_fields=["execucao_em_andamento", "execucao_em_andamento_desde"]
        )

    def test_permite_edicao_quando_agente_nao_esta_em_execucao(self):
        resp = self.client.get(self.editar_url)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["agente_edicao"], self.agente)

    def test_bloqueia_get_quando_agente_em_execucao(self):
        self._marcar_em_execucao()

        resp = self.client.get(self.editar_url, follow=True)

        self.assertRedirects(resp, reverse("portal_agentes_gerenciar"))
        mensagens = [str(m) for m in resp.context["messages"]]
        self.assertTrue(any("em execução agora" in m for m in mensagens))

    def test_bloqueia_post_e_nao_salva_alteracao(self):
        self._marcar_em_execucao()

        resp = self.client.post(
            self.editar_url,
            {"nome": "Nome alterado indevidamente", "prompt_base": "prompt novo"},
            follow=True,
        )

        self.assertRedirects(resp, reverse("portal_agentes_gerenciar"))
        self.agente.refresh_from_db()
        self.assertEqual(self.agente.nome, "Agente Edicao")
        self.assertEqual(self.agente.prompt_base, "prompt original")

    def test_trava_travada_ha_mais_que_o_limite_libera_edicao(self):
        # Auto-recuperacao de crash: mesmo teto ja usado pela trava de
        # execucao (LIMITE_TRAVA_EXECUCAO_MINUTOS) — nao pode bloquear
        # "Editar" para sempre se o processo morreu sem liberar a trava.
        self._marcar_em_execucao(
            ha=timedelta(minutes=LIMITE_TRAVA_EXECUCAO_MINUTOS + 1)
        )

        resp = self.client.get(self.editar_url)

        self.assertEqual(resp.status_code, 200)

    def test_selector_expoe_bloqueado_por_execucao_na_listagem_de_gerenciamento(self):
        from apps.agentes_ia.selectors import listar_agentes_para_gerenciamento

        self._marcar_em_execucao()
        resumo = next(
            r for r in listar_agentes_para_gerenciamento() if r.slug == self.agente.slug
        )

        self.assertTrue(resumo.bloqueado_por_execucao)

    def test_selector_nao_bloqueado_quando_sem_execucao_em_andamento(self):
        from apps.agentes_ia.selectors import listar_agentes_para_gerenciamento

        resumo = next(
            r for r in listar_agentes_para_gerenciamento() if r.slug == self.agente.slug
        )

        self.assertFalse(resumo.bloqueado_por_execucao)

    def test_excluir_nao_e_bloqueado_pela_execucao_em_andamento(self):
        # Regra 9 exclui Excluir explicitamente — so o formulario de edicao
        # fica bloqueado.
        self._marcar_em_execucao()

        resp = self.client.post(
            reverse("portal_agente_excluir", kwargs={"slug": self.agente.slug})
        )

        self.assertRedirects(resp, reverse("portal_agentes_gerenciar"))
        self.assertFalse(AgenteIA.objects.filter(pk=self.agente.pk).exists())
