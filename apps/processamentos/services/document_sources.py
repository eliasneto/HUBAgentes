import hashlib
from pathlib import Path

from django.core.files.base import ContentFile
from django.db import transaction

from apps.agentes_ia.models import AgentDocumentExecutionMode
from apps.integracoes.services.google_drive import (
    GoogleDriveServiceError,
    GOOGLE_DRIVE_FOLDER_MIME,
    list_folder_contents_from_folder_source,
    list_pdf_files_from_drive_folder_id,
    list_pdf_files_from_folder_source,
)
from apps.integracoes.services.local_storage import (
    LocalStorageServiceError,
    MIME_TYPE_MAP,
    get_local_file_payload,
    list_pdf_files_from_relative_folder,
    list_pdf_files_from_subfolder,
    list_subfolders_from_relative_folder,
    read_local_file_bytes,
)
from apps.processamentos.models import (
    DocumentoEntrada,
    DocumentStatus,
    ProcessingInputSourceType,
)


class DocumentSourcePreparationError(Exception):
    pass


def prepare_documentos(processamento):
    is_lote_por_pasta = (
        processamento.document_execution_mode_snapshot
        == AgentDocumentExecutionMode.LOTE_POR_PASTA
    )
    if processamento.input_source_type == ProcessingInputSourceType.NONE:
        return {"created": 0, "updated": 0, "total": 0}
    if processamento.input_source_type == ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER:
        if is_lote_por_pasta:
            return _prepare_google_drive_documents_por_pasta(processamento)
        return _prepare_google_drive_documents(processamento)
    if processamento.input_source_type == ProcessingInputSourceType.LOCAL_FOLDER:
        if is_lote_por_pasta:
            return _prepare_local_folder_documents_por_pasta(processamento)
        return _prepare_local_folder_documents(processamento)
    if processamento.input_source_type == ProcessingInputSourceType.LOCAL_FILE:
        return _prepare_local_file_document(processamento)
    if processamento.input_source_type == ProcessingInputSourceType.UPLOAD_AT_EXECUTION:
        return _prepare_upload_document(processamento)
    raise DocumentSourcePreparationError("Tipo de origem documental nao suportado.")


def load_document_bytes(processamento, documento):
    if documento.source_type == ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER:
        if processamento.google_drive_integration is None:
            raise DocumentSourcePreparationError(
                "A integracao do Google Drive nao esta configurada para este processamento."
            )
        from apps.integracoes.services.google_drive import download_drive_file_bytes

        return download_drive_file_bytes(processamento.google_drive_integration, documento.drive_file_id)
    if documento.source_type in {
        ProcessingInputSourceType.LOCAL_FOLDER,
        ProcessingInputSourceType.LOCAL_FILE,
    }:
        if processamento.local_storage_integration is None:
            raise DocumentSourcePreparationError(
                "A integracao local nao esta configurada para este processamento."
            )
        try:
            return read_local_file_bytes(
                processamento.local_storage_integration,
                documento.source_reference,
            )
        except LocalStorageServiceError as exc:
            nome_pasta = processamento.local_storage_integration.nome
            raise DocumentSourcePreparationError(
                f"Esse agente esta configurado para acessar a pasta local '{nome_pasta}'. "
                f"Nao foi possivel ler o arquivo — verifique se a maquina que hospeda essa "
                f"pasta esta ligada e acessivel na rede. Detalhe: {exc}"
            ) from exc
    if documento.source_type == ProcessingInputSourceType.UPLOAD_AT_EXECUTION:
        if not documento.uploaded_file:
            raise DocumentSourcePreparationError(
                "O arquivo enviado na execucao nao esta mais disponivel."
            )
        with documento.uploaded_file.open("rb") as uploaded_stream:
            return uploaded_stream.read()
    raise DocumentSourcePreparationError("Nao foi possivel carregar o documento selecionado.")


def _prepare_google_drive_documents(processamento):
    if not processamento.folder_source_id:
        raise DocumentSourcePreparationError(
            "Selecione a pasta do Google Drive antes de materializar os documentos."
        )
    try:
        files = list_pdf_files_from_folder_source(processamento.folder_source)
    except GoogleDriveServiceError as exc:
        raise DocumentSourcePreparationError(str(exc)) from exc

    created = 0
    updated = 0
    for drive_file in files:
        documento = _find_existing_documento(
            processamento,
            source_type=ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
            source_reference=drive_file["id"],
        )
        defaults = {
            "nome_arquivo": drive_file["name"],
            "drive_file_id": drive_file["id"],
            "drive_path": drive_file.get("webViewLink", ""),
            "source_type": ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
            "source_reference": drive_file["id"],
            "mime_type": drive_file.get("mimeType", "application/pdf"),
            "checksum": drive_file.get("md5Checksum", ""),
        }
        if documento is None:
            DocumentoEntrada.objects.create(
                processamento=processamento,
                **defaults,
            )
            created += 1
        else:
            _update_documento_if_needed(documento, defaults)
            updated += 1
    return {"created": created, "updated": updated, "total": processamento.documentos.count()}


