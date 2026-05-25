from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "processamentos",
            "0003_rename_openai_snapshot_to_ai_provider_snapshot",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="processamento",
            name="duracao_processamento_ms",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="processamento",
            name="execucao_finalizada_em",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="processamento",
            name="execucao_iniciada_em",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="processamento",
            name="input_tokens",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="processamento",
            name="output_tokens",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="processamento",
            name="processing_tokens",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="processamento",
            name="total_tokens",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
