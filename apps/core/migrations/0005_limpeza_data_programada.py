from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_configuracaogeral_limpeza'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='configuracaogeral',
            name='limpeza_automatica_ativa',
        ),
        migrations.RemoveField(
            model_name='configuracaogeral',
            name='dias_retencao_arquivos',
        ),
        migrations.AddField(
            model_name='configuracaogeral',
            name='data_programada_limpeza',
            field=models.DateField(
                null=True,
                blank=True,
                help_text='Na data escolhida, a meia-noite, o sistema apagara todos os arquivos de saida com mais de 30 dias.',
            ),
        ),
    ]