def _prepare_local_folder_documents(processamento):
    if not processamento.local_storage_integration_id:
        raise DocumentSourcePreparationError(
            "Selecione a integracao local autorizada antes de materializar os documentos."
        )
    try:
        files = list_pdf_files_from_relative_folder(
            processamento.local_storage_integration,
            processamento.local_relative_input_path,
        )
    except LocalStorageServiceError as exc:
        nome_pasta = processamento.local_storage_integration.nome
        raise DocumentSourcePreparationError(
            f"Esse agente esta configurado para acessar a pasta local '{nome_pasta}'. "
            f"Nao foi possivel acessar o caminho configurado — verifique se a maquina que "
            f"hospeda essa pasta esta ligada e acessivel na rede. Detalhe: {exc}"
        ) from exc

    created = 0
    updated = 0
    for local_file in files:
        documento = _find_existing_documento(
            processamento,
            source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            source_reference=local_file["relative_path"],
        )
        defaults = {
            "nome_arquivo": local_file["name"],
            "drive_file_id": "",
            "drive_path": local_file["absolute_path"],
            "source_type": ProcessingInputSourceType.LOCAL_FOLDER,
            "source_reference": local_file["relative_path"],
            "mime_type": local_file["mime_type"],
            "checksum": local_file["checksum"],
        }
        if documento is None:
            DocumentoEntrada.objects.create(processamento=processamento, **defaults)
            created += 1
        else:
            _update_documento_if_needed(documento, defaults)
            updated += 1
    return {"created": created, "updated": updated, "total": processamento.documentos.count()}


def _prepare_local_folder_documents_por_pasta(processamento):
    if not processamento.local_storage_integration_id:
        raise DocumentSourcePreparationError(
            "Selecione a integracao local autorizada antes de materializar os documentos."
        )
    try:
        subpastas = list_subfolders_from_relative_folder(
            processamento.local_storage_integration,
            processamento.local_relative_input_path,
        )
    except LocalStorageServiceError as exc:
        nome_pasta = processamento.local_storage_integration.nome
        raise DocumentSourcePreparationError(
            f"Esse agente esta configurado para acessar a pasta local '{nome_pasta}'. "
            f"Nao foi possivel acessar o caminho configurado — verifique se a maquina que "
            f"hospeda essa pasta esta ligada e acessivel na rede. Detalhe: {exc}"
        ) from exc

    if not subpastas:
        raise DocumentSourcePreparationError(
            "Nenhuma subpasta encontrada na pasta informada para o modo Lote por pasta."
        )

    created = 0
    updated = 0
    for subpasta in subpastas:
        try:
            files = list_pdf_files_from_subfolder(
                processamento.local_storage_integration,
                processamento.local_relative_input_path,
                subpasta,
            )
        except LocalStorageServiceError as exc:
            raise DocumentSourcePreparationError(str(exc)) from exc

        for local_file in files:
            documento = _find_existing_documento(
                processamento,
                source_type=ProcessingInputSourceType.LOCAL_FOLDER,
                source_reference=local_file["relative_path"],
            )
            defaults = {
                "nome_arquivo": local_file["name"],
                "drive_file_id": "",
                "drive_path": local_file["absolute_path"],
                "source_type": ProcessingInputSourceType.LOCAL_FOLDER,
                "source_reference": local_file["relative_path"],
                "mime_type": local_file["mime_type"],
                "checksum": local_file["checksum"],
                "pasta_grupo": subpasta.name,
            }
            if documento is None:
                DocumentoEntrada.objects.create(processamento=processamento, **defaults)
                created += 1
            else:
                _update_documento_if_needed(documento, defaults)
                updated += 1

    return {"created": created, "updated": updated, "total": processamento.documentos.count()}


def _prepare_google_drive_documents_por_pasta(processamento):
    if not processamento.folder_source_id:
        raise DocumentSourcePreparationError(
            "Selecione a pasta do Google Drive antes de materializar os documentos."
        )
    try:
        items = list_folder_contents_from_folder_source(processamento.folder_source)
    except GoogleDriveServiceError as exc:
        raise DocumentSourcePreparationError(str(exc)) from exc

    subpastas = [item for item in items if item["item_type"] == "pasta"]
    if not subpastas:
        raise DocumentSourcePreparationError(
            "Nenhuma subpasta encontrada na pasta do Google Drive para o modo Lote por pasta."
        )

    created = 0
    updated = 0
    drive_integration = processamento.folder_source.google_drive_integration

    for subpasta in subpastas:
        try:
            files = list_pdf_files_from_drive_folder_id(
                drive_integration,
                subpasta["drive_item_id"],
            )
        except GoogleDriveServiceError as exc:
            raise DocumentSourcePreparationError(str(exc)) from exc

        for drive_file in files:
            documento = _find_existing_documento(
                processamento,
                source_type=ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
                source_reference=drive_file["id"],
            )
            defaults = {
                "nome_arquivo": drive_file["name"],
                "drive_file_id": drive_file["id"],
                "drive_path": drive_file.get("webViewLink", ""),
                "source_type": ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
                "source_reference": drive_file["id"],
                "mime_type": drive_file.get("mimeType", "application/pdf"),
                "checksum": drive_file.get("md5Checksum", ""),
                "pasta_grupo": subpasta["nome"],
            }
            if documento is None:
                DocumentoEntrada.objects.create(processamento=processamento, **defaults)
                created += 1
            else:
                _update_documento_if_needed(documento, defaults)
                updated += 1

    return {"created": created, "updated": updated, "total": processamento.documentos.count()}


