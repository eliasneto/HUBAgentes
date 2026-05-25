from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("processamentos", "0007_alter_documentoentrada_source_type_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="processamento",
            name="mensagem_erro_tecnico",
            field=models.TextField(blank=True),
        ),
    ]
