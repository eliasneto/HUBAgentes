"""Testa o agente Groq - Analise CSV com um CSV de exemplo."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Testa o agente Groq com CSV de folha de pagamento."

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model
        from apps.agentes_ia.models import AgenteIA
        from apps.processamentos.services.operational_execution import (
            criar_e_iniciar_processamento_para_agente,
        )
        from apps.processamentos.models import ProcessingInputSourceType, ProcessingOutputFormat
        from django.core.files.base import ContentFile

        User = get_user_model()
        admin = User.objects.filter(is_superuser=True).first()

        agente = AgenteIA.objects.filter(slug__icontains="groq").first()
        if not agente:
            self.stderr.write("Agente Groq nao encontrado.")
            return

        self.stdout.write(f"Usando agente: {agente.nome}")

        csv_content = (
            "EMPRESA: FOLHA TESTE LTDA - COMPETENCIA: 05/2026\n"
            "Cód.Empregado;Cód.Evento;Referência;Valor do Evento\n"
            "001;100;30;3.500,00\n"
            "001;200;1;150,00\n"
            "001;500;1;200,00\n"
            "002;100;30;4.200,00\n"
            "002;150;2;300,00\n"
            "003;100;30;2.800,00\n"
            "003;200;1;120,00\n"
            "Z;TOTAL;;11.270,00\n"
        ).encode("utf-8")

        self.stdout.write("Iniciando processamento...")
        try:
            arquivo = ContentFile(csv_content, name="folha_teste.csv")
            cleaned_data = {
                "input_source_type": ProcessingInputSourceType.UPLOAD_AT_EXECUTION,
                "output_format": ProcessingOutputFormat.JSON,
                "arquivo_execucao_upload": arquivo,
                "local_relative_input_path": "",
                "local_storage_integration": None,
                "folder_source": None,
            }
            processamento = criar_e_iniciar_processamento_para_agente(
                agente=agente,
                actor=admin,
                cleaned_data=cleaned_data,
            )
            from apps.processamentos.models import ProcessingStatus
            processamento.refresh_from_db()
            self.stdout.write(f"Status: {processamento.status}")
            self.stdout.write(f"Erro: {processamento.mensagem_erro or 'nenhum'}")
            if processamento.arquivo_saida:
                processamento.arquivo_saida.open("rb")
                saida = processamento.arquivo_saida.read().decode("utf-8")
                self.stdout.write(f"Saida (500 chars): {saida[:500]}")
            else:
                self.stdout.write("Sem arquivo de saida.")
        except Exception as exc:
            import traceback
            self.stderr.write(f"ERRO: {exc}")
            traceback.print_exc()
