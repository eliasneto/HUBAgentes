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
    list_pdf_files_recursive_from_drive_folder_id,
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


def _deve_incluir_subpastas(processamento):
    """True quando o agente deste processamento tem
    AgenteConfiguracaoOperacional.include_subfolders ligado — le PDFs de
    todas as subpastas abaixo da raiz configurada, em qualquer
    profundidade, em vez de so os arquivos soltos na raiz (ou, no modo
    Lote por pasta, so 1 nivel de subpastas)."""
    agente = getattr(processamento, "agente", None)
    if agente is None:
        return False
    configuracao = getattr(agente, "configuracao_operacional", None)
    return bool(configuracao and configuracao.include_subfolders)


def _limite_documentos_novos_por_lote():
    """Maximo de DocumentoEntrada NOVOS (nao contando os ja processados
    antes, que sao pulados de graca) criados numa unica execucao quando o
    agente le subpastas recursivamente — evita que uma arvore de pastas
    muito grande produza uma execucao longa demais e estoure o timeout do
    servidor. None = sem limite. So consultado quando
    _deve_incluir_subpastas() e True; agentes com o toggle desligado nunca
    passam por aqui."""
    from apps.core.models import ConfiguracaoGeral

    limite = ConfiguracaoGeral.obter().max_pdfs_lote_subpastas
    return limite or None


def _margem_varredura_drive(limite):
    """Teto de PDFs que a varredura recursiva do Google Drive pode coletar
    antes de parar (ver list_pdf_files_recursive_from_drive_folder_id).
    Maior que `limite` de proposito: parte dos arquivos coletados pode já
    ter sido processada antes (dedup) e não conta para o lote, então
    coletar só `limite` itens arriscaria sobrar poucos ou nenhum arquivo
    novo mesmo com mais PDFs disponíveis na árvore. None = varredura
    completa (sem limite configurado)."""
    if limite is None:
        return None
    return max(limite * 4, 100)


def _pasta_mae_do_caminho(relative_path):
    """Deriva a pasta que contem o arquivo a partir do caminho relativo
    (separador '/'), para usar como pasta_grupo: evita que arquivos de
    mesmo nome em subpastas diferentes colidam no dedup de "ja processado
    antes" (que hoje identifica arquivo por nome — ver
    _arquivo_ja_processado_em_outra_execucao) e, no modo Lote por pasta, e
    o proprio agrupamento. Retorna "" quando o arquivo esta direto na raiz
    (sem '/' no caminho)."""
    if "/" not in relative_path:
        return ""
    return relative_path.rsplit("/", 1)[0]


class _LimiteLoteTracker:
    """Acompanha quantos documentos NOVOS (que nao existiam antes e nao
    foram pulados por dedup) foram criados nesta execucao, para
    interromper a descoberta ao atingir o limite de lote configurado.
    Arquivos ja processados antes continuam sendo pulados de graca (nao
    consomem o limite) — so a criacao de DocumentoEntrada novo conta."""

    def __init__(self, limite):
        self.limite = limite  # None = sem limite
        self.novos = 0
        self.atingiu_limite = False

    def pode_criar_mais(self):
        if self.limite is not None and self.novos >= self.limite:
            self.atingiu_limite = True
            return False
        return True

    def registrar_criado(self):
        self.novos += 1


