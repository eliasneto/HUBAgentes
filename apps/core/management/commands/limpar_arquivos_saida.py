"""
Deleta arquivos de saida de processamentos mais antigos que o período configurado.
Executado automaticamente a meia-noite pelo worker quando limpeza_automatica_ativa=True.

Execute manualmente com:
    python manage.py limpar_arquivos_saida
    python manage.py limpar_arquivos_saida --dias 30 --dry-run
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta


class Command(BaseCommand):
    help = "Deleta arquivos de saida de processamentos mais antigos que N dias."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dias",
            type=int,
            default=None,
            help="Dias de retencao (sobrepoe a configuracao do banco).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Simula a limpeza sem deletar nada.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Executa mesmo se limpeza_automatica_ativa=False.",
        )
        parser.add_argument(
            "--check-day",
            action="store_true",
            help="Executa apenas se hoje e o dia configurado. Retorna exit code 0 se executou, 1 se nao era o dia.",
        )

    def handle(self, *args, **options):
        from apps.core.models import ConfiguracaoGeral
        from apps.processamentos.models import Processamento

        config = ConfiguracaoGeral.obter()
        dry_run = options["dry_run"]
        force   = options["force"]

        if not config.limpeza_automatica_ativa and not force:
            self.stdout.write("Limpeza automatica desativada. Use --force para executar manualmente.")
            raise SystemExit(1)

        if options["check_day"] and not force:
            from datetime import date
            hoje = date.today()
            import calendar
            ultimo_dia = calendar.monthrange(hoje.year, hoje.month)[1]
            dia_alvo = min(config.dia_execucao_limpeza, ultimo_dia)
            if hoje.day != dia_alvo:
                self.stdout.write(f"Hoje e dia {hoje.day}, execucao programada para dia {dia_alvo}. Nada a fazer.")
                raise SystemExit(1)
            self.stdout.write(f"Hoje e o dia {dia_alvo} — executando limpeza mensal.")

        dias = options["dias"] or config.dias_retencao_arquivos
        corte = timezone.now() - timedelta(days=dias)

        candidatos = Processamento.objects.filter(
            arquivo_saida__isnull=False,
            arquivo_saida_liberado_em__lt=corte,
        ).exclude(arquivo_saida="")

        total = candidatos.count()
        self.stdout.write(
            f"Limpeza de arquivos de saida — corte: {corte.strftime('%d/%m/%Y')} "
            f"(retencao: {dias} dias) | candidatos: {total}"
        )

        if total == 0:
            self.stdout.write("Nenhum arquivo para deletar.")
            return

        if dry_run:
            for proc in candidatos[:20]:
                self.stdout.write(f"  [DRY-RUN] {proc.codigo} — {proc.arquivo_saida_nome}")
            if total > 20:
                self.stdout.write(f"  ... e mais {total - 20} arquivo(s)")
            return

        deletados = 0
        erros = 0
        for proc in candidatos:
            try:
                proc.arquivo_saida.delete(save=False)
                proc.arquivo_saida = None
                proc.arquivo_saida_nome = ""
                proc.arquivo_saida_liberado_em = None
                proc.save(update_fields=[
                    "arquivo_saida", "arquivo_saida_nome",
                    "arquivo_saida_liberado_em", "updated_at",
                ])
                deletados += 1
            except Exception as exc:
                erros += 1
                self.stderr.write(f"  Erro ao deletar {proc.codigo}: {exc}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Limpeza concluida: {deletados} arquivo(s) deletado(s), {erros} erro(s)."
            )
        )
