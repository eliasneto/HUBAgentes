"""
Tamanho do chunk de upload em pedacos pra pastas locais (settings.
LOCAL_UPLOAD_CHUNK_SIZE_KB), repassado pra tela de arquivos da integracao
(local_storage_arquivos.html) via contexto, em vez de fixo em 7 KB no JS.

O padrao (7) e o valor testado em producao atras do proxy NPM/OpenResty
(ver comentario no template) — continua o mesmo a menos que alguem
configure LOCAL_UPLOAD_CHUNK_SIZE_KB no .env. Em ambiente local, sem esse
proxy na frente, pode subir bastante pra upload mais rapido.
"""

import tempfile

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.integracoes.models import IntegrationStatus, LocalStorageIntegration


class UploadChunkSizeContextTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-upload-chunk", password="x", email="a@a.com"
        )
        self.client.force_login(self.admin)
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.integracao = LocalStorageIntegration.objects.create(
            nome="Pasta Chunk",
            base_path=self._tmpdir.name,
            status=IntegrationStatus.ATIVA,
        )

    @override_settings(LOCAL_UPLOAD_CHUNK_SIZE_KB=7)
    def test_usa_o_padrao_de_producao_quando_nao_configurado(self):
        # override_settings explicito (nao confia no .env do ambiente que
        # roda o teste) — o padrao real vem de config(..., default=7) em
        # settings.py quando LOCAL_UPLOAD_CHUNK_SIZE_KB nao esta no .env.
        resp = self.client.get(
            reverse("portal_local_arquivos", args=[self.integracao.id])
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["upload_chunk_size_kb"], 7)
        self.assertContains(resp, "const CHUNK_SIZE = 7 * 1024;")

    @override_settings(LOCAL_UPLOAD_CHUNK_SIZE_KB=4096)
    def test_respeita_override_configurado_via_settings(self):
        resp = self.client.get(
            reverse("portal_local_arquivos", args=[self.integracao.id])
        )

        self.assertEqual(resp.context["upload_chunk_size_kb"], 4096)
        self.assertContains(resp, "const CHUNK_SIZE = 4096 * 1024;")
