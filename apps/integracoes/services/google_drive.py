import json
from io import BytesIO
import re
from typing import Any

from django.utils.dateparse import parse_datetime


FOLDER_ID_PATTERNS = (
    re.compile(r"/folders/([a-zA-Z0-9_-]+)"),
    re.compile(r"[?&]id=([a-zA-Z0-9_-]+)"),
)
GOOGLE_DRIVE_FOLDER_MIME = "application/vnd.google-apps.folder"
PDF_MIME = "application/pdf"


class GoogleDriveServiceError(Exception):
    pass


def extract_folder_id_from_url(folder_url: str) -> str:
    if not folder_url:
        raise GoogleDriveServiceError("Informe a URL compartilhada da pasta do Google Drive.")

    for pattern in FOLDER_ID_PATTERNS:
        match = pattern.search(folder_url)
        if match:
            return match.group(1)

    raise GoogleDriveServiceError(
        "Nao foi possivel extrair o folder_id a partir da URL informada."
    )


def build_service_account_credentials(credentials_json: str):
    try:
        from google.oauth2 import service_account
    except ImportError as exc:
        raise GoogleDriveServiceError(
            "Dependencias do Google Drive nao instaladas. Instale google-auth e google-api-python-client."
        ) from exc

    try:
        payload = json.loads(credentials_json)
    except json.JSONDecodeError as exc:
        raise GoogleDriveServiceError("O JSON de credenciais do Google Drive e invalido.") from exc

    return service_account.Credentials.from_service_account_info(
        payload,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
    )


def build_drive_service(google_drive_integration):
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise GoogleDriveServiceError(
            "Dependencias do Google Drive nao instaladas. Instale google-auth e google-api-python-client."
        ) from exc

    credentials = build_service_account_credentials(
        google_drive_integration.credentials_json
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def get_folder_name(google_drive_integration, folder_id: str) -> str:
    service = build_drive_service(google_drive_integration)
    try:
        result = service.files().get(fileId=folder_id, fields="name").execute()
        return result.get("name", "")
    except Exception as exc:
        raise GoogleDriveServiceError(
            f"Falha ao obter o nome da pasta no Google Drive: {exc}"
        ) from exc


def fetch_folder_metadata(folder_source) -> dict[str, Any]:
    service = build_drive_service(folder_source.google_drive_integration)
    try:
        return (
            service.files()
            .get(fileId=folder_source.folder_id, fields="id,name,mimeType,webViewLink")
            .execute()
        )
    except Exception as exc:  # pragma: no cover
        raise GoogleDriveServiceError(
            f"Falha ao validar a pasta no Google Drive: {exc}"
        ) from exc


def _list_children_paginated(service, query: str, fields: str) -> list[dict[str, Any]]:
    """Pagina sobre `service.files().list()` até esgotar `nextPageToken`.

    A API do Drive devolve no máximo `pageSize` itens por chamada; sem
    percorrer `nextPageToken`, pastas com mais de 1000 itens eram
    truncadas silenciosamente (perdendo arquivos sem erro nenhum). Usado
    por toda listagem de conteúdo de pasta neste módulo — o chamador
    continua responsável por capturar exceções e traduzir a mensagem de
    erro para o contexto dele.
    """
    files: list[dict[str, Any]] = []
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=query,
                fields=f"nextPageToken,{fields}",
                pageSize=1000,
                pageToken=page_token,
            )
            .execute()
        )
        files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    return files


def list_pdf_files_from_folder_source(folder_source) -> list[dict[str, Any]]:
    service = build_drive_service(folder_source.google_drive_integration)
    query = (
        f"'{folder_source.folder_id}' in parents and trashed = false "
        f"and mimeType = '{PDF_MIME}'"
    )
    try:
        return _list_children_paginated(
            service,
            query,
            "files(id,name,mimeType,parents,webViewLink,md5Checksum)",
        )
    except Exception as exc:  # pragma: no cover
        raise GoogleDriveServiceError(
            f"Falha ao listar PDFs da pasta no Google Drive: {exc}"
        ) from exc


def list_subfolders_from_drive_folder_id(
    google_drive_integration, folder_id: str
) -> list[dict[str, Any]]:
    service = build_drive_service(google_drive_integration)
    query = f"'{folder_id}' in parents and trashed = false and mimeType = '{GOOGLE_DRIVE_FOLDER_MIME}'"
    try:
        files = _list_children_paginated(service, query, "files(id,name)")
    except Exception as exc:
        raise GoogleDriveServiceError(
            f"Falha ao listar subpastas no Google Drive: {exc}"
        ) from exc

    return sorted(
        [{"id": f["id"], "nome": f["name"]} for f in files],
        key=lambda x: x["nome"].lower(),
    )


