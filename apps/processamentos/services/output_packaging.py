import io
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from django.core.files.base import ContentFile

from apps.agentes_ia.models import AgentOutputAssemblyMode, AgentOutputPackagingMode
from apps.processamentos.models import ProcessingOutputFormat


class OutputPackagingError(Exception):
    pass


def publicar_saida_final(
    *,
    processamento,
    output_records,
    output_packaging_mode,
    output_assembly_mode,
    source_document_count,
):
    if not output_records:
        return False

    if _deve_empacotar_em_zip(
        output_records=output_records,
        output_packaging_mode=output_packaging_mode,
        output_assembly_mode=output_assembly_mode,
        source_document_count=source_document_count,
    ):
        package_name, package_bytes = _render_zip(processamento, output_records)
        processamento.arquivo_saida.save(
            package_name,
            ContentFile(package_bytes),
            save=False,
        )
        processamento.arquivo_saida_nome = package_name
        processamento.arquivo_saida_formato = ProcessingOutputFormat.ZIP
        return True

    output_record = output_records[-1]
    if not output_record.arquivo:
        raise OutputPackagingError(
            "A saida individual nao possui arquivo disponivel para publicacao final."
        )

    processamento.arquivo_saida.name = output_record.arquivo.name
    processamento.arquivo_saida_nome = output_record.arquivo_nome or Path(
        output_record.arquivo.name
    ).name
    processamento.arquivo_saida_formato = output_record.formato
    return True


def _deve_empacotar_em_zip(
    *,
    output_records,
    output_packaging_mode,
    output_assembly_mode,
    source_document_count,
):
    if output_packaging_mode == AgentOutputPackagingMode.SEMPRE_ZIP:
        return True
    if output_packaging_mode == AgentOutputPackagingMode.ZIP_SE_MULTIPLOS:
        if output_assembly_mode == AgentOutputAssemblyMode.UMA_POR_ENTRADA:
            return source_document_count > 1
        return len(output_records) > 1
    return False


def _render_zip(processamento, output_records):
    package_name = f"{processamento.codigo}_resultados.zip"
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for index, output_record in enumerate(output_records, start=1):
            if not output_record.arquivo:
                continue
            entry_name = _build_zip_entry_name(output_record, index)
            with output_record.arquivo.open("rb") as output_stream:
                archive.writestr(entry_name, output_stream.read())
    return package_name, buffer.getvalue()


def _build_zip_entry_name(output_record, index):
    raw_name = output_record.arquivo_nome or (
        Path(output_record.arquivo.name).name if output_record.arquivo else ""
    )
    safe_name = Path(raw_name).name if raw_name else ""
    if safe_name:
        return safe_name

    extension = {
        ProcessingOutputFormat.JSON: ".json",
        ProcessingOutputFormat.CSV: ".csv",
        ProcessingOutputFormat.XLSX: ".xlsx",
        ProcessingOutputFormat.PDF: ".pdf",
        ProcessingOutputFormat.TXT: ".txt",
    }.get(output_record.formato, "")
    return f"saida_{index}{extension}"
