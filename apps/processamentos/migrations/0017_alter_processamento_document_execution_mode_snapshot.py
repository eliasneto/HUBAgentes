from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('processamentos', '0016_add_custo_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='processamento',
            name='document_execution_mode_snapshot',
            field=models.CharField(
                choices=[
                    ('individual', 'Individual'),
                    ('grupo_unico', 'Grupo unico'),
                    ('lote_por_pasta', 'Lote por sub-pastas'),
                ],
                default='individual',
                max_length=30,
            ),
        ),
    ]
