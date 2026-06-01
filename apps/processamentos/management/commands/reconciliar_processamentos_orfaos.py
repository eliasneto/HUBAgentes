from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.processamentos.models import Processamento, ProcessingStatus
from apps.processamentos.services.stalled_processing import (
    ORPHAN_PROCESSING_TIMEOUT_SECONDS,
    reconciliar_processamento_orfao,
)


STATUSES_ATIVOS = {
    ProcessingStatus.CRIADO,
    ProcessingStatus.EM_FILA,
    ProcessingStatus.EM_PROCESSAMENTO,
}


class Command(BaseCommand):
    help = (
        "Verifica processamentos ativos sem atividade recente e os marca como erro. "
        f"Timeout padrao: {ORPHAN_PROCESSING_TIMEOUT_SECONDS}s. "
        "Deve ser executado periodicamente via cron ou worker."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Apenas lista os processamentos orfaos sem alterar o banco.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        iniciado_em = timezone.now()

        candidatos = Processamento.objects.filter(
            status__in=STATUSES_ATIVOS
        ).select_related("agente").order_by("created_at")

        total = candidatos.count()
        if total == 0:
            self.stdout.write("Nenhum processamento ativo encontrado.")
            return

        self.stdout.write(f"Verificando {total} processamento(s) ativo(s)...")

        reconciliados = 0
        for processamento in candidatos:
            status_antes = processamento.status

            if dry_run:
                from datetime import timedelta
                last_activity = processamento.ultima_atividade_em or processamento.updated_at
                if last_activity and (timezone.now() - last_activity) >= timedelta(
                    seconds=ORPHAN_PROCESSING_TIMEOUT_SECONDS
                ):
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [DRY-RUN] Orfao: {processamento.codigo} "
                            f"| agente: {processamento.agente.nome} "
                            f"| status: {status_antes} "
                            f"| ultima atividade: {last_activity}"
                        )
                    )
                    reconciliados += 1
                continue

            reconciliar_processamento_orfao(processamento)
            processamento.refresh_from_db()

            if processamento.status != status_antes:
                reconciliados += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"  Reconciliado: {processamento.codigo} "
                        f"| agente: {processamento.agente.nome} "
                        f"| {status_antes} -> {processamento.status}"
                    )
                )

        duracao = (timezone.now() - iniciado_em).total_seconds()

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n[DRY-RUN] {reconciliados} de {total} seriam reconciliados "
                    f"({duracao:.1f}s)"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\nConcluido: {reconciliados} reconciliado(s) de {total} verificado(s) "
                    f"({duracao:.1f}s)"
                )
            )
