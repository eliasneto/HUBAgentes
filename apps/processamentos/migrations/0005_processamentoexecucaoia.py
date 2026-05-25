import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("integracoes", "0004_rename_openaiintegration_to_aiproviderintegration"),
        ("processamentos", "0004_processamento_execucao_telemetria"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProcessamentoExecucaoIA",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("tentativa_numero", models.PositiveIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[("sucesso", "Sucesso"), ("erro", "Erro")],
                        default="sucesso",
                        max_length=20,
                    ),
                ),
                ("modelo_utilizado", models.CharField(blank=True, max_length=120)),
                ("execucao_iniciada_em", models.DateTimeField(blank=True, null=True)),
                ("execucao_finalizada_em", models.DateTimeField(blank=True, null=True)),
                ("duracao_ms", models.PositiveIntegerField(blank=True, null=True)),
                ("input_tokens", models.PositiveIntegerField(blank=True, null=True)),
                ("processing_tokens", models.PositiveIntegerField(blank=True, null=True)),
                ("output_tokens", models.PositiveIntegerField(blank=True, null=True)),
                ("total_tokens", models.PositiveIntegerField(blank=True, null=True)),
                ("usage_metadata", models.JSONField(blank=True, default=dict)),
                ("response_summary", models.TextField(blank=True)),
                ("error_message", models.TextField(blank=True)),
                (
                    "ai_provider_integration",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="execucoes_processamento",
                        to="integracoes.openaiintegration",
                    ),
                ),
                (
                    "documento",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="execucoes_ia",
                        to="processamentos.documentoentrada",
                    ),
                ),
                (
                    "processamento",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="execucoes_ia",
                        to="processamentos.processamento",
                    ),
                ),
            ],
            options={
                "verbose_name": "Execucao de IA do processamento",
                "verbose_name_plural": "Execucoes de IA do processamento",
                "ordering": ["-tentativa_numero", "-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="processamentoexecucaoia",
            index=models.Index(
                fields=["processamento", "tentativa_numero"],
                name="processamen_process_03e92c_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="processamentoexecucaoia",
            index=models.Index(
                fields=["processamento", "status"],
                name="processamen_process_378e37_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="processamentoexecucaoia",
            index=models.Index(
                fields=["execucao_iniciada_em"],
                name="processamen_execuca_80a10b_idx",
            ),
        ),
    ]
