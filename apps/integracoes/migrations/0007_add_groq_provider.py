from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('integracoes', '0006_aiproviderintegration_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='openaiintegration',
            name='provider_type',
            field=models.CharField(
                choices=[
                    ('openai', 'OpenAI'),
                    ('anthropic', 'Anthropic'),
                    ('gemini', 'Gemini'),
                    ('groq', 'Groq'),
                ],
                default='openai',
                max_length=40,
            ),
        ),
    ]
