import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "integracoes",
            "0004_rename_openaiintegration_to_aiproviderintegration",
        ),
        (
            "processamentos",
            "0002_processamento_drive_folder_url_escolhida_and_more",
        ),
    ]

    operations = [
        migrations.RenameField(
            model_name="processamento",
            old_name="openai_integration_snapshot",
            new_name="ai_provider_integration_snapshot",
        ),
        migrations.AlterField(
            model_name="processamento",
            name="ai_provider_integration_snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="processamentos_snapshot",
                to="integracoes.openaiintegration",
            ),
        ),
    ]
