from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('processamentos', '0015_documentoentrada_pasta_grupo'),
    ]

    operations = [
        migrations.AddField(
            model_name='processamento',
            name='custo_usd',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name='processamento',
            name='custo_brl',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name='processamentoexecucaoia',
            name='custo_usd',
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name='processamentoexecucaoia',
            name='custo_brl',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True),
        ),
    ]
