from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_alter_configuracaogeral_data_programada_limpeza'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='configuracaogeral',
            name='data_programada_limpeza',
        ),
        migrations.AddField(
            model_name='configuracaogeral',
            name='limpeza_automatica_ativa',
            field=models.BooleanField(
                default=False,
                help_text='Quando ativo, o sistema deleta arquivos de saida com mais de 30 dias toda meia-noite.',
            ),
        ),
        migrations.AddField(
            model_name='configuracaogeral',
            name='dias_retencao_arquivos',
            field=models.PositiveIntegerField(
                default=30,
                help_text='Dias de retencao dos arquivos de saida. Alteravel apenas pelo admin.',
            ),
        ),
    ]
