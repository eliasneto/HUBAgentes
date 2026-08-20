from django.core.management.base import BaseCommand

from apps.processamentos.services.agent_execution import (
    retentar_processamentos_com_sobrecarga,
)


class Command(BaseCommand):
    help = (
        "Avanca o loop de retentativa automatica de processamentos travados "
        "por sobrecarga do provedor de IA (ex.: Gemini HTTP 503 'model is "
        "currently experiencing high demand') — ver "
        "Processamento.retentativa_sobrecarga_ativa. Deve ser executado "
        "periodicamente via cron ou worker; cada chamada avanca uma rodada "
        "para cada processamento cuja proxima tentativa ja esta no tempo."
    )

    def handle(self, *args, **options):
        resultados = retentar_processamentos_com_sobrecarga()

        if not resultados:
            self.stdout.write("Nenhum processamento aguardando retentativa por sobrecarga.")
            return

        for item in resultados:
            self.stdout.write(f"  {item['codigo']}: {item['resultado']}")

        self.stdout.write(
            self.style.SUCCESS(f"\n{len(resultados)} processamento(s) avancado(s).")
        )
