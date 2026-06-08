from dataclasses import dataclass
from datetime import datetime

from django.db.models import Count, Q
from django.urls import reverse

from apps.integracoes.models import (
    AIProviderIntegration,
    GoogleDriveIntegration,
    GoogleDriveFolderSource,
    LocalStorageIntegration,
)


def _caminho_para_exibicao(base_path: str) -> str:
    if not base_path.startswith("/app/entradas"):
        return base_path
    remainder = base_path[len("/app/entradas"):].lstrip("/")
    win_path = "C:\\HubAgentes"
    return win_path + "\\" + remainder.replace("/", "\\") if remainder else win_path


@dataclass(frozen=True)
class GoogleDriveFonteResumo:
    id: int
    nome: str
    status: str
    integracao: str
    pasta: str
    total_itens: int
    total_pdfs: int
    total_disponiveis_ia: int
    ultima_validacao: datetime | None


@dataclass(frozen=True)
class LocalStorageFonteResumo:
    id: int
    nome: str
    status: str
    base_path: str
    extensoes: str
    leitura_recursiva: bool
    ultima_validacao: datetime | None
    criado_por: str
    criado_em: datetime | None
    pode_gerenciar: bool = False
    pode_excluir: bool = False


@dataclass(frozen=True)
class FontesDocumentosResumo:
    google_drive: list[GoogleDriveFonteResumo]
    storage_local: list[LocalStorageFonteResumo]

    @property
    def total_fontes(self) -> int:
        return len(self.google_drive) + len(self.storage_local)

    @property
    def total_google_drive(self) -> int:
        return len(self.google_drive)

    @property
    def total_storage_local(self) -> int:
        return len(self.storage_local)


@dataclass(frozen=True)
class IAIntegracaoResumo:
    id: int
    nome: str
    provedor: str
    status: str
    modelo_padrao: str
    timeout_seconds: int
    ultima_validacao: datetime | None
    ultima_conexao: datetime | None
    ultimo_erro: str
    validar_url: str


@dataclass(frozen=True)
class GoogleDriveIntegracaoResumo:
    id: int
    nome: str
    status: str
    modo_autenticacao: str
    service_account_email: str
    extensoes: str
    ultima_conexao: datetime | None
    total_fontes: int
    ultimo_erro: str
    validar_url: str


@dataclass(frozen=True)
class LocalStorageIntegracaoResumo:
    id: int
    nome: str
    status: str
    base_path: str
    extensoes: str
    leitura_recursiva: bool
    ultima_validacao: datetime | None
    ultimo_erro: str
    validar_url: str
    criado_por: str


@dataclass(frozen=True)
class IntegracoesPortalResumo:
    ia: list[IAIntegracaoResumo]
    google_drive: list[GoogleDriveIntegracaoResumo]
    storage_local: list[LocalStorageIntegracaoResumo]

    @property
    def total_integracoes(self) -> int:
        return len(self.ia) + len(self.google_drive) + len(self.storage_local)

    @property
    def total_ia(self) -> int:
        return len(self.ia)

    @property
    def total_google_drive(self) -> int:
        return len(self.google_drive)

    @property
    def total_storage_local(self) -> int:
        return len(self.storage_local)


