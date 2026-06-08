from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integracoes', '0008_localstorageintegration_compartilhada'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='localstorageintegration',
            name='usuarios_autorizados',
            field=models.ManyToManyField(
                blank=True,
                help_text='Usuários que podem usar esta pasta. Vazio = somente administradores.',
                related_name='integracoes_pasta_autorizada',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
