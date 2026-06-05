"""
Cria dados fictícios variados para testar os dashboards do painel inicial.
Cria integracoes, agentes e processamentos com tokens/custos simulados.

Execute com:
    python manage.py criar_dados_dashboard
"""
from decimal import Decimal
import random
import time
from secrets import token_hex
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify


class Command(BaseCommand):
    help = "Cria dados fictícios para visualização dos dashboards."

    def handle(self, *args, **options):
        from apps.agentes_ia.models import (
            AgentStatus, AgentTriggerMode, AgentType, AgentVisibility, AgenteIA,
        )
        from apps.integracoes.models import (
            AIProviderIntegration, AIProviderType, IntegrationStatus,
        )
        from apps.processamentos.models import (
            Processamento, ProcessingStatus, ProcessingInputSourceType,
            ProcessingOutputFormat,
        )
        from apps.custos.models import PrecificacaoModelo, ConfiguracaoFinanceira
        from django.contrib.auth import get_user_model
        User = get_user_model()

        admin = User.objects.filter(is_superuser=True).first()

        # ── Integracoes ───────────────────────────────────────────
        integracoes_dados = [
            ("Gemini Flash Prod",   AIProviderType.GEMINI,    "gemini-2.0-flash"),
            ("Gemini Pro",          AIProviderType.GEMINI,    "gemini-1.5-pro"),
            ("OpenAI GPT-4o",       AIProviderType.OPENAI,    "gpt-4o-mini"),
        ]

        integracoes = {}
        for nome, provedor, modelo in integracoes_dados:
            obj, criada = AIProviderIntegration.objects.get_or_create(
                nome=nome,
                defaults={
                    "provider_type": provedor,
                    "status": IntegrationStatus.ATIVA,
                    "api_key": "CHAVE-FICTICIA-DASHBOARD",
                    "default_model": modelo,
                    "timeout_seconds": 120,
                },
            )
            integracoes[nome] = obj
            status = "criada" if criada else "já existe"
            self.stdout.write(f"  Integração {status}: {nome}")

        # ── Precificacoes ─────────────────────────────────────────
        precos = {
            "gemini-2.0-flash": (Decimal("0.10"), Decimal("0.40")),
            "gemini-1.5-pro":   (Decimal("1.25"), Decimal("5.00")),
            "gpt-4o-mini":      (Decimal("0.15"), Decimal("0.60")),
        }
        for modelo, (inp, out) in precos.items():
            PrecificacaoModelo.objects.get_or_create(
                nome_modelo=modelo,
                defaults={"preco_input_por_milhao": inp, "preco_output_por_milhao": out, "ativo": True},
            )

        if not ConfiguracaoFinanceira.objects.exists():
            ConfiguracaoFinanceira.objects.create(cotacao_dolar=Decimal("5.80"))

        # ── Agentes ───────────────────────────────────────────────
        agentes_dados = [
            ("Leitor de Contratos",    integracoes["Gemini Flash Prod"],  "Extrai dados de contratos PDF."),
            ("Analisador de Editais",  integracoes["Gemini Flash Prod"],  "Analisa editais de licitacao."),
            ("Resumidor de Relatorios",integracoes["Gemini Pro"],         "Resume relatorios extensos."),
            ("Classificador de Notas", integracoes["OpenAI GPT-4o"],     "Classifica notas fiscais."),
            ("Extrator de Dados",      integracoes["Gemini Flash Prod"],  "Extrai dados estruturados de documentos."),
        ]

        agentes = []
        for nome, integracao, objetivo in agentes_dados:
            slug = slugify(nome)
            obj, criado = AgenteIA.objects.get_or_create(
                slug=slug,
                defaults={
                    "nome": nome,
                    "tipo": AgentType.EXTRATOR,
                    "visibilidade": AgentVisibility.USUARIO,
                    "modo_acionamento": AgentTriggerMode.PORTAL,
                    "status": AgentStatus.ATIVO,
                    "ai_provider_integration": integracao,
                    "modelo_preferencial": integracao.default_model,
                    "objetivo": objetivo,
                    "prompt_base": f"Voce e um agente especialista. {objetivo}",
                },
            )
            agentes.append(obj)
            status = "criado" if criado else "já existe"
            self.stdout.write(f"  Agente {status}: {nome}")

        # ── Processamentos ficticios ──────────────────────────────
        cotacao = Decimal("5.80")
        cenarios = [
            # (agente_idx, integracao_nome, n_processamentos, docs_each, inp_tokens, out_tokens)
            (0, "Gemini Flash Prod",  8, 3,  28000, 350),
            (0, "Gemini Flash Prod",  5, 1,  15000, 120),
            (1, "Gemini Flash Prod", 12, 5,  42000, 600),
            (2, "Gemini Pro",         4, 8,  90000, 1200),
            (3, "OpenAI GPT-4o",      6, 2,  22000, 280),
            (4, "Gemini Flash Prod",  9, 4,  35000, 450),
            (4, "Gemini Pro",         3, 6,  75000, 900),
        ]

        total_proc = 0
        for agente_idx, integ_nome, n_proc, docs, inp, out in cenarios:
            agente = agentes[agente_idx]
            integracao = integracoes[integ_nome]
            modelo = integracao.default_model
            prec = PrecificacaoModelo.objects.filter(nome_modelo=modelo, ativo=True).first()

            for i in range(n_proc):
                jitter = random.uniform(0.8, 1.2)
                input_tok = int(inp * jitter)
                output_tok = int(out * jitter)
                proc_tok = int(output_tok * 0.15)
                total_tok = input_tok + output_tok + proc_tok

                custo_usd = None
                custo_brl = None
                if prec:
                    custo_usd = (
                        Decimal(input_tok) * prec.preco_input_por_milhao
                        + Decimal(output_tok + proc_tok) * prec.preco_output_por_milhao
                    ) / Decimal("1000000")
                    custo_brl = round(custo_usd * cotacao, 4)

                ts = timezone.now().strftime("%Y%m%d%H%M%S")
                codigo = f"PROC-{ts}-{token_hex(2).upper()}"
                time.sleep(0.01)  # garante unicidade do timestamp

                proc = Processamento(
                    codigo=codigo,
                    agente=agente,
                    iniciado_por=admin,
                    status=ProcessingStatus.CONCLUIDO_SUCESSO,
                    input_source_type=ProcessingInputSourceType.UPLOAD_AT_EXECUTION,
                    output_format=ProcessingOutputFormat.JSON,
                    arquivo_saida_formato=ProcessingOutputFormat.JSON,
                    prompt_snapshot=agente.prompt_base,
                    modelo_snapshot=modelo,
                    output_packaging_mode_snapshot="zip_se_multiplos",
                    output_assembly_mode_snapshot="uma_por_entrada",
                    ai_provider_integration_snapshot=integracao,
                    total_documentos=docs,
                    total_processados=docs,
                    input_tokens=input_tok,
                    processing_tokens=proc_tok,
                    output_tokens=output_tok,
                    total_tokens=total_tok,
                    custo_usd=custo_usd,
                    custo_brl=custo_brl,
                    duracao_processamento_ms=random.randint(8000, 120000),
                    iniciado_em=timezone.now(),
                    finalizado_em=timezone.now(),
                )
                proc.save()
                total_proc += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"Dados criados: {len(integracoes)} integracoes, {len(agentes)} agentes, {total_proc} processamentos."
        ))
        self.stdout.write("Acesse o Painel inicial para ver os dashboards.")