def listar_fontes_documentos_para_portal(usuario=None) -> FontesDocumentosResumo:
    """Retorna somente dados operacionais seguros das fontes de documentos."""
    fontes_google_drive = (
        GoogleDriveFolderSource.objects.select_related("google_drive_integration")
        .annotate(
            total_itens=Count("synced_items"),
            total_pdfs=Count("synced_items", filter=Q(synced_items__item_type="pdf")),
            total_disponiveis_ia=Count(
                "synced_items",
                filter=Q(synced_items__disponivel_para_ia=True),
            ),
        )
        .order_by("nome")
    )

    fontes_locais_qs = LocalStorageIntegration.objects.select_related("created_by").prefetch_related("membros")
    is_admin = bool(usuario and (usuario.is_superuser or usuario.groups.filter(name="administrador").exists()))
    if usuario:
        if is_admin:
            # Admin vê todas as pastas do sistema (pessoais de todos + todas compartilhadas)
            pass
        else:
            # Usuário comum: só a pasta pessoal própria + compartilhadas onde foi adicionado
            pasta_pessoal = Q(created_by=usuario, compartilhada=False)
            pastas_compartilhadas = Q(compartilhada=True, usuarios_autorizados=usuario)
            fontes_locais_qs = fontes_locais_qs.filter(pasta_pessoal | pastas_compartilhadas)
    fontes_locais = fontes_locais_qs.order_by("nome")

    def _pode_gerenciar(fonte):
        if not usuario:
            return False
        # Pasta pessoal: só o dono, nunca o admin de outro
        if not fonte.compartilhada:
            return fonte.created_by_id == usuario.pk
        # Pasta compartilhada: admin pode sempre; membros com escrita também
        if is_admin:
            return True
        from apps.integracoes.models import PastaCompartilhadaUsuario, PermissaoPasta
        membro = next((m for m in fonte.membros.all() if m.usuario_id == usuario.pk), None)
        return membro is not None and membro.permissao == PermissaoPasta.ESCRITA

    return FontesDocumentosResumo(
        google_drive=[
            GoogleDriveFonteResumo(
                id=fonte.pk,
                nome=fonte.nome,
                status=fonte.get_status_display(),
                integracao=str(fonte.google_drive_integration),
                pasta=fonte.folder_display_name or fonte.nome,
                total_itens=fonte.total_itens,
                total_pdfs=fonte.total_pdfs,
                total_disponiveis_ia=fonte.total_disponiveis_ia,
                ultima_validacao=fonte.last_validated_at,
            )
            for fonte in fontes_google_drive
        ],
        storage_local=[
            LocalStorageFonteResumo(
                id=fonte.pk,
                nome=fonte.nome,
                status=fonte.get_status_display(),
                base_path=_caminho_para_exibicao(fonte.base_path),
                extensoes=", ".join(fonte.allowed_extensions or []),
                leitura_recursiva=fonte.recursive_scan,
                ultima_validacao=fonte.last_validated_at,
                criado_por=(
                    fonte.created_by.get_full_name() or fonte.created_by.username
                ) if fonte.created_by else "—",
                criado_em=fonte.created_at,
                pode_gerenciar=_pode_gerenciar(fonte),
                pode_excluir=is_admin,
            )
            for fonte in fontes_locais
        ],
    )


def listar_integracoes_para_portal() -> IntegracoesPortalResumo:
    """Retorna somente metadados seguros das integracoes cadastradas."""
    integracoes_ia = AIProviderIntegration.objects.order_by("provider_type", "nome")
    integracoes_google_drive = (
        GoogleDriveIntegration.objects.annotate(total_fontes=Count("folder_sources"))
        .order_by("nome")
    )
    integracoes_locais = LocalStorageIntegration.objects.select_related("created_by").order_by("nome")

    return IntegracoesPortalResumo(
        ia=[
            IAIntegracaoResumo(
                id=integracao.pk,
                nome=integracao.nome,
                provedor=integracao.get_provider_type_display(),
                status=integracao.get_status_display(),
                modelo_padrao=integracao.default_model or "Nao informado",
                timeout_seconds=integracao.timeout_seconds,
                ultima_validacao=integracao.last_validated_at,
                ultima_conexao=integracao.last_connection_at,
                ultimo_erro=integracao.last_error,
                validar_url=reverse(
                    "portal_integracao_validar",
                    kwargs={"tipo": "ia", "integracao_id": integracao.pk},
                ),
            )
            for integracao in integracoes_ia
        ],
        google_drive=[
            GoogleDriveIntegracaoResumo(
                id=integracao.pk,
                nome=integracao.nome,
                status=integracao.get_status_display(),
                modo_autenticacao=integracao.auth_mode,
                service_account_email=integracao.service_account_email,
                extensoes=", ".join(integracao.allowed_extensions or []),
                ultima_conexao=integracao.last_connection_at,
                total_fontes=integracao.total_fontes,
                ultimo_erro=integracao.last_error,
                validar_url=reverse(
                    "portal_integracao_validar",
                    kwargs={"tipo": "google-drive", "integracao_id": integracao.pk},
                ),
            )
            for integracao in integracoes_google_drive
        ],
        storage_local=[
            LocalStorageIntegracaoResumo(
                id=integracao.pk,
                nome=integracao.nome,
                status=integracao.get_status_display(),
                base_path=_caminho_para_exibicao(integracao.base_path),
                extensoes=", ".join(integracao.allowed_extensions or []),
                leitura_recursiva=integracao.recursive_scan,
                ultima_validacao=integracao.last_validated_at,
                ultimo_erro=integracao.last_error,
                validar_url=reverse(
                    "portal_integracao_validar",
                    kwargs={"tipo": "storage-local", "integracao_id": integracao.pk},
                ),
                criado_por=str(integracao.created_by) if integracao.created_by else "—",
            )
            for integracao in integracoes_locais
        ],
    )