def _resolver_pasta_raiz_efetiva_drive(processamento):
    """Raiz efetiva para a varredura recursiva do Google Drive: a subpasta
    fixa configurada no agente (default_gdrive_subfolder_path), se houver,
    senao a pasta do folder_source do processamento — mesma resolucao que
    o modo individual/grupo unico ja faz hoje para o 1o nivel."""
    agente = getattr(processamento, "agente", None)
    if agente is not None:
        try:
            path = agente.configuracao_operacional.default_gdrive_subfolder_path or []
            if path:
                return path[-1]["id"]
        except Exception:
            pass
    return processamento.folder_source.folder_id


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
    incluir_subpastas = _deve_incluir_subpastas(processamento)
    limite = _limite_documentos_novos_por_lote() if incluir_subpastas else None
    try:
        if incluir_subpastas:
            files = list_pdf_files_recursive_from_drive_folder_id(
                processamento.folder_source.google_drive_integration,
                _resolver_pasta_raiz_efetiva_drive(processamento),
                max_files=_margem_varredura_drive(limite),
            )
        else:
            subfolder_drive_id = None
            agente = getattr(processamento, "agente", None)
            if agente is not None:
                try:
                    path = agente.configuracao_operacional.default_gdrive_subfolder_path or []
                    if path:
                        subfolder_drive_id = path[-1]["id"]
                except Exception:
                    pass

            if subfolder_drive_id:
                files = list_pdf_files_from_drive_folder_id(
                    processamento.folder_source.google_drive_integration,
                    subfolder_drive_id,
                )
            else:
                files = list_pdf_files_from_folder_source(processamento.folder_source)
    except GoogleDriveServiceError as exc:
        raise DocumentSourcePreparationError(str(exc)) from exc

    tracker = _LimiteLoteTracker(limite)
    created = 0
    updated = 0
    ignorados = 0
    for drive_file in files:
        pasta_grupo = (
            _pasta_mae_do_caminho(drive_file["relative_path"]) if incluir_subpastas else ""
        )
        documento = _find_existing_documento(
            processamento,
            source_type=ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
            source_reference=drive_file["id"],
        )
        if documento is None and _arquivo_ja_processado_anteriormente(
            processamento, drive_file["name"], pasta_grupo=pasta_grupo
        ):
            ignorados += 1
            continue
        if documento is None and not tracker.pode_criar_mais():
            break
        defaults = {
            "nome_arquivo": drive_file["name"],
            "drive_file_id": drive_file["id"],
            "drive_path": drive_file.get("webViewLink", ""),
            "source_type": ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
            "source_reference": drive_file["id"],
            "mime_type": drive_file.get("mimeType", "application/pdf"),
            "checksum": drive_file.get("md5Checksum", ""),
            "pasta_grupo": pasta_grupo,
        }
        if documento is None:
            DocumentoEntrada.objects.create(
                processamento=processamento,
                **defaults,
            )
            created += 1
            tracker.registrar_criado()
        else:
            _update_documento_if_needed(documento, defaults)
            updated += 1
    return {
        "created": created,
        "updated": updated,
        "total": processamento.documentos.count(),
        "ignorados": ignorados,
        "atingiu_limite_lote": tracker.atingiu_limite,
    }


def _prepare_local_folder_documents(processamento):
    if not processamento.local_storage_integration_id:
        raise DocumentSourcePreparationError(
            "Selecione a integracao local autorizada antes de materializar os documentos."
        )
    incluir_subpastas = _deve_incluir_subpastas(processamento)
    try:
        files = list_pdf_files_from_relative_folder(
            processamento.local_storage_integration,
            processamento.local_relative_input_path,
            force_recursive=incluir_subpastas,
        )
    except LocalStorageServiceError as exc:
        nome_pasta = processamento.local_storage_integration.nome
        raise DocumentSourcePreparationError(
            f"Esse agente esta configurado para acessar a pasta local '{nome_pasta}'. "
            f"Nao foi possivel acessar o caminho configurado — verifique se a maquina que "
            f"hospeda essa pasta esta ligada e acessivel na rede. Detalhe: {exc}"
        ) from exc

    tracker = _LimiteLoteTracker(
        _limite_documentos_novos_por_lote() if incluir_subpastas else None
    )
    created = 0
    updated = 0
    ignorados = 0
    for local_file in files:
        pasta_grupo = (
            _pasta_mae_do_caminho(local_file["relative_path"]) if incluir_subpastas else ""
        )
        documento = _find_existing_documento(
            processamento,
            source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            source_reference=local_file["relative_path"],
        )
        if documento is None and _arquivo_local_ja_processado_anteriormente(
            processamento, local_file["name"], pasta_grupo=pasta_grupo
        ):
            ignorados += 1
            continue
        if documento is None and not tracker.pode_criar_mais():
            break
        defaults = {
            "nome_arquivo": local_file["name"],
            "drive_file_id": "",
            "drive_path": local_file["absolute_path"],
            "source_type": ProcessingInputSourceType.LOCAL_FOLDER,
            "source_reference": local_file["relative_path"],
            "mime_type": local_file["mime_type"],
            "checksum": local_file["checksum"],
            "pasta_grupo": pasta_grupo,
        }
        if documento is None:
            DocumentoEntrada.objects.create(processamento=processamento, **defaults)
            created += 1
            tracker.registrar_criado()
        else:
            _update_documento_if_needed(documento, defaults)
            updated += 1
    return {
        "created": created,
        "updated": updated,
        "total": processamento.documentos.count(),
        "ignorados": ignorados,
        "atingiu_limite_lote": tracker.atingiu_limite,
    }


