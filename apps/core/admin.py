from django.apps import apps as django_apps
from django.contrib import admin
from django.db import models
from django.forms import PasswordInput

from apps.core.models import ConfiguracaoGeral


@admin.register(ConfiguracaoGeral)
class ConfiguracaoGeralAdmin(admin.ModelAdmin):
    list_display = ("visibilidade_dashboard", "mascote_ativo", "limpeza_automatica_ativa", "dias_retencao_arquivos", "updated_at", "atualizado_por")
    readonly_fields = ("updated_at", "atualizado_por")
    fieldsets = (
        ("Painel inicial", {
            "fields": ("visibilidade_dashboard",),
        }),
        ("Assistente Biel", {
            "fields": ("mascote_ativo",),
            "description": "Quando ativo, o mascote Biel aparece flutuando no portal para todos os usuários.",
        }),
        ("Limpeza automática de arquivos", {
            "fields": ("limpeza_automatica_ativa", "dia_execucao_limpeza", "dias_retencao_arquivos"),
            "description": "Quando ativo, deleta arquivos de saída no dia configurado de cada mês. Ex: dia=30 → roda todo dia 30, apaga arquivos com mais de 30 dias.",
        }),
        ("Auditoria", {
            "fields": ("atualizado_por", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def has_add_permission(self, request):
        return not ConfiguracaoGeral.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class UserStampedAdmin(admin.ModelAdmin):
    def get_exclude(self, request, obj=None):
        excludes = list(super().get_exclude(request, obj) or [])
        model_field_names = {field.name for field in self.model._meta.fields}
        for field_name in ("created_by", "updated_by"):
            if field_name in model_field_names:
                excludes.append(field_name)
        return tuple(dict.fromkeys(excludes))

    def save_model(self, request, obj, form, change):
        if hasattr(obj, "updated_by"):
            obj.updated_by = request.user
        if not change and hasattr(obj, "created_by") and not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        self.log_audit_event(request, obj, "editar" if change else "criar")

    def delete_model(self, request, obj):
        self.log_audit_event(request, obj, "excluir")
        super().delete_model(request, obj)

    def log_audit_event(self, request, obj, action):
        evento_model = django_apps.get_model("auditoria", "EventoAuditoria")
        if evento_model is None:
            return
        evento_model.objects.create(
            modulo=obj._meta.app_label,
            acao=action,
            actor=request.user,
            objeto_tipo=obj.__class__.__name__,
            objeto_id=str(obj.pk or ""),
            descricao=str(obj),
            payload={"admin_model": obj._meta.label},
        )

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name in {"api_key", "credentials_json"}:
            kwargs["widget"] = PasswordInput(render_value=True)
        return super().formfield_for_dbfield(db_field, request, **kwargs)


class ReadOnlyForOperatorsMixin:
    def is_operador(self, request):
        return (
            request.user.is_authenticated
            and request.user.groups.filter(name="operador").exists()
        )

    def has_add_permission(self, request):
        if self.is_operador(request):
            return False
        return super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        if self.is_operador(request):
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if self.is_operador(request):
            return False
        return super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if self.is_operador(request):
            for field in self.model._meta.get_fields():
                if isinstance(field, models.Field):
                    readonly.append(field.name)
        return tuple(dict.fromkeys(readonly))
