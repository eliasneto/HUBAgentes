"""
redact_url_credentials (base.py) — mascara chaves de API embutidas na URL
(?key=...) antes de qualquer log, auditoria ou exibicao. Descoberto
testando localmente (20/08/2026): a chave real do Gemini aparecia em texto
puro no log de retentativa E ficava persistida em EventoAuditoria.payload
(auditoria, visivel no Django admin) via AIProviderExecutionResult.
request_url — apesar da variavel se chamar "safe_payload".

Gemini autentica via query string (?key=...); OpenAI/Anthropic/Groq usam
header (Authorization/x-api-key), entao nunca tem credencial na URL — o
teste de "nao afeta URLs sem credencial" cobre esse caso.
"""

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from apps.integracoes.services.ai_providers.base import redact_url_credentials
from apps.integracoes.services.ai_providers.gemini_adapter import GeminiProviderAdapter


class RedactUrlCredentialsTests(SimpleTestCase):
    def test_mascara_key_do_gemini(self):
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key=AQ.Ab8SEGREDO123"
        self.assertEqual(
            redact_url_credentials(url),
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash:generateContent?key=***",
        )

    def test_mascara_no_meio_de_outros_parametros(self):
        url = "https://exemplo/api?foo=bar&key=SEGREDO&baz=qux"
        resultado = redact_url_credentials(url)
        self.assertIn("foo=bar", resultado)
        self.assertIn("baz=qux", resultado)
        self.assertIn("key=***", resultado)
        self.assertNotIn("SEGREDO", resultado)

    def test_url_sem_credencial_fica_inalterada(self):
        # Caso de OpenAI/Anthropic/Groq: autenticam via header, nunca tem
        # credencial na URL - a funcao nao deve alterar nada nesses casos.
        url = "https://api.openai.com/v1/chat/completions"
        self.assertEqual(redact_url_credentials(url), url)

    def test_url_vazia_ou_none_nao_quebra(self):
        self.assertEqual(redact_url_credentials(""), "")
        self.assertIsNone(redact_url_credentials(None))


class GeminiAdapterNaoExpoeChaveNoResultadoTests(SimpleTestCase):
    """AIProviderExecutionResult.request_url e persistido em
    EventoAuditoria.payload (auditoria/Django admin) — nunca pode conter a
    chave real."""

    def setUp(self):
        integration = MagicMock()
        integration.api_key = "CHAVE-SUPER-SECRETA"
        integration.api_base_url = ""
        integration.default_model = "gemini-3.5-flash"
        integration.timeout_seconds = 30
        self.adapter = GeminiProviderAdapter(integration)

    @patch.object(GeminiProviderAdapter, "_post_json")
    def test_execute_prompt_with_document_nao_expoe_chave(self, mock_post_json):
        mock_post_json.return_value = {"candidates": [], "usageMetadata": {}}

        resultado = self.adapter.execute_prompt_with_document(
            prompt="pergunta",
            document_bytes=b"pdf",
            document_mime_type="application/pdf",
            document_name="doc.pdf",
            execution_params={},
            model_name="gemini-3.5-flash",
        )

        self.assertNotIn("CHAVE-SUPER-SECRETA", resultado.request_url)
        self.assertIn("key=***", resultado.request_url)
        # A chamada real (mock_post_json) ainda recebe a URL com a chave
        # verdadeira - so o resultado exposto/persistido e que e mascarado.
        url_chamada_real = mock_post_json.call_args.args[0]
        self.assertIn("CHAVE-SUPER-SECRETA", url_chamada_real)
