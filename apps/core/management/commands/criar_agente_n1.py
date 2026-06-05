"""
Cria o agente consolidador N→1: recebe vários PDFs e gera 1 arquivo de saída.

Execute com:
    python manage.py criar_agente_n1
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify


PROMPT = """Você receberá múltiplos documentos PDF para análise.

IMPORTANTE: Leia TODOS os documentos antes de responder. Sua resposta deve ser
uma análise CONSOLIDADA e ÚNICA cobrindo todos os documentos recebidos.

Produza um relatório de análise no seguinte formato JSON:

{
  "titulo": "Análise Consolidada de Documentos",
  "total_documentos_analisados": 0,
  "resumo_geral": "parágrafo resumindo os principais pontos de TODOS os documentos",
  "documentos": [
    {
      "nome": "nome ou identificação do documento",
      "principais_pontos": ["ponto 1", "ponto 2"],
      "observacoes": "observações relevantes"
    }
  ],
  "conclusao": "conclusão final integrando os achados de todos os documentos",
  "pontos_comuns": ["tema ou assunto que aparece em mais de um documento"],
  "diferenciais": ["aspecto único de cada documento, se houver"]
}

Responda APENAS com o JSON válido, sem texto adicional antes ou depois."""


class Command(BaseCommand):
    help = "Cria o agente consolidador N para 1."

    def handle(self, *args, **options):
        from apps.agentes_ia.models import (
            AgentStatus, AgentTriggerMode, AgentType, AgentVisibility,
            AgentDocumentExecutionMode, AgentOutputAssemblyMode,
            AgentOutputPackagingMode, AgenteIA, AgenteConfiguracaoOperacional,
        )
        from apps.integracoes.models import AIProviderIntegration, IntegrationStatus
        from apps.processamentos.models import ProcessingOutputFormat

        integracao = AIProviderIntegration.objects.filter(
            status=IntegrationStatus.ATIVA
        ).first()

        if not integracao:
            self.stderr.write("Nenhuma integração de IA ativa encontrada.")
            return

        self.stdout.write(f"Usando integração: {integracao.nome} — {integracao.default_model}")

        nome = "Analisador Consolidado N-para-1"
        slug = slugify(nome)

        agente, criado = AgenteIA.objects.get_or_create(
            slug=slug,
            defaults={
                "nome": nome,
                "tipo": AgentType.EXTRATOR,
                "visibilidade": AgentVisibility.USUARIO,
                "modo_acionamento": AgentTriggerMode.PORTAL,
                "status": AgentStatus.ATIVO,
                "ai_provider_integration": integracao,
                "modelo_preferencial": integracao.default_model,
                "objetivo": (
                    "Recebe múltiplos PDFs, analisa todos de uma vez em uma única "
                    "chamada à IA e gera um único relatório JSON consolidado."
                ),
                "prompt_base": PROMPT,
            },
        )

        if not criado:
            agente.prompt_base = PROMPT
            agente.status = AgentStatus.ATIVO
            agente.save()

        config, _ = AgenteConfiguracaoOperacional.objects.get_or_create(agente=agente)
        config.document_execution_mode = AgentDocumentExecutionMode.GRUPO_UNICO
        config.output_assembly_mode    = AgentOutputAssemblyMode.UMA_SAIDA_FINAL
        config.output_packaging_mode   = AgentOutputPackagingMode.ARQUIVO_UNICO
        config.default_output_format   = ProcessingOutputFormat.JSON
        config.input_policy            = "upload_na_execucao"
        config.save()

        status_txt = "CRIADO" if criado else "ATUALIZADO"
        self.stdout.write(self.style.SUCCESS(f"\nAgente {status_txt}: {agente.nome}"))
        self.stdout.write(f"  Modo de entrada : {config.document_execution_mode} (todos os PDFs em 1 chamada)")
        self.stdout.write(f"  Modo de saída   : {config.output_assembly_mode} (1 arquivo de saída)")
        self.stdout.write(f"  Empacotamento   : {config.output_packaging_mode} (sem ZIP)")
        self.stdout.write(f"  Formato         : {config.default_output_format}")
        self.stdout.write(f"  Entrada         : upload na execução")
        self.stdout.write("")
        self.stdout.write("Acesse: Operação → Agentes de Leitura → Analisador Consolidado N-para-1")
        self.stdout.write("Faça upload de até 4 PDFs ao executar — o sistema envia todos juntos à IA.")
