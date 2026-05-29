"""
Cria AIProviderIntegration como proxy formal de OpenAIIntegration (A4),
criptografa campos sensiveis (U1, U2) e adiciona soft delete (M3).

A tabela fisica permanece integracoes_openaiintegration. O proxy compartilha
a mesma tabela sem migracao de dados.
"""

import apps.core.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("integracoes", "0005_localstorageintegration"),
    ]

    operations = [
        # U2: api_key agora e armazenada criptografada (TextField cifrado via Fernet).
        # Dados existentes serao lidos com fallback gracioso ate serem re-salvos.
        migrations.AlterField(
            model_name="openaiintegration",
            name="api_key",
            field=apps.core.fields.EncryptedCharField(),
        ),

        # U1: credentials_json agora e armazenado criptografado.
        migrations.AlterField(
            model_name="googledriveintegration",
            name="credentials_json",
            field=apps.core.fields.EncryptedTextField(),
        ),

        # M3: soft delete — OpenAIIntegration / AIProviderIntegration.
        migrations.AddField(
            model_name="openaiintegration",
            name="deleted_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),

        # M3: soft delete — GoogleDriveIntegration.
        migrations.AddField(
            model_name="googledriveintegration",
            name="deleted_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),

        # M3: soft delete — LocalStorageIntegration.
        migrations.AddField(
            model_name="localstorageintegration",
            name="deleted_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),

        # Meta options — LocalStorageIntegration.
        migrations.AlterModelOptions(
            name="localstorageintegration",
            options={
                "verbose_name": "Conexao de pasta local",
                "verbose_name_plural": "Conexoes de pasta local",
            },
        ),

        # A4: AIProviderIntegration como proxy formal de OpenAIIntegration.
        migrations.CreateModel(
            name="AIProviderIntegration",
            fields=[],
            options={
                "proxy": True,
                "verbose_name": "Integracao de IA",
                "verbose_name_plural": "Integracoes de IA",
                "indexes": [],
                "constraints": [],
            },
            bases=("integracoes.openaiintegration",),
        ),
    ]
