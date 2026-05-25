from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("integracoes", "0003_googledrivefoldersourceitem"),
    ]

    operations = [
        migrations.AddField(
            model_name="openaiintegration",
            name="last_validated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="openaiintegration",
            name="last_validation_summary",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="openaiintegration",
            name="provider_type",
            field=models.CharField(
                choices=[
                    ("openai", "OpenAI"),
                    ("anthropic", "Anthropic"),
                    ("gemini", "Gemini"),
                ],
                default="openai",
                max_length=40,
            ),
        ),
        migrations.AlterModelOptions(
            name="openaiintegration",
            options={
                "verbose_name": "Integracao de IA",
                "verbose_name_plural": "Integracoes de IA",
            },
        ),
        migrations.AddIndex(
            model_name="openaiintegration",
            index=models.Index(
                fields=["provider_type", "status"],
                name="integ_ai_prov_status_idx",
            ),
        ),
    ]
