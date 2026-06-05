from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_limpeza_booleano_final'),
    ]

    operations = [
        migrations.AddField(
            model_name='configuracaogeral',
            name='dia_execucao_limpeza',
            field=models.PositiveSmallIntegerField(
                default=30,
                help_text='Dia do mes em que a limpeza e executada.',
            ),
        ),
        migrations.AlterField(
            model_name='configuracaogeral',
            name='limpeza_automatica_ativa',
            field=models.BooleanField(
                default=False,
                help_text='Quando ativo, a limpeza roda no dia configurado de cada mes.',
            ),
        ),
    ]
