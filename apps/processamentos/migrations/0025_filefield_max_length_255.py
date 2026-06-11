from django.db import migrations, models

import apps.processamentos.models


class Migration(migrations.Migration):
    """Aumenta max_length dos FileField de 100 (default) para 255.

    Nomes de arquivo longos (ex.: editais) somados ao prefixo
    "processamentos/{codigo}/entradas/" ultrapassavam 100 caracteres e o
    Django falhava com "Storage can not find an available filename ...
    allows sufficient max_length" ao salvar o upload.
    """

    dependencies = [
        ('processamentos', '0024_alter_documentosaidaprocessamento_formato_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='processamento',
            name='arquivo_execucao_upload',
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=apps.processamentos.models.processamento_input_upload_path,
            ),
        ),
        migrations.AlterField(
            model_name='processamento',
            name='arquivo_saida',
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=apps.processamentos.models.processamento_output_path,
            ),
        ),
        migrations.AlterField(
            model_name='documentoentrada',
            name='uploaded_file',
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=apps.processamentos.models.documento_entrada_upload_path,
            ),
        ),
        migrations.AlterField(
            model_name='documentosaidaprocessamento',
            name='arquivo',
            field=models.FileField(
                blank=True,
                max_length=255,
                null=True,
                upload_to=apps.processamentos.models.documento_saida_output_path,
            ),
        ),
    ]
