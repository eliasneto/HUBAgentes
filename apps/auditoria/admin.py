from django.contrib import admin

from apps.core.admin import ReadOnlyForOperatorsMixin

from .models import EventoAuditoria


@admin.register(EventoAuditoria)
class EventoAuditoriaAdmin(ReadOnlyForOperatorsMixin, admin.ModelAdmin):
    list_display = (
        "modulo",
        "acao",
        "actor",
        "processamento",
        "created_at",
    )
    list_filter = ("modulo", "acao", "created_at")
    search_fields = ("descricao", "objeto_tipo", "objeto_id")
    readonly_fields = (
        "modulo",
        "acao",
        "actor",
        "processamento",
        "objeto_tipo",
        "objeto_id",
        "descricao",
        "payload",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.groups.filter(
            name="administrador"
        ).exists()

    def has_delete_permission(self, request, obj=None):
        return False
