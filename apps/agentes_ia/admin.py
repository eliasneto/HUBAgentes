from django.contrib import admin, messages

from apps.core.admin import UserStampedAdmin
from apps.agentes_ia.services import clonar_agente

from .models import AgenteConfiguracaoOperacional, AgenteIA


class AgenteConfiguracaoOperacionalInline(admin.StackedInline):
    model = AgenteConfiguracaoOperacional
    extra = 1
    max_num = 1
    fieldsets = (
        (
            "Entrada",
            {
                "fields": (
                    "input_policy",
                    "default_input_source_type",
                    "default_folder_source",
                    "default_local_storage_integration",
                    "default_local_relative_input_path",
                    "allowed_input_extensions",
                    "allow_runtime_input_choice",
                    "allow_runtime_file_upload",
                )
            },
        ),
        (
            "Saida",
            {
                "fields": (
                    "output_policy",
                    "default_output_format",
                    "default_output_destination",
                    "allow_runtime_output_override",
                )
            },
        ),
        (
            "Schemas e concorrencia",
            {
                "fields": (
                    "runtime_fields_schema",
                    "builder_schema",
                    "concurrency_policy",
                )
            },
        ),
    )


@admin.register(AgenteIA)
class AgenteIAAdmin(UserStampedAdmin):
    list_display = (
        "nome",
        "tipo",
        "categoria_operacional",
        "visibilidade",
        "modo_acionamento",
        "status",
        "ai_provider_integration",
        "permite_execucao_manual",
        "permite_clonagem",
        "updated_at",
    )
    list_filter = (
        "status",
        "tipo",
        "categoria_operacional",
        "visibilidade",
        "modo_acionamento",
        "permite_execucao_manual",
        "permite_clonagem",
    )
    search_fields = ("nome", "slug", "objetivo", "prompt_version")
    prepopulated_fields = {"slug": ("nome",)}
    readonly_fields = ("clonado_de",)
    inlines = (AgenteConfiguracaoOperacionalInline,)
    actions = ("clonar_agentes",)

    fieldsets = (
        (
            "Identidade",
            {
                "fields": (
                    "nome",
                    "slug",
                    "tipo",
                    "categoria_operacional",
                    "objetivo",
                )
            },
        ),
        (
            "Visibilidade e acionamento",
            {
                "fields": (
                    "status",
                    "visibilidade",
                    "modo_acionamento",
                    "permite_execucao_manual",
                    "permite_clonagem",
                    "clonado_de",
                )
            },
        ),
        (
            "IA",
            {
                "fields": (
                    "ai_provider_integration",
                    "modelo_preferencial",
                    "prompt_version",
                    "prompt_base",
                    "parametros_execucao",
                )
            },
        ),
    )

    @admin.action(description="Clonar agentes selecionados")
    def clonar_agentes(self, request, queryset):
        total = 0
        for agente in queryset:
            try:
                clone = clonar_agente(agente=agente, actor=request.user)
            except ValueError as exc:
                self.message_user(
                    request,
                    f"{agente.nome}: {exc}",
                    level=messages.ERROR,
                )
                continue
            total += 1
            self.message_user(
                request,
                f"Clone criado inativo: {clone.nome}",
                level=messages.SUCCESS,
            )

        if total:
            self.message_user(request, f"{total} clone(s) criado(s).")

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for obj in instances:
            if hasattr(obj, "updated_by"):
                obj.updated_by = request.user
            if not obj.pk and hasattr(obj, "created_by") and not obj.created_by_id:
                obj.created_by = request.user
            obj.save()
        formset.save_m2m()