def _prepare_local_folder_documents_por_pasta(processamento):
    if not processamento.local_storage_integration_id:
        raise DocumentSourcePreparationError(
            "Selecione a integracao local autorizada antes de materializar os documentos."
        )
    if _deve_incluir_subpastas(processamento):
        return _prepare_local_folder_documents_por_pasta_recursivo(processamento)
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
    ignorados = 0
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
            if documento is None and _arquivo_local_ja_processado_anteriormente(
                processamento, local_file["name"], pasta_grupo=subpasta.name
            ):
                ignorados += 1
                continue
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

    return {
        "created": created,
        "updated": updated,
        "total": processamento.documentos.count(),
        "ignorados": ignorados,
    }


def _prepare_local_folder_documents_por_pasta_recursivo(processamento):
    """Variante de `_prepare_local_folder_documents_por_pasta` para
    AgenteConfiguracaoOperacional.include_subfolders=True: em vez de
    enumerar so 1 nivel de subpastas, varre a arvore inteira e agrupa cada
    arquivo pela sua pasta-mae (relative_path sem o nome do arquivo) — uma
    generalizacao direta do agrupamento de 1 nivel para profundidade
    arbitraria. Mantem a mesma regra de negocio de excluir arquivos soltos
    direto na raiz."""
    try:
        files = list_pdf_files_from_relative_folder(
            processamento.local_storage_integration,
            processamento.local_relative_input_path,
            force_recursive=True,
        )
    except LocalStorageServiceError as exc:
        nome_pasta = processamento.local_storage_integration.nome
        raise DocumentSourcePreparationError(
            f"Esse agente esta configurado para acessar a pasta local '{nome_pasta}'. "
            f"Nao foi possivel acessar o caminho configurado — verifique se a maquina que "
            f"hospeda essa pasta esta ligada e acessivel na rede. Detalhe: {exc}"
        ) from exc

    arquivos_em_subpasta = [f for f in files if "/" in f["relative_path"]]
    if not arquivos_em_subpasta:
        raise DocumentSourcePreparationError(
            "Nenhuma subpasta encontrada na pasta informada para o modo Lote por pasta."
        )

    tracker = _LimiteLoteTracker(_limite_documentos_novos_por_lote())
    created = 0
    updated = 0
    ignorados = 0
    for local_file in arquivos_em_subpasta:
        pasta_grupo = _pasta_mae_do_caminho(local_file["relative_path"])
        documento = _find_existing_documento(
            processamento,
            source_type=ProcessingInputSourceType.LOCAL_FOLDER,
            source_reference=local_file["relative_path"],
        )
        if documento is None and _arquivo_local_ja_processado_anteriormente(
            processamento, local_file["name"], pasta_grupo=pasta_grupo
        ):
            ignorados += 1
            continue
        if documento is None and not tracker.pode_criar_mais():
            break
        defaults = {
            "nome_arquivo": local_file["name"],
            "drive_file_id": "",
            "drive_path": local_file["absolute_path"],
            "source_type": ProcessingInputSourceType.LOCAL_FOLDER,
            "source_reference": local_file["relative_path"],
            "mime_type": local_file["mime_type"],
            "checksum": local_file["checksum"],
            "pasta_grupo": pasta_grupo,
        }
        if documento is None:
            DocumentoEntrada.objects.create(processamento=processamento, **defaults)
            created += 1
            tracker.registrar_criado()
        else:
            _update_documento_if_needed(documento, defaults)
            updated += 1

    return {
        "created": created,
        "updated": updated,
        "total": processamento.documentos.count(),
        "ignorados": ignorados,
        "atingiu_limite_lote": tracker.atingiu_limite,
    }


