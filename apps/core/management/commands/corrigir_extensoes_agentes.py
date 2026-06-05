from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Atualiza allowed_input_extensions de agentes que so tem pdf."

    def handle(self, *args, **options):
        from apps.agentes_ia.models import AgenteConfiguracaoOperacional
        todos = ["pdf", "txt", "csv", "png", "jpg", "jpeg", "xlsx"]
        atualizados = 0
        for config in AgenteConfiguracaoOperacional.objects.all():
            if set(config.allowed_input_extensions or []) <= {"pdf"}:
                config.allowed_input_extensions = todos
                config.save(update_fields=["allowed_input_extensions", "updated_at"])
                atualizados += 1
                self.stdout.write(f"  Atualizado: {config.agente.nome}")
        self.stdout.write(self.style.SUCCESS(f"Total: {atualizados} configuracoes atualizadas."))
