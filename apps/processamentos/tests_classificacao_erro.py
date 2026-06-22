"""
Classificacao de mensagens: indisponibilidade temporaria do provedor de IA deve
ser tratada como "atencao" (amarelo), nao como erro tecnico (vermelho).
"""

from django.test import SimpleTestCase

from apps.integracoes.services.ai_providers.base import (
    _PROVIDER_TEMPORARIAMENTE_INDISPONIVEL,
)
from apps.processamentos.services.operational_execution import _e_situacao_atencao


class ClassificacaoMensagemErroTests(SimpleTestCase):

    def test_provedor_indisponivel_e_atencao(self):
        self.assertTrue(_e_situacao_atencao(_PROVIDER_TEMPORARIAMENTE_INDISPONIVEL))

    def test_sobrecarregado_e_atencao(self):
        self.assertTrue(
            _e_situacao_atencao("O servico esta SOBRECARREGADO no momento.")
        )

    def test_erro_tecnico_generico_nao_e_atencao(self):
        self.assertFalse(
            _e_situacao_atencao("Ocorreu um erro tecnico ao executar o agente.")
        )
