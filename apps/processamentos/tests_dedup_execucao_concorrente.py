"""
Dedup de "arquivo ja processado em outra execucao" (ver document_sources.
_arquivo_ja_processado_em_outra_execucao) durante o loop de retentativa por
sobrecarga do provedor de IA (ver tests_retentativa_sobrecarga_provedor.py).

Ate a 1.5.25, um documento parado nesse loop (status=ERRO,
erro_reprocessavel=True, tentativas_pontuais=0 — o loop de sobrecarga nunca
toca esse contador, so o mecanismo de erro pontual entre rodadas da rotina
automatica o faz) nao era reconhecido pelo dedup: um segundo clique manual
ou uma nova rodada da rotina automatica, na mesma pasta, enquanto o loop
ainda estava esperando, recriava o arquivo do zero e chamava a IA de novo
em paralelo — duplicando custo e podendo gerar duas saidas "processadas"
para o mesmo arquivo fisico.

Caso identificado revisando o teto do loop de sobrecarga (LIMITE_
RETENTATIVA_SOBRECARGA, reduzido de 2h para 45min na mesma versao): quanto
maior o teto, maior a janela de exposicao a essa duplicacao.
"""

from django.contrib.auth.models import User
from django.test import TestCase

from apps.agentes_ia.models import AgenteIA, AgentType, AgentStatus
from apps.integracoes.models import AIProviderIntegration, IntegrationStatus
from apps.processamentos.models import (
    DocumentoEntrada,
    DocumentStatus,
    Processamento,
    ProcessingInputSourceType,
)
from apps.processamentos.services.document_sources import (
    _arquivo_local_ja_processado_anteriormente,
)


class ArquivoJaProcessadoDuranteLoopDeSobrecargaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dono-dedup", password="x")
        self.ai_integration = AIProviderIntegration.objects.create(
            nome="Integracao Dedup",
            api_key="chave-teste",
            status=IntegrationStatus.ATIVA,
            default_model="modelo-teste",
        )
        self.agente = AgenteIA.objects.create(
            nome="Agente Dedup",
            slug="agente-dedup",
            tipo=AgentType.GENERICO,
            ai_provider_integration=self.ai_integration,
            status=AgentStatus.ATIVO,
            prompt_base="prompt",
        )

    def _processamento(self, sufixo, *, retentativa_sobrecarga_ativa=False):
        return Processamento.objects.create(
            codigo=f"PROC-DEDUP-{sufixo}",
            iniciado_por=self.user,
            agente=self.agente,
            input_source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            local_relative_input_path="",
            retentativa_sobrecarga_ativa=retentativa_sobrecarga_ativa,
        )

    def _documento_em_erro(self, processamento, nome, *, erro_reprocessavel, tentativas_pontuais=0):
        return DocumentoEntrada.objects.create(
            processamento=processamento,
            nome_arquivo=nome,
            source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            source_reference=nome,
            status=DocumentStatus.ERRO,
            erro_reprocessavel=erro_reprocessavel,
            tentativas_pontuais=tentativas_pontuais,
        )

    def test_arquivo_em_loop_de_sobrecarga_ativo_em_outra_execucao_nao_e_recriado(self):
        # rodada_1 ainda esta com o loop de retentativa por sobrecarga ligado
        # (Processamento.retentativa_sobrecarga_ativa=True) — o documento
        # esta so "esperando", nao definitivamente com erro.
        rodada_1 = self._processamento("1", retentativa_sobrecarga_ativa=True)
        self._documento_em_erro(rodada_1, "edital.pdf", erro_reprocessavel=True)
        nova_rodada = self._processamento("2")

        ja_tratado = _arquivo_local_ja_processado_anteriormente(nova_rodada, "edital.pdf")

        self.assertTrue(ja_tratado)

    def test_arquivo_com_loop_de_sobrecarga_ja_encerrado_pode_ser_recriado(self):
        # Loop ja desligou (sucesso, desistencia apos o teto, ou 2a falha
        # consecutiva do erro pontual) — erro transitorio comum, sem
        # retentativa em andamento em nenhum lugar: comportamento de sempre
        # (reprocessa_seletivo) continua valendo, sem ficar preso para
        # sempre so por ter passado pelo loop uma vez.
        rodada_1 = self._processamento("1", retentativa_sobrecarga_ativa=False)
        self._documento_em_erro(rodada_1, "edital.pdf", erro_reprocessavel=True)
        nova_rodada = self._processamento("2")

        ja_tratado = _arquivo_local_ja_processado_anteriormente(nova_rodada, "edital.pdf")

        self.assertFalse(ja_tratado)

    def test_erro_definitivo_nao_reprocessavel_continua_sem_ser_pego_por_este_ramo(self):
        # erro_reprocessavel=False (credenciais, formato nao suportado etc.)
        # nunca passou pelo loop de sobrecarga — este ramo novo nao deve
        # afetar esse caso preexistente (fora do escopo desta correcao).
        rodada_1 = self._processamento("1", retentativa_sobrecarga_ativa=True)
        self._documento_em_erro(rodada_1, "edital.pdf", erro_reprocessavel=False)
        nova_rodada = self._processamento("2")

        ja_tratado = _arquivo_local_ja_processado_anteriormente(nova_rodada, "edital.pdf")

        self.assertFalse(ja_tratado)

    def test_forcar_reprocessamento_ignora_mesmo_com_loop_ativo(self):
        rodada_1 = self._processamento("1", retentativa_sobrecarga_ativa=True)
        self._documento_em_erro(rodada_1, "edital.pdf", erro_reprocessavel=True)
        nova_rodada = self._processamento("2")
        nova_rodada.forcar_reprocessamento = True

        ja_tratado = _arquivo_local_ja_processado_anteriormente(nova_rodada, "edital.pdf")

        self.assertFalse(ja_tratado)

    def test_documento_processado_com_sucesso_continua_sendo_pulado(self):
        # Regressao: garante que o ramo pre-existente (PROCESSADO) nao foi
        # afetado pela adicao do novo ramo de sobrecarga.
        rodada_1 = self._processamento("1")
        documento = self._documento_em_erro(rodada_1, "edital.pdf", erro_reprocessavel=True)
        documento.status = DocumentStatus.PROCESSADO
        documento.save(update_fields=["status"])
        nova_rodada = self._processamento("2")

        ja_tratado = _arquivo_local_ja_processado_anteriormente(nova_rodada, "edital.pdf")

        self.assertTrue(ja_tratado)
