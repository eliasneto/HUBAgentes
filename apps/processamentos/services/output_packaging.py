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

    # Prefere o registro mais recente que TEM arquivo, em vez de pegar
    # output_records[-1] (o mais ANTIGO, ja que DocumentoSaidaProcessamento.
    # Meta.ordering = ["-created_at"] traz do mais novo pro mais velho) —
    # quando um documento e retentado (ex.: loop de retentativa por
    # sobrecarga do provedor), cada tentativa cria um novo registro; pegar
    # o mais velho as cegas pode escolher uma tentativa que falhou (sem
    # arquivo) mesmo com uma tentativa POSTERIOR bem-sucedida (com arquivo)
    # na mesma lista. Caso real em producao (30/08/2026,
    # PROC-20260826130828-16738188): documento tinha 3 tentativas com erro
    # seguidas de 1 com sucesso, e o codigo antigo pegava a mais antiga
    # (erro, sem arquivo) e explodia com OutputPackagingError — travando o
    # processamento pra sempre (ver agent_execution._finalizar_loop_
    # sobrecarga, que roda dentro de um transaction.atomic() sem try/except
    # ao redor desta chamada: a excecao revertia ATE o reset de
    # retentativa_sobrecarga_ativa, entao o worker recriava o mesmo erro a
    # cada rodada, indefinidamente).
    output_record = next((r for r in output_records if r.arquivo), None)
    if output_record is None:
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