def _prepare_local_file_document(processamento):
    if not processamento.local_storage_integration_id:
        raise DocumentSourcePreparationError(
            "Selecione a integracao local autorizada antes de materializar o arquivo."
        )
    try:
        local_file = get_local_file_payload(
            processamento.local_storage_integration,
            processamento.local_relative_input_path,
        )
    except LocalStorageServiceError as exc:
        raise DocumentSourcePreparationError(str(exc)) from exc

    documento = _find_existing_documento(
        processamento,
        source_type=ProcessingInputSourceType.LOCAL_FILE,
        source_reference=local_file["relative_path"],
    )
    defaults = {
        "nome_arquivo": local_file["name"],
        "drive_file_id": "",
        "drive_path": local_file["absolute_path"],
        "source_type": ProcessingInputSourceType.LOCAL_FILE,
        "source_reference": local_file["relative_path"],
        "mime_type": local_file["mime_type"],
        "checksum": local_file["checksum"],
    }
    if documento is None:
        DocumentoEntrada.objects.create(processamento=processamento, **defaults)
        created = 1
        updated = 0
    else:
        _update_documento_if_needed(documento, defaults)
        created = 0
        updated = 1
    return {"created": created, "updated": updated, "total": processamento.documentos.count()}


def _prepare_upload_document(processamento):
    if not processamento.arquivo_execucao_upload:
        raise DocumentSourcePreparationError(
            "No modo de arquivo informado na execucao, envie um PDF antes de iniciar."
        )

    upload_name = Path(processamento.arquivo_execucao_upload.name).name
    if not upload_name.lower().endswith(".pdf"):
        raise DocumentSourcePreparationError(
            "No modo de upload em execucao, somente PDFs sao aceitos."
        )

    with processamento.arquivo_execucao_upload.open("rb") as upload_stream:
        upload_bytes = upload_stream.read()

    checksum = hashlib.md5(upload_bytes).hexdigest()
    source_reference = f"upload:{upload_name}:{checksum}"
    documento = _find_existing_documento(
        processamento,
        source_type=ProcessingInputSourceType.UPLOAD_AT_EXECUTION,
        source_reference=source_reference,
        pending_only=True,
    )
    if documento is None:
        ext = Path(upload_name).suffix.lower().lstrip(".")
        mime = MIME_TYPE_MAP.get(ext, "application/octet-stream")
        documento = DocumentoEntrada(
            processamento=processamento,
            nome_arquivo=upload_name,
            drive_file_id="",
            drive_path="upload interno",
            source_type=ProcessingInputSourceType.UPLOAD_AT_EXECUTION,
            source_reference=source_reference,
            mime_type=mime,
            checksum=checksum,
        )
        documento.uploaded_file.save(upload_name, ContentFile(upload_bytes), save=False)
        documento.save()
        created = 1
        updated = 0
    else:
        ext = Path(upload_name).suffix.lower().lstrip(".")
        documento.nome_arquivo = upload_name
        documento.mime_type = MIME_TYPE_MAP.get(ext, "application/octet-stream")
        documento.checksum = checksum
        documento.drive_path = "upload interno"
        documento.uploaded_file.save(upload_name, ContentFile(upload_bytes), save=False)
        documento.save()
        created = 0
        updated = 1

    temporary_field = processamento.arquivo_execucao_upload
    processamento.arquivo_execucao_upload = None
    with transaction.atomic():
        processamento.save(update_fields=["arquivo_execucao_upload", "updated_at"])
        temporary_field.delete(save=False)

    return {"created": created, "updated": updated, "total": processamento.documentos.count()}


def _find_existing_documento(
    processamento,
    *,
    source_type,
    source_reference,
    pending_only=False,
):
    queryset = DocumentoEntrada.objects.filter(
        processamento=processamento,
        source_type=source_type,
        source_reference=source_reference,
    )
    if pending_only:
        queryset = queryset.filter(status=DocumentStatus.PENDENTE)
    return queryset.order_by("-created_at").first()


def _update_documento_if_needed(documento, defaults):
    changed = False
    requires_reprocessing = False
    for field, value in defaults.items():
        current_value = getattr(documento, field)
        if current_value != value:
            setattr(documento, field, value)
            changed = True
            if field in {"nome_arquivo", "drive_path", "source_reference", "checksum"}:
                requires_reprocessing = True
    if documento.status == DocumentStatus.ERRO:
        documento.status = DocumentStatus.PENDENTE
        documento.mensagem_erro = ""
        documento.processado_em = None
        changed = True
    elif requires_reprocessing and documento.status == DocumentStatus.PROCESSADO:
        documento.status = DocumentStatus.PENDENTE
        documento.mensagem_erro = ""
        documento.processado_em = None
        changed = True
    if changed:
        documento.save()
