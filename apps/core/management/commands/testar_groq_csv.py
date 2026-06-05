"""Testa o processamento de CSV com Groq."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Testa Groq com CSV."

    def handle(self, *args, **options):
        from apps.integracoes.models import AIProviderIntegration
        from apps.integracoes.services.ai_providers.groq_adapter import GroqProviderAdapter

        integracao = AIProviderIntegration.objects.filter(provider_type='groq').first()
        if not integracao:
            self.stderr.write("Nenhuma integracao Groq encontrada.")
            return

        self.stdout.write(f"Usando: {integracao.nome} - {integracao.default_model}")

        csv_bytes = (
            b"Cod.Empregado;Cod.Evento;Referencia;Valor do Evento\n"
            b"001;100;30;3500,00\n"
            b"001;200;1;150,00\n"
            b"002;100;30;4200,00\n"
        )

        prompt = (
            "Leia o CSV abaixo e retorne SOMENTE JSON valido sem markdown:\n"
            "{\"resumo\": {\"total_funcionarios\": 0, \"soma_total_valores\": 0}, "
            "\"funcionarios\": []}"
        )

        adapter = GroqProviderAdapter(integracao)
        try:
            result = adapter.execute_prompt_with_document(
                prompt=prompt,
                document_bytes=csv_bytes,
                document_mime_type="text/csv",
                document_name="teste.csv",
                execution_params={"response_mime_type": "application/json"},
                model_name=integracao.default_model,
            )
            self.stdout.write(self.style.SUCCESS("SUCESSO"))
            self.stdout.write(f"Tokens: {result.usage_metadata}")
            self.stdout.write(f"Output (300 chars): {result.output_text[:300]}")
        except Exception as exc:
            self.stderr.write(f"ERRO: {exc}")
