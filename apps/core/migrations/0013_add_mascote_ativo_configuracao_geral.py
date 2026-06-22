from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_configuracaogeral_max_execucoes_por_usuario_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='configuracaogeral',
            name='mascote_ativo',
            field=models.BooleanField(default=True, help_text='Quando ativo, o assistente Biel aparece flutuando no portal para todos os usuarios.'),
        ),
    ]
