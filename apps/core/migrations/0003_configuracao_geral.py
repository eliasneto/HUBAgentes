from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_add_tela_v3'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ConfiguracaoGeral',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('visibilidade_dashboard', models.CharField(
                    choices=[
                        ('administrador', 'Apenas Administrador'),
                        ('analista', 'Administrador e Analista'),
                        ('operacional', 'Todos (Administrador, Analista e Operacional)'),
                    ],
                    default='administrador',
                    max_length=20,
                )),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('atualizado_por', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'verbose_name': 'Configuracao Geral'},
        ),
    ]
