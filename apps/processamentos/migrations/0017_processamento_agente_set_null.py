from django.db import migrations, models
import django.db.models.deletion
from apps.agentes_ia.models import AgenteIA


class Migration(migrations.Migration):

    dependencies = [
        ('processamentos', '0016_add_custo_fields'),
        ('agentes_ia', '0009_alter_agenteia_objetivo'),
    ]

    operations = [
        migrations.AlterField(
            model_name='processamento',
            name='agente',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='processamentos',
                to='agentes_ia.agenteia',
            ),
        ),
    ]
