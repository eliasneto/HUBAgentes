"""
DB-U2: testes do limite de tentativas de execucao por documento.

Cobre o ponto de decisao `_documento_excedeu_tentativas`, que governa se um
documento sera bloqueado por ter atingido `max_tentativas` execucoes.
"""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from apps.processamentos.services.agent_execution import (
    _documento_excedeu_tentativas,
)


def _proc_com_contagem(quantidade):
    """Processamento simulado cujo execucoes_ia.filter(...).count() devolve `quantidade`."""
    proc = MagicMock()
    proc.execucoes_ia.filter.return_value.count.return_value = quantidade
    return proc


class DocumentoExcedeuTentativasTests(SimpleTestCase):

    def test_abaixo_do_limite_nao_excede(self):
        proc = _proc_com_contagem(2)
        documento = MagicMock()
        self.assertFalse(_documento_excedeu_tentativas(proc, documento, 3))

    def test_igual_ao_limite_excede(self):
        proc = _proc_com_contagem(3)
        documento = MagicMock()
        self.assertTrue(_documento_excedeu_tentativas(proc, documento, 3))

    def test_acima_do_limite_excede(self):
        proc = _proc_com_contagem(5)
        documento = MagicMock()
        self.assertTrue(_documento_excedeu_tentativas(proc, documento, 3))

    def test_zero_significa_sem_limite_e_nao_consulta_banco(self):
        proc = _proc_com_contagem(999)
        documento = MagicMock()
        self.assertFalse(_documento_excedeu_tentativas(proc, documento, 0))
        # Short-circuit: nao deve nem montar a query quando o limite e 0.
        proc.execucoes_ia.filter.assert_not_called()

    def test_none_significa_sem_limite(self):
        proc = _proc_com_contagem(999)
        documento = MagicMock()
        self.assertFalse(_documento_excedeu_tentativas(proc, documento, None))
        proc.execucoes_ia.filter.assert_not_called()

    def test_conta_apenas_o_documento_especifico(self):
        proc = _proc_com_contagem(1)
        documento = MagicMock()
        _documento_excedeu_tentativas(proc, documento, 3)
        proc.execucoes_ia.filter.assert_called_once_with(documento=documento)
