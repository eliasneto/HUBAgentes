"""
Retentativa de erros de CONEXAO (nao de resposta HTTP com codigo de erro)
em BaseAIProviderAdapter._post_json_request — URLError, TimeoutError e
http.client.HTTPException (ex.: RemoteDisconnected).

Descoberto testando localmente (20/08/2026): o servidor as vezes fecha a
conexao sem devolver nenhuma resposta HTTP ("Remote end closed connection
without response" / http.client.RemoteDisconnected) — essa excecao nao e
um URLError nem um TimeoutError, entao nao caia em nenhum except da
retentativa e quebrava o lote inteiro sem nenhuma nova tentativa, mesmo
sendo uma falha tao transitoria quanto as outras duas.
"""

import http.client
from unittest.mock import MagicMock, patch
from urllib import error

from django.test import SimpleTestCase

from apps.integracoes.services.ai_providers.base import AIProviderServiceError
from apps.integracoes.services.ai_providers.gemini_adapter import GeminiProviderAdapter


class RetentativaErroConexaoTests(SimpleTestCase):
    def setUp(self):
        integration = MagicMock()
        integration.api_key = "chave-teste"
        integration.api_base_url = ""
        integration.timeout_seconds = 30
        self.adapter = GeminiProviderAdapter(integration)

    def _post(self):
        return self.adapter._post_json_request(
            "https://exemplo/url",
            {"contents": []},
            http_error_prefix="Falha HTTP {code}: {body}",
            connection_error_prefix="Falha de conexao: {reason}",
            invalid_json_message="resposta invalida",
        )

    @patch("apps.integracoes.services.ai_providers.base.time.sleep")
    @patch("apps.integracoes.services.ai_providers.base.request.urlopen")
    def test_remote_disconnected_tenta_de_novo_e_da_certo(self, mock_urlopen, mock_sleep):
        resposta_ok = MagicMock()
        resposta_ok.read.return_value = b'{"ok": true}'
        resposta_ok.__enter__.return_value = resposta_ok

        mock_urlopen.side_effect = [
            http.client.RemoteDisconnected(
                "Remote end closed connection without response"
            ),
            resposta_ok,
        ]

        payload, url = self._post()

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("apps.integracoes.services.ai_providers.base.time.sleep")
    @patch("apps.integracoes.services.ai_providers.base.request.urlopen")
    def test_remote_disconnected_persistente_esgota_tentativas_com_erro_amigavel(
        self, mock_urlopen, mock_sleep
    ):
        mock_urlopen.side_effect = http.client.RemoteDisconnected(
            "Remote end closed connection without response"
        )

        with self.assertRaises(AIProviderServiceError) as ctx:
            self._post()

        self.assertTrue(ctx.exception.retryable)
        # Esgota max_transient_retries tentativas extras (+1 tentativa inicial).
        self.assertEqual(
            mock_urlopen.call_count, self.adapter.max_transient_retries + 1
        )

    @patch("apps.integracoes.services.ai_providers.base.time.sleep")
    @patch("apps.integracoes.services.ai_providers.base.request.urlopen")
    def test_urlerror_continua_sendo_retentado_como_antes(self, mock_urlopen, mock_sleep):
        # Garante que a correcao (adicionar http.client.HTTPException ao
        # except) nao afetou o comportamento ja existente para URLError.
        resposta_ok = MagicMock()
        resposta_ok.read.return_value = b'{"ok": true}'
        resposta_ok.__enter__.return_value = resposta_ok

        mock_urlopen.side_effect = [error.URLError("dns falhou"), resposta_ok]

        payload, _ = self._post()

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(mock_urlopen.call_count, 2)
