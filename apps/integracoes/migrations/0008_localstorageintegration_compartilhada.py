from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integracoes', '0007_add_groq_provider'),
    ]

    operations = [
        migrations.AddField(
            model_name='localstorageintegration',
            name='compartilhada',
            field=models.BooleanField(
                default=False,
                help_text='Pastas compartilhadas ficam visíveis para todos os usuários.',
            ),
        ),
    ]
