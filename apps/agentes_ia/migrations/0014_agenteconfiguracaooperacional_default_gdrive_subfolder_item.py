from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('agentes_ia', '0013_alter_agenteconfiguracaooperacional_default_output_format'),
    ]

    operations = [
        migrations.AddField(
            model_name='agenteconfiguracaooperacional',
            name='default_gdrive_subfolder_path',
            field=models.JSONField(blank=True, default=list),
        ),
    ]