def _prepare_google_drive_documents_por_pasta(processamento):
    if not processamento.folder_source_id:
        raise DocumentSourcePreparationError(
            "Selecione a pasta do Google Drive antes de materializar os documentos."
        )
    if _deve_incluir_subpastas(processamento):
        return _prepare_google_drive_documents_por_pasta_recursivo(processamento)
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
    ignorados = 0
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
            if documento is None and _arquivo_ja_processado_anteriormente(
                processamento, drive_file["name"], pasta_grupo=subpasta["nome"]
            ):
                ignorados += 1
                continue
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

    return {
        "created": created,
        "updated": updated,
        "total": processamento.documentos.count(),
        "ignorados": ignorados,
    }


def _prepare_google_drive_documents_por_pasta_recursivo(processamento):
    """Variante de `_prepare_google_drive_documents_por_pasta` para
    AgenteConfiguracaoOperacional.include_subfolders=True: varre a arvore
    inteira a partir da raiz efetiva (ver _resolver_pasta_raiz_efetiva_drive)
    e agrupa cada arquivo pela sua pasta-mae, em qualquer profundidade —
    generalizacao do agrupamento de 1 nivel. Mantem a mesma regra de negocio
    de excluir arquivos soltos direto na raiz."""
    limite = _limite_documentos_novos_por_lote()
    try:
        files = list_pdf_files_recursive_from_drive_folder_id(
            processamento.folder_source.google_drive_integration,
            _resolver_pasta_raiz_efetiva_drive(processamento),
            max_files=_margem_varredura_drive(limite),
        )
    except GoogleDriveServiceError as exc:
        raise DocumentSourcePreparationError(str(exc)) from exc

    arquivos_em_subpasta = [f for f in files if "/" in f["relative_path"]]
    if not arquivos_em_subpasta:
        raise DocumentSourcePreparationError(
            "Nenhuma subpasta encontrada na pasta do Google Drive para o modo Lote por pasta."
        )

    tracker = _LimiteLoteTracker(limite)
    created = 0
    updated = 0
    ignorados = 0
    for drive_file in arquivos_em_subpasta:
        pasta_grupo = _pasta_mae_do_caminho(drive_file["relative_path"])
        documento = _find_existing_documento(
            processamento,
            source_type=ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
            source_reference=drive_file["id"],
        )
        if documento is None and _arquivo_ja_processado_anteriormente(
            processamento, drive_file["name"], pasta_grupo=pasta_grupo
        ):
            ignorados += 1
            continue
        if documento is None and not tracker.pode_criar_mais():
            break
        defaults = {
            "nome_arquivo": drive_file["name"],
            "drive_file_id": drive_file["id"],
            "drive_path": drive_file.get("webViewLink", ""),
            "source_type": ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
            "source_reference": drive_file["id"],
            "mime_type": drive_file.get("mimeType", "application/pdf"),
            "checksum": drive_file.get("md5Checksum", ""),
            "pasta_grupo": pasta_grupo,
        }
        if documento is None:
            DocumentoEntrada.objects.create(processamento=processamento, **defaults)
            created += 1
            tracker.registrar_criado()
        else:
            _update_documento_if_needed(documento, defaults)
            updated += 1

    return {
        "created": created,
        "updated": updated,
        "total": processamento.documentos.count(),
        "ignorados": ignorados,
        "atingiu_limite_lote": tracker.atingiu_limite,
    }


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
    _extensoes_ok = {"pdf", "txt", "csv", "png", "jpg", "jpeg", "xlsx"}
    _ext = upload_name.lower().rsplit(".", 1)[-1] if "." in upload_name else ""
    if _ext not in _extensoes_ok:
        raise DocumentSourcePreparationError(
            f"Extensao '.{_ext}' nao suportada. Use: {', '.join(sorted(_extensoes_ok))}"
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


def _arquivo_ja_processado_em_outra_execucao(
    processamento, *, source_type, nome_arquivo, pasta_grupo, escopo_filtros
):
    """
    Nucleo comum do rastreamento de "arquivo ja processado" entre execucoes
    (Processamentos) diferentes de um mesmo agente sobre uma mesma pasta —
    usado tanto para pasta do Google Drive quanto para pasta local (ver
    _arquivo_ja_processado_anteriormente e _arquivo_local_ja_processado_anteriormente).

    Identidade = NOME do arquivo (regra de negocio: se o nome nao mudar, nao
    reprocessa, mesmo que o conteudo do arquivo tenha mudado na origem).
    Nunca se aplica a execucao pontual de arquivo (upload_at_execution/
    local_file nao chamam esta funcao). Pode ser ignorado marcando
    `forcar_reprocessamento` no Processamento (checkbox "Reprocessar
    arquivos ja executados" na tela de execucao).
    """
    if processamento.forcar_reprocessamento:
        return False
    return (
        DocumentoEntrada.objects.filter(
            processamento__agente_id=processamento.agente_id,
            source_type=source_type,
            nome_arquivo=nome_arquivo,
            pasta_grupo=pasta_grupo,
            status=DocumentStatus.PROCESSADO,
            **escopo_filtros,
        )
        .exclude(processamento_id=processamento.id)
        .exists()
    )


def _arquivo_ja_processado_anteriormente(processamento, nome_arquivo, pasta_grupo=""):
    """
    Variante para origem Google Drive — escopo (agente, folder_source).

    Limitacao conhecida: quando o agente usa uma subpasta fixa dentro do
    folder_source (default_gdrive_subfolder_path, modo nao-lote), essa
    subpasta nao entra na chave — so (agente, folder_source, nome_arquivo).
    Trocar a subpasta configurada no agente mantendo o mesmo folder_source
    pode fazer um arquivo de mesmo nome na nova subpasta ser incorretamente
    tratado como ja processado. Reconfiguracao rara; aceito como trade-off.
    """
    return _arquivo_ja_processado_em_outra_execucao(
        processamento,
        source_type=ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER,
        nome_arquivo=nome_arquivo,
        pasta_grupo=pasta_grupo,
        escopo_filtros={"processamento__folder_source_id": processamento.folder_source_id},
    )


def _arquivo_local_ja_processado_anteriormente(processamento, nome_arquivo, pasta_grupo=""):
    """
    Variante para origem Pasta Local — escopo (agente, local_storage_integration,
    local_relative_input_path).
    """
    return _arquivo_ja_processado_em_outra_execucao(
        processamento,
        source_type=ProcessingInputSourceType.LOCAL_FOLDER,
        nome_arquivo=nome_arquivo,
        pasta_grupo=pasta_grupo,
        escopo_filtros={
            "processamento__local_storage_integration_id": (
                processamento.local_storage_integration_id
            ),
            "processamento__local_relative_input_path": (
                processamento.local_relative_input_path
            ),
        },
    )


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
        # Só erros transitórios (provedor indisponível, timeout) são reprocessados
        # automaticamente. Erros que exigem intervenção manual (chave inválida,
        # documento grande demais, saída inválida) permanecem em ERRO — repetir
        # não resolveria. Exceção: se o arquivo de origem mudou (conteúdo novo),
        # o erro anterior pode não valer mais, então reprocessa mesmo assim.
        if documento.erro_reprocessavel or requires_reprocessing:
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
