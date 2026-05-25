from django.contrib.auth.models import Group, Permission
from django.db.models.signals import post_migrate
from django.dispatch import receiver


ROLE_PERMISSIONS = {
    "administrador": "__all__",
    "analista": {
        "agentes_ia.view_agenteia",
        "integracoes.add_googledrivefoldersource",
        "integracoes.change_googledrivefoldersource",
        "integracoes.view_googledrivefoldersource",
        "processamentos.add_processamento",
        "processamentos.change_processamento",
        "processamentos.view_processamento",
        "processamentos.add_documentoentrada",
        "processamentos.change_documentoentrada",
        "processamentos.view_documentoentrada",
        "auditoria.view_eventoauditoria",
    },
    "operador": {
        "processamentos.view_processamento",
    },
}


@receiver(post_migrate)
def create_default_groups(sender, **kwargs):
    for group_name, permission_map in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        if permission_map == "__all__":
            group.permissions.set(Permission.objects.all())
            continue

        permissions = []
        for permission_code in permission_map:
            app_label, codename = permission_code.split(".")
            permission = Permission.objects.filter(
                content_type__app_label=app_label,
                codename=codename,
            ).first()
            if permission:
                permissions.append(permission)
        group.permissions.set(permissions)
