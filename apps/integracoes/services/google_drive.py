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


def list_pdf_files_from_folder_source(folder_source) -> list[dict[str, Any]]:
    service = build_drive_service(folder_source.google_drive_integration)
    query = (
        f"'{folder_source.folder_id}' in parents and trashed = false "
        f"and mimeType = '{PDF_MIME}'"
    )
    try:
        response = (
            service.files()
            .list(
                q=query,
                fields="files(id,name,mimeType,parents,webViewLink,md5Checksum)",
                pageSize=1000,
            )
            .execute()
        )
    except Exception as exc:  # pragma: no cover
        raise GoogleDriveServiceError(
            f"Falha ao listar PDFs da pasta no Google Drive: {exc}"
        ) from exc

    return response.get("files", [])


def list_folder_contents_from_folder_source(folder_source) -> list[dict[str, Any]]:
    service = build_drive_service(folder_source.google_drive_integration)
    query = (
        f"'{folder_source.folder_id}' in parents and trashed = false and ("
        f"mimeType = '{PDF_MIME}' or "
        f"mimeType = '{GOOGLE_DRIVE_FOLDER_MIME}')"
    )
    try:
        response = (
            service.files()
            .list(
                q=query,
                fields=(
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
                pageSize=1000,
            )
            .execute()
        )
    except Exception as exc:  # pragma: no cover
        raise GoogleDriveServiceError(
            f"Falha ao listar o conteudo da pasta no Google Drive: {exc}"
        ) from exc

    normalized_items = []
    for drive_item in response.get("files", []):
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
