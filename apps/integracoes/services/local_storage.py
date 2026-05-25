import hashlib
from pathlib import Path


class LocalStorageServiceError(Exception):
    pass


def validate_local_storage_integration(local_storage_integration):
    base_path = Path(local_storage_integration.base_path).expanduser()
    if not base_path.exists():
        raise LocalStorageServiceError(
            "A raiz local autorizada nao existe no filesystem do servidor."
        )
    if not base_path.is_dir():
        raise LocalStorageServiceError(
            "A raiz local autorizada precisa apontar para uma pasta do servidor."
        )
    return base_path.resolve()


def resolve_local_relative_path(local_storage_integration, relative_path):
    base_path = validate_local_storage_integration(local_storage_integration)
    normalized_relative = str(relative_path or "").strip().replace("\\", "/").strip("/")
    target_path = (base_path / normalized_relative).resolve()
    try:
        target_path.relative_to(base_path)
    except ValueError as exc:
        raise LocalStorageServiceError(
            "O caminho informado esta fora da raiz local autorizada."
        ) from exc
    return target_path


def list_pdf_files_from_relative_folder(local_storage_integration, relative_path):
    target_folder = resolve_local_relative_path(local_storage_integration, relative_path)
    if not target_folder.exists():
        raise LocalStorageServiceError("A pasta local informada nao existe.")
    if not target_folder.is_dir():
        raise LocalStorageServiceError("O caminho informado precisa apontar para uma pasta.")

    patterns = ["*.pdf"]
    files = []
    for pattern in patterns:
        iterator = (
            target_folder.rglob(pattern)
            if local_storage_integration.recursive_scan
            else target_folder.glob(pattern)
        )
        files.extend(iterator)

    normalized_files = []
    for file_path in sorted({file.resolve() for file in files}, key=lambda item: str(item).lower()):
        if not file_path.is_file():
            continue
        normalized_files.append(_build_local_file_payload(file_path, target_folder, local_storage_integration))
    return normalized_files


def get_local_file_payload(local_storage_integration, relative_path):
    target_file = resolve_local_relative_path(local_storage_integration, relative_path)
    if not target_file.exists():
        raise LocalStorageServiceError("O arquivo local informado nao existe.")
    if not target_file.is_file():
        raise LocalStorageServiceError("O caminho informado precisa apontar para um arquivo.")
    if target_file.suffix.lower() != ".pdf":
        raise LocalStorageServiceError("Somente arquivos PDF sao aceitos como entrada local.")
    return _build_local_file_payload(
        target_file,
        validate_local_storage_integration(local_storage_integration),
        local_storage_integration,
    )


def read_local_file_bytes(local_storage_integration, relative_path):
    target_file = resolve_local_relative_path(local_storage_integration, relative_path)
    if not target_file.exists() or not target_file.is_file():
        raise LocalStorageServiceError("O arquivo local solicitado nao esta disponivel.")
    return target_file.read_bytes()


def _build_local_file_payload(file_path, base_path, local_storage_integration):
    try:
        relative_reference = str(file_path.relative_to(base_path)).replace("\\", "/")
    except ValueError:
        relative_reference = file_path.name

    file_bytes = file_path.read_bytes()
    checksum = hashlib.md5(file_bytes).hexdigest()
    return {
        "name": file_path.name,
        "relative_path": relative_reference,
        "absolute_path": str(file_path),
        "mime_type": "application/pdf",
        "checksum": checksum,
        "size_bytes": len(file_bytes),
        "recursive_scan": local_storage_integration.recursive_scan,
    }
