from django.core.management.base import BaseCommand

from apps.processamentos.services.operational_execution import (
    executar_rotinas_automaticas_agentes,
)


class Command(BaseCommand):
    help = (
        "Dispara a rotina automatica dos agentes com "
        "AgenteConfiguracaoOperacional.execucao_automatica_ativa=True, "
        "respeitando o interruptor e o intervalo GLOBAIS "
        "(ConfiguracaoGeral.rotina_automatica_agentes_ativa/"
        "rotina_automatica_intervalo_minutos, editaveis em Administrador > "
        "Rotina automatica) — processa um lote pequeno de documentos "
        "pendentes por agente (execucao_automatica_lote_tamanho, padrao "
        "10; forcado para 6 quando o intervalo global for menor que 30min) "
        "em vez de tentar processar tudo de uma vez numa unica execucao "
        "sincrona. Deve ser executado periodicamente via cron ou worker; "
        "so dispara de fato quando a proxima rodada global ja chegou, "
        "independente da frequencia com que este comando e chamado."
    )

    def handle(self, *args, **options):
        resultados = executar_rotinas_automaticas_agentes()

        if not resultados:
            self.stdout.write("Rotina automatica desligada ou nenhum agente elegivel agora.")
            return

        for item in resultados:
            detalhe = (
                f"{item['total_sucesso']}/{item['total_documentos']} ok, "
                f"{item['total_erro']} erro"
                if item["total_documentos"]
                else (item["motivo"] or "sem documentos novos")
            )
            self.stdout.write(f"  {item['agente']}: {item['status']} - {detalhe}")

        self.stdout.write(
            self.style.SUCCESS(f"\n{len(resultados)} agente(s) verificado(s).")
        )
