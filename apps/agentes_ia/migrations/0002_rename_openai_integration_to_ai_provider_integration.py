import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "integracoes",
            "0004_rename_openaiintegration_to_aiproviderintegration",
        ),
        ("agentes_ia", "0001_initial"),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="agenteia",
            name="agentes_ia__openai__c6021e_idx",
        ),
        migrations.RenameField(
            model_name="agenteia",
            old_name="openai_integration",
            new_name="ai_provider_integration",
        ),
        migrations.AddIndex(
            model_name="agenteia",
            index=models.Index(
                fields=["ai_provider_integration"],
                name="agentes_ia_ai_provider_idx",
            ),
        ),
        migrations.AlterField(
            model_name="agenteia",
            name="ai_provider_integration",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="agentes",
                to="integracoes.openaiintegration",
            ),
        ),
    ]
