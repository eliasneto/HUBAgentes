from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('integracoes', '0009_localstorageintegration_usuarios_autorizados'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Remove o M2M simples e recria com through
        migrations.RemoveField(
            model_name='localstorageintegration',
            name='usuarios_autorizados',
        ),
        migrations.CreateModel(
            name='PastaCompartilhadaUsuario',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('permissao', models.CharField(
                    choices=[('leitura', 'Leitura'), ('escrita', 'Leitura e escrita')],
                    default='leitura',
                    max_length=10,
                )),
                ('integracao', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='membros',
                    to='integracoes.localstorageintegration',
                )),
                ('usuario', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='membros_pasta',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'verbose_name': 'Membro de pasta compartilhada',
                'unique_together': {('integracao', 'usuario')},
            },
        ),
        migrations.AddField(
            model_name='localstorageintegration',
            name='usuarios_autorizados',
            field=models.ManyToManyField(
                blank=True,
                help_text='Usuários que podem usar esta pasta.',
                related_name='integracoes_pasta_autorizada',
                through='integracoes.PastaCompartilhadaUsuario',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
