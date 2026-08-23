"""
Tamanho de pagina dos grids de Processamentos e do historico da Rotina
automatica — reduzido pra 10 itens por pagina (era 20 e 25) pra nao carregar
lista grande demais de uma vez na tela, mostrando o resto so quando a
pessoa clica na paginacao (que ja existe nos dois grids, com link de
pagina — nao acumula DOM de paginas antigas, cada clique e uma nova
requisicao).
"""

from django.contrib.auth.models import User
from django.test import TestCase

from apps.agentes_ia.models import AgenteIA, AgentStatus, AgentType
from apps.integracoes.models import AIProviderIntegration, IntegrationStatus
from apps.processamentos.models import (
    Processamento,
    ProcessingInputSourceType,
    RotinaAutomaticaExecucao,
    RotinaAutomaticaExecucaoStatus,
)
from apps.processamentos.selectors import (
    listar_historico_rotina_automatica,
    listar_processamentos_para_portal,
)


class PaginacaoGridsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono-paginacao", password="x")
        self.ai_integration = AIProviderIntegration.objects.create(
            nome="Integracao Paginacao",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-teste",
        )
        self.agente = AgenteIA.objects.create(
            nome="Agente Paginacao",
            slug="agente-paginacao",
            tipo=AgentType.GENERICO,
            ai_provider_integration=self.ai_integration,
            status=AgentStatus.ATIVO,
            prompt_base="prompt",
        )

    def test_grid_de_processamentos_mostra_so_10_por_pagina(self):
        for i in range(15):
            Processamento.objects.create(
                codigo=f"PROC-PAGINACAO-{i}",
                iniciado_por=self.user,
                agente=self.agente,
                input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            )

        resultado = listar_processamentos_para_portal()

        self.assertEqual(resultado.itens_por_pagina, 10)
        self.assertEqual(len(resultado.processamentos), 10)
        self.assertEqual(resultado.total, 15)
        self.assertTrue(resultado.tem_proxima_pagina)

    def test_grid_do_historico_da_rotina_mostra_so_10_por_pagina(self):
        for i in range(15):
            RotinaAutomaticaExecucao.objects.create(
                agente=self.agente,
                status=RotinaAutomaticaExecucaoStatus.SEM_DOCUMENTOS,
            )

        resultado = listar_historico_rotina_automatica()

        self.assertEqual(resultado.itens_por_pagina, 10)
        self.assertEqual(len(resultado.execucoes), 10)
        self.assertEqual(resultado.total, 15)
        self.assertTrue(resultado.tem_proxima_pagina)
