"""
Tela "Documentos Processados": 1 linha por NOME de documento (identidade
do documento — mesma regra ja aplicada na descoberta de arquivos, ver
document_sources._arquivo_ja_processado_em_outra_execucao: o nome e a
chave, nao o conteudo; documento concluido com sucesso nao e reprocessado
com o MESMO nome, so muda de nome). N Processamentos podem ter um
DocumentoEntrada com o mesmo nome — esta tela agrega isso e permite ver
os Processamentos filtrados (reaproveita ?codigos= de ProcessamentosView).
"""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.agentes_ia.models import AgenteIA, AgentStatus, AgentType
from apps.integracoes.models import AIProviderIntegration, IntegrationStatus
from apps.processamentos.models import (
    DocumentoEntrada,
    DocumentStatus,
    Processamento,
    ProcessingInputSourceType,
)
from apps.processamentos.selectors import listar_documentos_processados_para_portal


class ListarDocumentosProcessadosParaPortalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono-docproc", password="x")
        self.integracao = AIProviderIntegration.objects.create(
            nome="Integracao DocProc",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-teste",
        )
        self.agente_a = AgenteIA.objects.create(
            nome="Agente A",
            slug="agente-a-docproc",
            tipo=AgentType.GENERICO,
            ai_provider_integration=self.integracao,
            status=AgentStatus.ATIVO,
            prompt_base="prompt",
        )
        self.agente_b = AgenteIA.objects.create(
            nome="Agente B",
            slug="agente-b-docproc",
            tipo=AgentType.GENERICO,
            ai_provider_integration=self.integracao,
            status=AgentStatus.ATIVO,
            prompt_base="prompt",
        )

    def _processamento(self, codigo, agente, *, iniciado_em=None):
        return Processamento.objects.create(
            codigo=codigo,
            iniciado_por=self.user,
            agente=agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            iniciado_em=iniciado_em or timezone.now(),
        )

    def test_agrupa_por_nome_contando_processamentos_distintos(self):
        # Mesmo nome em 2 Processamentos diferentes -> 1 linha, total=2.
        p1 = self._processamento("PROC-DOCPROC-1", self.agente_a)
        p2 = self._processamento("PROC-DOCPROC-2", self.agente_a)
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="edital.pdf", status=DocumentStatus.ERRO
        )
        DocumentoEntrada.objects.create(
            processamento=p2, nome_arquivo="edital.pdf", status=DocumentStatus.ERRO
        )

        resultado = listar_documentos_processados_para_portal()

        self.assertEqual(resultado.total, 1)
        linha = resultado.documentos[0]
        self.assertEqual(linha.nome_arquivo, "edital.pdf")
        self.assertEqual(linha.total_processamentos, 2)

    def test_nomes_diferentes_viram_linhas_separadas(self):
        p1 = self._processamento("PROC-DOCPROC-3", self.agente_a)
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="a.pdf", status=DocumentStatus.PENDENTE
        )
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="b.pdf", status=DocumentStatus.PENDENTE
        )

        resultado = listar_documentos_processados_para_portal()

        self.assertEqual(resultado.total, 2)
        nomes = {d.nome_arquivo for d in resultado.documentos}
        self.assertEqual(nomes, {"a.pdf", "b.pdf"})

    def test_documento_ja_processado_com_sucesso_fica_bloqueado(self):
        p1 = self._processamento("PROC-DOCPROC-4", self.agente_a)
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="contrato.pdf", status=DocumentStatus.PROCESSADO
        )

        resultado = listar_documentos_processados_para_portal()

        self.assertFalse(resultado.documentos[0].pode_reprocessar)

    def test_sucesso_em_qualquer_tentativa_bloqueia_mesmo_com_erros_antes(self):
        # 1a tentativa (Processamento antigo) deu erro, 2a (novo) deu certo
        # — o documento (pelo nome) fica bloqueado, refletindo a regra real.
        p1 = self._processamento("PROC-DOCPROC-5", self.agente_a)
        p2 = self._processamento("PROC-DOCPROC-6", self.agente_a)
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="ata.pdf", status=DocumentStatus.ERRO
        )
        DocumentoEntrada.objects.create(
            processamento=p2, nome_arquivo="ata.pdf", status=DocumentStatus.PROCESSADO
        )

        resultado = listar_documentos_processados_para_portal()

        self.assertFalse(resultado.documentos[0].pode_reprocessar)

    def test_documento_sem_nenhum_sucesso_pode_ser_reprocessado(self):
        p1 = self._processamento("PROC-DOCPROC-7", self.agente_a)
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="rascunho.pdf", status=DocumentStatus.ERRO
        )

        resultado = listar_documentos_processados_para_portal()

        self.assertTrue(resultado.documentos[0].pode_reprocessar)

    def test_ver_processamentos_url_lista_todos_os_codigos_distintos(self):
        p1 = self._processamento("PROC-DOCPROC-8", self.agente_a)
        p2 = self._processamento("PROC-DOCPROC-9", self.agente_a)
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="minuta.pdf", status=DocumentStatus.ERRO
        )
        DocumentoEntrada.objects.create(
            processamento=p2, nome_arquivo="minuta.pdf", status=DocumentStatus.PROCESSADO
        )

        resultado = listar_documentos_processados_para_portal()
        url = resultado.documentos[0].ver_processamentos_url

        self.assertTrue(url.startswith(reverse("portal_processamentos") + "?codigos="))
        codigos_na_url = url.split("?codigos=")[1].split(",")
        self.assertEqual(set(codigos_na_url), {"PROC-DOCPROC-8", "PROC-DOCPROC-9"})

    def test_agentes_envolvidos_aparecem_juntos_no_mesmo_nome(self):
        # Mesmo nome de arquivo usado por 2 agentes diferentes — a tela
        # mostra os dois (identidade e so pelo nome, ver docstring do
        # selector: aproximacao global, de proposito mais simples).
        p1 = self._processamento("PROC-DOCPROC-10", self.agente_a)
        p2 = self._processamento("PROC-DOCPROC-11", self.agente_b)
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="compartilhado.pdf", status=DocumentStatus.ERRO
        )
        DocumentoEntrada.objects.create(
            processamento=p2, nome_arquivo="compartilhado.pdf", status=DocumentStatus.ERRO
        )

        resultado = listar_documentos_processados_para_portal()

        self.assertIn("Agente A", resultado.documentos[0].agentes)
        self.assertIn("Agente B", resultado.documentos[0].agentes)

    def test_filtro_busca_por_nome(self):
        p1 = self._processamento("PROC-DOCPROC-12", self.agente_a)
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="relatorio-financeiro.pdf", status=DocumentStatus.ERRO
        )
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="outro-documento.pdf", status=DocumentStatus.ERRO
        )

        resultado = listar_documentos_processados_para_portal(filtro_busca="financeiro")

        self.assertEqual(resultado.total, 1)
        self.assertEqual(resultado.documentos[0].nome_arquivo, "relatorio-financeiro.pdf")

    def test_filtro_por_agente(self):
        p1 = self._processamento("PROC-DOCPROC-13", self.agente_a)
        p2 = self._processamento("PROC-DOCPROC-14", self.agente_b)
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="do-agente-a.pdf", status=DocumentStatus.ERRO
        )
        DocumentoEntrada.objects.create(
            processamento=p2, nome_arquivo="do-agente-b.pdf", status=DocumentStatus.ERRO
        )

        resultado = listar_documentos_processados_para_portal(filtro_agente=str(self.agente_a.pk))

        self.assertEqual(resultado.total, 1)
        self.assertEqual(resultado.documentos[0].nome_arquivo, "do-agente-a.pdf")

    def test_agentes_disponiveis_lista_distinta_ordenada(self):
        p1 = self._processamento("PROC-DOCPROC-15", self.agente_b)
        p2 = self._processamento("PROC-DOCPROC-16", self.agente_a)
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="x.pdf", status=DocumentStatus.ERRO
        )
        DocumentoEntrada.objects.create(
            processamento=p2, nome_arquivo="y.pdf", status=DocumentStatus.ERRO
        )

        resultado = listar_documentos_processados_para_portal()

        nomes = [nome for _id, nome in resultado.agentes_disponiveis]
        self.assertEqual(nomes, ["Agente A", "Agente B"])

    def test_documento_sem_nenhum_documentoentrada_nao_aparece(self):
        # Sanidade: nome vazio (registro degenerado) e excluido.
        p1 = self._processamento("PROC-DOCPROC-17", self.agente_a)
        DocumentoEntrada.objects.create(
            processamento=p1, nome_arquivo="", status=DocumentStatus.ERRO
        )

        resultado = listar_documentos_processados_para_portal()

        self.assertEqual(resultado.total, 0)

    def test_paginacao_respeita_per_page(self):
        for i in range(3):
            p = self._processamento(f"PROC-DOCPROC-PAG-{i}", self.agente_a)
            DocumentoEntrada.objects.create(
                processamento=p, nome_arquivo=f"doc-{i}.pdf", status=DocumentStatus.ERRO
            )

        resultado = listar_documentos_processados_para_portal(per_page=2, page_number=1)

        self.assertEqual(resultado.total, 3)
        self.assertEqual(len(resultado.documentos), 2)
        self.assertEqual(resultado.total_paginas, 2)
        self.assertTrue(resultado.tem_proxima_pagina)


class DocumentosProcessadosViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="usuario-docproc-view", password="x", is_superuser=True
        )

    def test_pagina_carrega_para_usuario_logado(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("portal_documentos_processados"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Documentos Processados")

    def test_redireciona_para_login_se_nao_autenticado(self):
        resp = self.client.get(reverse("portal_documentos_processados"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("portal_login"), resp.url)
