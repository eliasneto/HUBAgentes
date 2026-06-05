from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('processamentos', '0018_merge_agente_set_null'),
        ('integracoes', '0007_add_groq_provider'),
    ]

    operations = [
        migrations.AlterField(
            model_name='processamento',
            name='google_drive_integration',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='processamentos',
                to='integracoes.googledriveintegration',
            ),
        ),
        migrations.AlterField(
            model_name='processamento',
            name='folder_source',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='processamentos',
                to='integracoes.googledrivefoldersource',
            ),
        ),
        migrations.AlterField(
            model_name='processamento',
            name='local_storage_integration',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='processamentos',
                to='integracoes.localstorageintegration',
            ),
        ),
    ]
