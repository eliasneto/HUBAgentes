"""
Cria dados de teste para demonstrar o calculo de custo:
  - 1 integracao de IA (Gemini) com chave placeholder
  - 1 agente ativo usando essa integracao
  - 1 precificacao de custo para o modelo
  - 1 configuracao de cotacao do dolar

Execute com:
    python manage.py criar_dados_teste
    python manage.py criar_dados_teste --api-key SUA_CHAVE_REAL
"""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils.text import slugify


class Command(BaseCommand):
    help = "Cria integracao, agente e configuracao de custo para testes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--api-key",
            default="COLOQUE_SUA_CHAVE_AQUI",
            help="Chave de API do Gemini (Google AI Studio). Padrao: placeholder.",
        )
        parser.add_argument(
            "--modelo",
            default="gemini-2.0-flash",
            help="Nome do modelo Gemini. Padrao: gemini-2.0-flash.",
        )
        parser.add_argument(
            "--cotacao",
            default="5.80",
            help="Cotacao do dolar em reais. Padrao: 5.80.",
        )

    def handle(self, *args, **options):
        from apps.agentes_ia.models import (
            AgentStatus,
            AgentTriggerMode,
            AgentType,
            AgentVisibility,
            AgenteIA,
        )
        from apps.custos.models import ConfiguracaoFinanceira, PrecificacaoModelo
        from apps.integracoes.models import (
            AIProviderIntegration,
            AIProviderType,
            IntegrationStatus,
        )

        api_key = options["api_key"]
        modelo = options["modelo"]
        cotacao = Decimal(options["cotacao"])

        # ── 1. Integracao de IA ───────────────────────────────────────────────
        nome_integracao = "Teste Gemini"
        integracao, criada = AIProviderIntegration.objects.get_or_create(
            nome=nome_integracao,
            defaults={
                "provider_type": AIProviderType.GEMINI,
                "status": IntegrationStatus.ATIVA,
                "api_key": api_key,
                "default_model": modelo,
                "timeout_seconds": 120,
            },
        )
        if not criada:
            integracao.api_key = api_key
            integracao.default_model = modelo
            integracao.status = IntegrationStatus.ATIVA
            integracao.save()
            self.stdout.write(f"  Integracao ja existia, atualizada: {integracao.nome}")
        else:
            self.stdout.write(self.style.SUCCESS(f"  Integracao criada: {integracao.nome}"))

        # ── 2. Agente ─────────────────────────────────────────────────────────
        nome_agente = "Agente de Teste"
        slug_agente = slugify(nome_agente)

        agente, criado = AgenteIA.objects.get_or_create(
            slug=slug_agente,
            defaults={
                "nome": nome_agente,
                "tipo": AgentType.GENERICO,
                "visibilidade": AgentVisibility.USUARIO,
                "modo_acionamento": AgentTriggerMode.PORTAL,
                "status": AgentStatus.ATIVO,
                "ai_provider_integration": integracao,
                "modelo_preferencial": modelo,
                "objetivo": "Agente criado para testar o calculo de custo por processamento.",
                "prompt_base": (
                    "Voce e um assistente de teste. Leia o documento enviado e "
                    "retorne um JSON com os campos: titulo (string com o titulo principal "
                    "do documento), resumo (string de ate 3 linhas resumindo o conteudo)."
                ),
            },
        )
        if not criado:
            agente.status = AgentStatus.ATIVO
            agente.ai_provider_integration = integracao
            agente.modelo_preferencial = modelo
            agente.save()
            self.stdout.write(f"  Agente ja existia, atualizado: {agente.nome}")
        else:
            self.stdout.write(self.style.SUCCESS(f"  Agente criado: {agente.nome}"))

        # ── 3. Precificacao do modelo ─────────────────────────────────────────
        # Precos Gemini 2.0 Flash (referencia: Google AI Studio, junho/2025)
        preco_input = Decimal("0.100000")   # U$ 0,10 por 1M tokens de entrada
        preco_output = Decimal("0.400000")  # U$ 0,40 por 1M tokens de saida

        prec, criada = PrecificacaoModelo.objects.get_or_create(
            nome_modelo=modelo,
            defaults={
                "preco_input_por_milhao": preco_input,
                "preco_output_por_milhao": preco_output,
                "ativo": True,
            },
        )
        if not criada:
            self.stdout.write(f"  Precificacao ja existia para: {modelo}")
        else:
            self.stdout.write(self.style.SUCCESS(
                f"  Precificacao criada: {modelo} — "
                f"input U${preco_input} / output U${preco_output} por 1M tokens"
            ))

        # ── 4. Cotacao do dolar ───────────────────────────────────────────────
        config = ConfiguracaoFinanceira.objects.order_by("-created_at").first()
        if config:
            self.stdout.write(f"  Cotacao ja configurada: R$ {config.cotacao_dolar}")
        else:
            ConfiguracaoFinanceira.objects.create(cotacao_dolar=cotacao)
            self.stdout.write(self.style.SUCCESS(f"  Cotacao criada: R$ {cotacao}"))

        # ── Resumo ────────────────────────────────────────────────────────────
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Dados de teste prontos!"))
        self.stdout.write("")

        if api_key == "COLOQUE_SUA_CHAVE_AQUI":
            self.stdout.write(self.style.WARNING(
                "ATENCAO: A integracao foi criada com chave placeholder.\n"
                "Para rodar um processamento real, atualize a chave em:\n"
                "  Administrador > Integracoes > Teste Gemini > Editar\n\n"
                "Ou execute novamente com a chave real:\n"
                "  python manage.py criar_dados_teste --api-key SUA_CHAVE_REAL"
            ))
        else:
            self.stdout.write(
                "Proximos passos:\n"
                f"  1. Acesse Operacao > Agentes de Leitura\n"
                f"  2. Execute o agente '{nome_agente}' com um PDF de teste\n"
                f"  3. Veja o custo em Administrador > Historico e Auditoria"
            )
