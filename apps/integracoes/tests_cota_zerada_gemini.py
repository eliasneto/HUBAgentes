"""
Deteccao de cota ZERADA (HTTP 429 com "RESOURCE_EXHAUSTED" + "limit: 0" no
corpo) na Gemini — ver GeminiProviderAdapter._eh_erro_cota_zerada e
BaseAIProviderAdapter._eh_erro_cota_zerada/_COTA_ZERADA_PROVEDOR.

Descoberto em producao (30/08/2026): 31 das 36 falhas do provedor Gemini nos
ultimos 30 dias eram um 429 "You exceeded your current quota" com
"limit: 0" no corpo — a chave de API nao tem NENHUMA cota liberada pro
modelo (projeto sem billing habilitado), nao um rate limit comum (limite >
0, so estourado no minuto/dia) que se resolve sozinho com espera. Antes
desta mudanca, esse caso caia no mesmo fluxo de "provedor temporariamente
indisponivel" (5 retentativas + mensagem generica de "tente novamente"),
escondendo a causa real e incentivando reexecucoes inuteis.
"""

import io
from unittest.mock import MagicMock, patch
from urllib import error

from django.test import SimpleTestCase

from apps.integracoes.services.ai_providers.base import (
    AIProviderServiceError,
    BaseAIProviderAdapter,
)
from apps.integracoes.services.ai_providers.gemini_adapter import GeminiProviderAdapter

# Corpo real (truncado) devolvido pela Gemini para cota zerada. A ordem dos
# campos importa para o teste: "limit: 0" aparece dentro de "message", ANTES
# do campo "status" (que so depois traz "RESOURCE_EXHAUSTED") — cobre a
# armadilha de um regex que exigisse "resource_exhausted" antes de
# "limit: 0" no texto (essa ordem nunca acontece na resposta real).
CORPO_COTA_ZERADA = """{
  "error": {
    "code": 429,
    "message": "You exceeded your current quota, please check your plan and billing details. \\n* Quota exceeded for metric: generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 0, model: gemini-2.0-flash\\nPlease retry in 780.475732ms.",
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "0s"}
    ]
  }
}"""

CORPO_RATE_LIMIT_COMUM = """{
  "error": {
    "code": 429,
    "message": "Quota exceeded for metric: generativelanguage.googleapis.com/generate_requests_per_minute, limit: 15, model: gemini-2.5-flash",
    "status": "RESOURCE_EXHAUSTED"
  }
}"""


class GeminiEhErroCotaZeradaTests(SimpleTestCase):
    def setUp(self):
        self.adapter = GeminiProviderAdapter(None)

    def test_detecta_cota_zerada_mesmo_com_status_depois_da_mensagem(self):
        self.assertTrue(self.adapter._eh_erro_cota_zerada(429, CORPO_COTA_ZERADA))

    def test_rate_limit_comum_com_limite_maior_que_zero_nao_e_cota_zerada(self):
        self.assertFalse(self.adapter._eh_erro_cota_zerada(429, CORPO_RATE_LIMIT_COMUM))

    def test_ignora_codigo_diferente_de_429(self):
        self.assertFalse(self.adapter._eh_erro_cota_zerada(503, CORPO_COTA_ZERADA))

    def test_corpo_vazio_ou_none_nao_e_cota_zerada(self):
        self.assertFalse(self.adapter._eh_erro_cota_zerada(429, ""))
        self.assertFalse(self.adapter._eh_erro_cota_zerada(429, None))

    def test_case_insensitive(self):
        self.assertTrue(
            self.adapter._eh_erro_cota_zerada(429, CORPO_COTA_ZERADA.upper())
        )


class BaseAdapterCotaZeradaPadraoTests(SimpleTestCase):
    """Provedores sem deteccao especifica (hoje: OpenAI, Anthropic, Groq)
    usam o hook generico da base, que e sempre False — 429 continua tratado
    como rate limit comum (retry normal), nunca como cota zerada."""

    def test_hook_generico_da_base_e_sempre_false(self):
        adapter = BaseAIProviderAdapter(MagicMock())
        self.assertFalse(adapter._eh_erro_cota_zerada(429, CORPO_COTA_ZERADA))


def _http_error_429(body):
    return error.HTTPError(
        "https://exemplo/url",
        429,
        "Too Many Requests",
        {},
        io.BytesIO(body.encode("utf-8")),
    )


class PostJsonRequestCotaZeradaTests(SimpleTestCase):
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
            http_error_prefix="Falha HTTP {code} ao executar o agente no provedor: {body}",
            connection_error_prefix="Falha de conexao: {reason}",
            invalid_json_message="resposta invalida",
        )

    @patch("apps.integracoes.services.ai_providers.base.time.sleep")
    @patch("apps.integracoes.services.ai_providers.base.request.urlopen")
    def test_cota_zerada_falha_na_hora_sem_retentar(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = _http_error_429(CORPO_COTA_ZERADA)

        with self.assertRaises(AIProviderServiceError) as ctx:
            self._post()

        self.assertIn("nao tem cota liberada", str(ctx.exception))
        self.assertFalse(ctx.exception.retryable)
        self.assertIn("RESOURCE_EXHAUSTED", ctx.exception.technical_message)
        # Nao gasta nenhuma das 5 retentativas normais: falha na 1a tentativa.
        self.assertEqual(mock_urlopen.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("apps.integracoes.services.ai_providers.base.time.sleep")
    @patch("apps.integracoes.services.ai_providers.base.request.urlopen")
    def test_rate_limit_comum_continua_retentando_como_antes(self, mock_urlopen, mock_sleep):
        resposta_ok = MagicMock()
        resposta_ok.read.return_value = b'{"ok": true}'
        resposta_ok.__enter__.return_value = resposta_ok

        mock_urlopen.side_effect = [
            _http_error_429(CORPO_RATE_LIMIT_COMUM),
            resposta_ok,
        ]

        payload, _ = self._post()

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(mock_urlopen.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("apps.integracoes.services.ai_providers.base.time.sleep")
    @patch("apps.integracoes.services.ai_providers.base.request.urlopen")
    def test_rate_limit_comum_persistente_ainda_usa_mensagem_generica(
        self, mock_urlopen, mock_sleep
    ):
        # Esgotando as retentativas de um rate limit comum (limite > 0), a
        # mensagem amigavel continua sendo a generica de "tente novamente"
        # — so a cota ZERADA ganha a mensagem especifica nova.
        mock_urlopen.side_effect = _http_error_429(CORPO_RATE_LIMIT_COMUM)

        with self.assertRaises(AIProviderServiceError) as ctx:
            self._post()

        self.assertTrue(ctx.exception.retryable)
        self.assertIn("temporariamente indisponivel", str(ctx.exception))
        self.assertEqual(
            mock_urlopen.call_count, self.adapter.max_transient_retries + 1
        )
