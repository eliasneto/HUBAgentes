from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_configuracao_geral'),
    ]

    operations = [
        migrations.AddField(
            model_name='configuracaogeral',
            name='limpeza_automatica_ativa',
            field=models.BooleanField(
                default=False,
                help_text='Se ativo, arquivos de saida com mais de 30 dias sao deletados automaticamente a meia-noite.',
            ),
        ),
        migrations.AddField(
            model_name='configuracaogeral',
            name='dias_retencao_arquivos',
            field=models.PositiveIntegerField(
                default=30,
                help_text='Quantidade de dias para manter os arquivos de saida.',
            ),
        ),
    ]
