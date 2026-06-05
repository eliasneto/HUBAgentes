from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ConfiguracaoTelaLogin',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('tela_ativa', models.CharField(
                    choices=[('principal', 'Tela Principal (robô animado)'), ('v2', 'Tela 2 (painel lateral direito)')],
                    default='principal',
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
            options={'verbose_name': 'Configuracao de Tela de Login'},
        ),
    ]
