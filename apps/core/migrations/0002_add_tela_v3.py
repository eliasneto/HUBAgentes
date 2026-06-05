from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_configuracao_tela_login'),
    ]

    operations = [
        migrations.AlterField(
            model_name='configuracaotelalogin',
            name='tela_ativa',
            field=models.CharField(
                choices=[
                    ('principal', 'Tela Principal (robô animado)'),
                    ('v2', 'Tela 2 (robô + painel lateral)'),
                    ('v3', 'Tela 3 (robô neon + paleta do sistema)'),
                ],
                default='principal',
                max_length=20,
            ),
        ),
    ]
