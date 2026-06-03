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
            name='PrecificacaoModelo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('nome_modelo', models.CharField(max_length=120, unique=True)),
                ('preco_input_por_milhao', models.DecimalField(decimal_places=6, max_digits=12)),
                ('preco_output_por_milhao', models.DecimalField(decimal_places=6, max_digits=12)),
                ('ativo', models.BooleanField(default=True)),
            ],
            options={
                'verbose_name': 'Precificacao de Modelo',
                'verbose_name_plural': 'Precificacoes de Modelos',
                'ordering': ['nome_modelo'],
            },
        ),
        migrations.CreateModel(
            name='ConfiguracaoFinanceira',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('cotacao_dolar', models.DecimalField(decimal_places=4, max_digits=10)),
                ('atualizado_por', models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Configuracao Financeira',
                'verbose_name_plural': 'Configuracoes Financeiras',
            },
        ),
    ]
