"""
DB-A1: testes de `Processamento.recalcular_totais`.

Verifica que o helper mapeia o resultado do aggregate (uma unica query) para os
dois campos fisicos, mantendo-os sempre coerentes entre si.
"""

from unittest.mock import patch

from django.test import SimpleTestCase

from apps.processamentos.models import Processamento


class RecalcularTotaisTests(SimpleTestCase):

    def _recalcular_com(self, total, processados):
        proc = Processamento()
        proc.total_documentos = 999  # valor sujo proposital
        proc.total_processados = 999
        with patch.object(Processamento, "documentos") as docs:
            docs.aggregate.return_value = {
                "total": total,
                "processados": processados,
            }
            proc.recalcular_totais()
        return proc

    def test_define_ambos_os_campos(self):
        proc = self._recalcular_com(total=5, processados=3)
        self.assertEqual(proc.total_documentos, 5)
        self.assertEqual(proc.total_processados, 3)

    def test_zera_quando_sem_documentos(self):
        proc = self._recalcular_com(total=0, processados=0)
        self.assertEqual(proc.total_documentos, 0)
        self.assertEqual(proc.total_processados, 0)

    def test_usa_uma_unica_query_agregada(self):
        proc = Processamento()
        with patch.object(Processamento, "documentos") as docs:
            docs.aggregate.return_value = {"total": 2, "processados": 1}
            proc.recalcular_totais()
            docs.aggregate.assert_called_once()