def list_folder_contents_from_folder_source(folder_source) -> list[dict[str, Any]]:
    service = build_drive_service(folder_source.google_drive_integration)
    query = (
        f"'{folder_source.folder_id}' in parents and trashed = false and ("
        f"mimeType = '{PDF_MIME}' or "
        f"mimeType = '{GOOGLE_DRIVE_FOLDER_MIME}')"
    )
    try:
        drive_items = _list_children_paginated(
            service,
            query,
            (
                "files("
                "id,"
                "name,"
                "mimeType,"
                "parents,"
                "webViewLink,"
                "md5Checksum,"
                "modifiedTime,"
                "size"
                ")"
            ),
        )
    except Exception as exc:  # pragma: no cover
        raise GoogleDriveServiceError(
            f"Falha ao listar o conteudo da pasta no Google Drive: {exc}"
        ) from exc

    normalized_items = []
    for drive_item in drive_items:
        mime_type = drive_item.get("mimeType", "")
        if mime_type == GOOGLE_DRIVE_FOLDER_MIME:
            item_type = "pasta"
        elif mime_type == PDF_MIME:
            item_type = "pdf"
        else:
            item_type = "outro"

        size_value = drive_item.get("size")
        normalized_items.append(
            {
                "drive_item_id": drive_item["id"],
                "nome": drive_item["name"],
                "mime_type": mime_type,
                "item_type": item_type,
                "parent_drive_id": (drive_item.get("parents") or [""])[0],
                "web_view_link": drive_item.get("webViewLink", ""),
                "checksum": drive_item.get("md5Checksum", ""),
                "modified_at": parse_datetime(drive_item["modifiedTime"])
                if drive_item.get("modifiedTime")
                else None,
                "size_bytes": int(size_value) if size_value else None,
                "disponivel_para_ia": item_type == "pdf",
            }
        )

    return sorted(
        normalized_items,
        key=lambda item: (item["item_type"] != "pasta", item["nome"].lower()),
    )


def list_pdf_files_from_drive_folder_id(google_drive_integration, folder_id: str) -> list[dict]:
    service = build_drive_service(google_drive_integration)
    query = f"'{folder_id}' in parents and trashed = false and mimeType = '{PDF_MIME}'"
    try:
        return _list_children_paginated(
            service, query, "files(id,name,mimeType,parents,webViewLink,md5Checksum)"
        )
    except Exception as exc:  # pragma: no cover
        raise GoogleDriveServiceError(
            f"Falha ao listar PDFs da subpasta no Google Drive: {exc}"
        ) from exc


def list_pdf_files_recursive_from_drive_folder_id(
    google_drive_integration, root_folder_id: str, *, max_files: int | None = None
) -> list[dict[str, Any]]:
    """Varre `root_folder_id` e TODAS as subpastas abaixo dele, em qualquer
    profundidade, devolvendo os PDFs encontrados.

    Cada item devolvido tem os mesmos campos de `list_pdf_files_from_folder_source`
    mais `relative_path` (caminho relativo a `root_folder_id`, com '/' como
    separador — ex.: "2024/Janeiro/contrato.pdf") — usado para dedup,
    ordenacao deterministica e (no modo "Lote por sub-pastas") para derivar o
    grupo do documento a partir da pasta-mae.

    `max_files`, se informado, interrompe a varredura (BFS) assim que esse
    total de PDFs for coletado, mesmo com pastas ainda nao visitadas — evita
    percorrer arvores muito grandes por completo quando so um lote limitado
    de arquivos sera processado nesta execucao (ver
    AgenteConfiguracaoOperacional.include_subfolders e
    ConfiguracaoGeral.max_pdfs_lote_subpastas).
    """
    service = build_drive_service(google_drive_integration)
    collected: list[dict[str, Any]] = []
    pending_folders = [(root_folder_id, "")]  # (folder_id, prefixo_relativo)

    while pending_folders:
        folder_id, prefix = pending_folders.pop(0)
        query = (
            f"'{folder_id}' in parents and trashed = false and ("
            f"mimeType = '{PDF_MIME}' or mimeType = '{GOOGLE_DRIVE_FOLDER_MIME}')"
        )
        try:
            children = _list_children_paginated(
                service,
                query,
                "files(id,name,mimeType,parents,webViewLink,md5Checksum)",
            )
        except Exception as exc:  # pragma: no cover
            raise GoogleDriveServiceError(
                f"Falha ao listar subpastas no Google Drive: {exc}"
            ) from exc

        # Subpastas primeiro (na ordem em que a API devolveu), depois PDFs —
        # nao muda o resultado final, so a ordem em que pastas sao
        # enfileiradas para visita.
        for child in children:
            if child.get("mimeType") == GOOGLE_DRIVE_FOLDER_MIME:
                pending_folders.append((child["id"], f"{prefix}{child['name']}/"))

        for child in children:
            if child.get("mimeType") == PDF_MIME:
                collected.append({**child, "relative_path": f"{prefix}{child['name']}"})
                if max_files and len(collected) >= max_files:
                    return collected

    return collected


def download_drive_file_bytes(google_drive_integration, drive_file_id: str) -> bytes:
    if not drive_file_id:
        raise GoogleDriveServiceError("Informe o identificador do arquivo do Google Drive.")

    service = build_drive_service(google_drive_integration)
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise GoogleDriveServiceError(
            "Dependencias do Google Drive nao instaladas. Instale google-auth e google-api-python-client."
        ) from exc

    request = service.files().get_media(fileId=drive_file_id)
    output = BytesIO()
    downloader = MediaIoBaseDownload(output, request)

    try:
        done = False
        while not done:
            _, done = downloader.next_chunk()
    except Exception as exc:  # pragma: no cover
        raise GoogleDriveServiceError(
            f"Falha ao baixar o arquivo PDF do Google Drive: {exc}"
        ) from exc

    return output.getvalue()
