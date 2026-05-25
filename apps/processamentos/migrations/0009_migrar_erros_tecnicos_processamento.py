import re

from django.db import migrations


ERRO_TECNICO_OPERACIONAL = (
    "Ocorreu um erro tecnico ao executar o agente. "
    "Contate o administrador do sistema."
)

TECHNICAL_ERROR_PATTERNS = (
    "falha http",
    "permission_denied",
    "access denied",
    "denied access",
    "api key",
    "token",
    "traceback",
    "stack trace",
    "exception",
    "credentials",
    "unauthorized",
    "forbidden",
)


def migrar_erros_tecnicos(apps, schema_editor):
    Processamento = apps.get_model("processamentos", "Processamento")
    for processamento in Processamento.objects.exclude(mensagem_erro="").iterator():
        mensagem = processamento.mensagem_erro or ""
        mensagem_normalizada = mensagem.lower()
        is_technical = any(
            pattern in mensagem_normalizada
            for pattern in TECHNICAL_ERROR_PATTERNS
        ) or bool(re.search(r"\b(4\d{2}|5\d{2})\b", mensagem_normalizada))

        if not is_technical:
            continue

        processamento.mensagem_erro_tecnico = (
            processamento.mensagem_erro_tecnico or mensagem
        )
        processamento.mensagem_erro = ERRO_TECNICO_OPERACIONAL
        processamento.save(
            update_fields=[
                "mensagem_erro",
                "mensagem_erro_tecnico",
                "updated_at",
            ]
        )


class Migration(migrations.Migration):

    dependencies = [
        ("processamentos", "0008_processamento_mensagem_erro_tecnico"),
    ]

    operations = [
        migrations.RunPython(migrar_erros_tecnicos, migrations.RunPython.noop),
    ]
