"""
DB-U1: re-criptografa em repouso os registros criados ANTES da migracao 0006.

A 0006 trocou os campos para EncryptedTextField/EncryptedCharField, mas apenas
no schema — os valores ja existentes no banco permaneceram em texto puro e so
seriam criptografados quando o registro fosse re-salvo manualmente. Esta
migracao percorre todos os registros e os re-salva, forcando a criptografia.

E idempotente: o EncryptedFieldMixin detecta valor ja cifrado e nao re-encripta.
Cobre tambem registros soft-deletados (o manager historico nao filtra deleted_at).

Requer FIELD_ENCRYPTION_KEY configurada — garantida pelo system check core.E001,
que bloqueia o migrate se a chave estiver ausente.
"""

from django.db import migrations


def encrypt_existing(apps, schema_editor):
    GoogleDriveIntegration = apps.get_model("integracoes", "GoogleDriveIntegration")
    for integracao in GoogleDriveIntegration.objects.all():
        # from_db_value ja devolveu o texto puro (fallback nos legados);
        # o save dispara get_prep_value, que aplica a criptografia.
        integracao.save(update_fields=["credentials_json"])

    OpenAIIntegration = apps.get_model("integracoes", "OpenAIIntegration")
    for integracao in OpenAIIntegration.objects.all():
        integracao.save(update_fields=["api_key"])


class Migration(migrations.Migration):

    dependencies = [
        ("integracoes", "0011_alter_localstorageintegration_usuarios_autorizados_and_more"),
    ]

    operations = [
        # Sem reverse: nao re-expomos credenciais em texto puro ao reverter.
        migrations.RunPython(encrypt_existing, migrations.RunPython.noop),
    ]
