"""
Cria agente para ler PDFs da pasta Licitacao e gerar analise consolidada.
"""
from django.core.management.base import BaseCommand
from django.utils.text import slugify


class Command(BaseCommand):
    help = "Cria agente Leitor Licitacao Local apontando para /app/entradas/Licitacao"

    def handle(self, *args, **options):
        from apps.agentes_ia.models import (
            AgentStatus, AgentTriggerMode, AgentType, AgentVisibility,
            AgentDocumentExecutionMode, AgentOutputAssemblyMode,
            AgentOutputPackagingMode, AgentInputPolicy,
            AgenteIA, AgenteConfiguracaoOperacional,
        )
        from apps.integracoes.models import (
            AIProviderIntegration, LocalStorageIntegration, IntegrationStatus,
        )
        from apps.processamentos.models import ProcessingOutputFormat

        # Integracao IA ativa
        ia = AIProviderIntegration.objects.filter(status=IntegrationStatus.ATIVA).first()
        if not ia:
            self.stderr.write("Nenhuma integracao de IA ativa.")
            return
        self.stdout.write(f"Integracao IA: {ia.nome} — {ia.default_model}")

        # Integracao local ativa
        local = LocalStorageIntegration.objects.filter(status=IntegrationStatus.ATIVA).first()
        if not local:
            self.stderr.write("Nenhuma integracao local ativa. Cadastre uma em Integracoes.")
            return
        self.stdout.write(f"Integracao local: {local.nome} -> {local.base_path}")

        nome = "Leitor Licitacao Local"
        slug = slugify(nome)

        prompt = (
            "Analise o documento de licitacao recebido e extraia as informacoes mais "
            "relevantes. Retorne um JSON com os campos: "
            "objeto (string), modalidade (string), valor_estimado (string), "
            "prazo_entrega (string), criterio_julgamento (string), "
            "requisitos_habilitacao (lista de strings), "
            "resumo (string com um paragrafo resumindo o edital)."
        )

        agente, criado = AgenteIA.objects.get_or_create(
            slug=slug,
            defaults={
                "nome": nome,
                "tipo": AgentType.EXTRATOR,
                "visibilidade": AgentVisibility.USUARIO,
                "modo_acionamento": AgentTriggerMode.PORTAL,
                "status": AgentStatus.ATIVO,
                "ai_provider_integration": ia,
                "modelo_preferencial": ia.default_model,
                "objetivo": (
                    "Le todos os PDFs da pasta Licitacao de uma vez (grupo unico), "
                    "analisa e gera um unico JSON consolidado com os dados extraidos."
                ),
                "prompt_base": prompt,
            },
        )

        if not criado:
            agente.status = AgentStatus.ATIVO
            agente.ai_provider_integration = ia
            agente.save()

        config, _ = AgenteConfiguracaoOperacional.objects.get_or_create(agente=agente)
        config.document_execution_mode             = AgentDocumentExecutionMode.GRUPO_UNICO
        config.output_assembly_mode                = AgentOutputAssemblyMode.UMA_SAIDA_FINAL
        config.output_packaging_mode               = AgentOutputPackagingMode.ARQUIVO_UNICO
        config.default_output_format               = ProcessingOutputFormat.JSON
        config.input_policy                        = AgentInputPolicy.FIXA
        config.default_local_storage_integration   = local
        config.default_local_relative_input_path   = "Licitacao"
        config.save()

        self.stdout.write(self.style.SUCCESS(
            f"\nAgente {'CRIADO' if criado else 'ATUALIZADO'}: {agente.nome}"
        ))
        self.stdout.write(f"  Pasta lida : {local.base_path}/Licitacao")
        self.stdout.write(f"  PDFs la    : 3 arquivos encontrados")
        self.stdout.write(f"  Modo       : grupo_unico + uma_saida_final")
        self.stdout.write(f"  Saida      : 1 arquivo JSON")
        self.stdout.write("")
        self.stdout.write("Acesse: Operacao > Agentes de Leitura > Leitor Licitacao Local")
        self.stdout.write("Clique em Executar — sem upload, le direto da pasta configurada.")
