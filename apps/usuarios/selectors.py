from dataclasses import dataclass
from datetime import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.urls import reverse


@dataclass(frozen=True)
class UsuarioPortalResumo:
    id: int
    username: str
    nome: str
    papel: str
    grupos: str
    status: str
    ultimo_acesso: datetime | None
    is_staff: bool
    is_superuser: bool
    editar_url: str


@dataclass(frozen=True)
class GrupoPortalResumo:
    nome: str
    total_usuarios: int


@dataclass(frozen=True)
class UsuariosAcessosPortalResumo:
    usuarios: list[UsuarioPortalResumo]
    grupos: list[GrupoPortalResumo]
    total_usuarios: int
    total_ativos: int
    total_admins: int
    total_grupos: int


def listar_usuarios_acessos_para_portal() -> UsuariosAcessosPortalResumo:
    User = get_user_model()
    usuarios_queryset = (
        User.objects.select_related("profile")
        .prefetch_related("groups")
        .order_by("username")
    )
    usuarios = [_build_usuario_resumo(user) for user in usuarios_queryset]
    grupos = [
        GrupoPortalResumo(
            nome=grupo.name,
            total_usuarios=grupo.user_set.count(),
        )
        for grupo in Group.objects.order_by("name")
    ]

    return UsuariosAcessosPortalResumo(
        usuarios=usuarios,
        grupos=grupos,
        total_usuarios=len(usuarios),
        total_ativos=sum(1 for usuario in usuarios if usuario.status == "Ativo"),
        total_admins=sum(1 for usuario in usuarios if usuario.is_superuser),
        total_grupos=len(grupos),
    )


def _build_usuario_resumo(user) -> UsuarioPortalResumo:
    profile = getattr(user, "profile", None)
    papel = profile.get_papel_principal_display() if profile and profile.papel_principal else "-"
    grupos = ", ".join(group.name for group in user.groups.all()) or "-"
    nome = user.get_full_name() or user.username
    return UsuarioPortalResumo(
        id=user.pk,
        username=user.username,
        nome=nome,
        papel=papel,
        grupos=grupos,
        status="Ativo" if user.is_active else "Inativo",
        ultimo_acesso=user.last_login,
        is_staff=user.is_staff,
        is_superuser=user.is_superuser,
        editar_url=reverse("portal_usuario_editar", kwargs={"user_id": user.pk}),
    )
