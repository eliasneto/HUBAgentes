import json

from django.apps import apps as django_apps
from django.contrib import admin, messages
from django.db import transaction
from django.core.serializers.json import DjangoJSONEncoder
from django.utils.html import format_html
from django.utils import timezone

from apps.core.admin import UserStampedAdmin
from apps.integracoes.services.ai_providers import (
    AIProviderServiceError,
    get_ai_provider_adapter,
)
from apps.integracoes.services.google_drive import (
    GoogleDriveServiceError,
    fetch_folder_metadata,
    list_folder_contents_from_folder_source,
)
from apps.integracoes.services.local_storage import (
    LocalStorageServiceError,
    validate_local_storage_integration,
)

from .models import (
    AIProviderIntegration,
    GoogleDriveFolderSource,
    GoogleDriveFolderSourceItem,
    GoogleDriveIntegration,
    LocalStorageIntegration,
)


class AdminOnlyGoogleDriveCredentialMixin:
    def _is_admin_group(self, request):
        return request.user.groups.filter(name="administrador").exists()

    def has_module_permission(self, request):
        return request.user.is_superuser or self._is_admin_group(request)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or self._is_admin_group(request)

    def has_add_permission(self, request):
        return request.user.is_superuser or self._is_admin_group(request)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser or self._is_admin_group(request)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or self._is_admin_group(request)


class FolderSourcePermissionMixin:
    def _can_manage_folder_sources(self, request):
        return request.user.is_superuser or request.user.groups.filter(
            name__in=["administrador", "analista"]
        ).exists()

    def has_module_permission(self, request):
        return self._can_manage_folder_sources(request)

    def has_view_permission(self, request, obj=None):
        return self._can_manage_folder_sources(request)

    def has_add_permission(self, request):
        return self._can_manage_folder_sources(request)

    def has_change_permission(self, request, obj=None):
        return self._can_manage_folder_sources(request)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.groups.filter(
            name="administrador"
        ).exists()


class GoogleDriveFolderSourceItemInline(admin.TabularInline):
    model = GoogleDriveFolderSourceItem
    extra = 0
    can_delete = False
    fields = (
        "nome_com_link",
        "item_type",
        "disponivel_para_ia",
        "modified_at",
        "size_bytes",
        "sincronizado_em",
    )
    readonly_fields = fields

    @admin.display(description="Item")
    def nome_com_link(self, obj):
        if obj.web_view_link:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener noreferrer">{}</a>',
                obj.web_view_link,
                obj.nome,
            )
        return obj.nome

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(GoogleDriveIntegration)
class GoogleDriveIntegrationAdmin(AdminOnlyGoogleDriveCredentialMixin, UserStampedAdmin):
    exclude = ("drive_folder_id",)
    list_display = (
        "nome",
        "status",
        "service_account_email",
        "updated_at",
    )
    list_filter = ("status",)
    search_fields = ("nome", "service_account_email")


@admin.register(LocalStorageIntegration)
class LocalStorageIntegrationAdmin(AdminOnlyGoogleDriveCredentialMixin, UserStampedAdmin):
    list_display = (
        "nome",
        "status",
        "base_path",
        "recursive_scan",
        "last_validated_at",
        "updated_at",
    )
    list_filter = ("status", "recursive_scan")
    search_fields = ("nome", "base_path")
    readonly_fields = ("last_validated_at", "last_error")
    actions = ("validar_storage_local",)

    @admin.action(description="Validar pasta local")
    def validar_storage_local(self, request, queryset):
        success_count = 0
        for integration in queryset:
            try:
                resolved_path = validate_local_storage_integration(integration)
            except LocalStorageServiceError as exc:
                integration.last_validated_at = timezone.now()
                integration.last_error = str(exc)
                if integration.status == "ativa":
                    integration.status = "erro"
                integration.save(
                    update_fields=[
                        "last_validated_at",
                        "last_error",
                        "status",
                        "updated_at",
                    ]
                )
                self.message_user(
                    request,
                    f"{integration.nome}: {exc}",
                    level=messages.ERROR,
                )
                continue

            integration.last_validated_at = timezone.now()
            integration.last_error = ""
            if integration.status == "erro":
                integration.status = "ativa"
            integration.save(
                update_fields=[
                    "last_validated_at",
                    "last_error",
                    "status",
                    "updated_at",
                ]
            )
            success_count += 1
            self.message_user(
                request,
                f"{integration.nome}: raiz local validada em {resolved_path}.",
            )

        if success_count:
            self.message_user(
                request,
                f"{success_count} integracao(oes) locais validada(s) com sucesso.",
            )


@admin.register(GoogleDriveFolderSource)
class GoogleDriveFolderSourceAdmin(FolderSourcePermissionMixin, UserStampedAdmin):
    list_display = (
        "nome",
        "status",
        "folder_display_name",
        "folder_id",
        "google_drive_integration",
        "itens_sincronizados",
        "pdfs_disponiveis_para_ia",
        "last_validated_at",
    )
    list_filter = ("status", "google_drive_integration")
    search_fields = ("nome", "folder_url", "folder_id", "folder_display_name")
    readonly_fields = (
        "folder_id",
        "folder_display_name",
        "last_validated_at",
        "last_error",
        "resumo_conteudo",
    )
    actions = ("validar_acesso_no_drive", "sincronizar_conteudo_do_drive")
    inlines = (GoogleDriveFolderSourceItemInline,)

    @admin.display(description="Itens sincronizados")
    def itens_sincronizados(self, obj):
        return obj.synced_items.count()

    @admin.display(description="PDFs para IA")
    def pdfs_disponiveis_para_ia(self, obj):
        return obj.synced_items.filter(disponivel_para_ia=True).count()

    @admin.display(description="Resumo do conteúdo sincronizado")
    def resumo_conteudo(self, obj):
        if not obj or not obj.pk:
            return "Salve a origem de pasta para habilitar a sincronizacao e a visualizacao."

        total_items = obj.synced_items.count()
        total_pdfs = obj.synced_items.filter(disponivel_para_ia=True).count()
        total_pastas = obj.synced_items.filter(item_type="pasta").count()
        latest_item = obj.synced_items.order_by("-sincronizado_em").first()
        latest_sync = (
            latest_item.sincronizado_em.strftime("%d/%m/%Y %H:%M")
            if latest_item
            else "ainda nao sincronizado"
        )
        return format_html(
            (
                "<strong>Itens sincronizados:</strong> {}<br>"
                "<strong>Pastas visiveis:</strong> {}<br>"
                "<strong>PDFs disponiveis para IA:</strong> {}<br>"
                "<strong>Ultima sincronizacao:</strong> {}<br>"
                "<strong>Como atualizar:</strong> use a acao "
                "<em>Validar acesso no Google Drive</em> ou "
                "<em>Sincronizar conteudo do Google Drive</em>."
            ),
            total_items,
            total_pastas,
            total_pdfs,
            latest_sync,
        )

    def _log_folder_source_event(self, request, source, action, payload):
        evento_model = django_apps.get_model("auditoria", "EventoAuditoria")
        if evento_model is None:
            return
        safe_payload = json.loads(json.dumps(payload, cls=DjangoJSONEncoder))
        evento_model.objects.create(
            modulo="integracoes",
            acao=action,
            actor=request.user,
            objeto_tipo="GoogleDriveFolderSource",
            objeto_id=str(source.pk),
            descricao=f"{action} da origem de pasta {source.nome}",
            payload=safe_payload,
        )

    def _sync_folder_source_items(self, source):
        drive_items = list_folder_contents_from_folder_source(source)
        sync_time = timezone.now()
        synced_ids = []

        with transaction.atomic():
            for drive_item in drive_items:
                synced_ids.append(drive_item["drive_item_id"])
                GoogleDriveFolderSourceItem.objects.update_or_create(
                    folder_source=source,
                    drive_item_id=drive_item["drive_item_id"],
                    defaults={
                        **drive_item,
                        "sincronizado_em": sync_time,
                    },
                )

            source.synced_items.exclude(drive_item_id__in=synced_ids).delete()

        return {
            "total_itens": len(drive_items),
            "total_pastas": sum(1 for item in drive_items if item["item_type"] == "pasta"),
            "total_pdfs": sum(1 for item in drive_items if item["disponivel_para_ia"]),
            "sincronizado_em": sync_time,
        }

    @admin.action(description="Validar acesso no Google Drive")
    def validar_acesso_no_drive(self, request, queryset):
        success_count = 0
        for source in queryset:
            try:
                metadata = fetch_folder_metadata(source)
            except GoogleDriveServiceError as exc:
                source.last_error = str(exc)
                if source.status == "ativa":
                    source.status = "erro"
                source.save(update_fields=["last_error", "status", "updated_at"])
                self.message_user(request, f"{source.nome}: {exc}", level=messages.ERROR)
                continue

            source.folder_display_name = metadata.get("name", source.folder_display_name)
            source.last_validated_at = timezone.now()
            source.last_error = ""
            source.save(
                update_fields=[
                    "folder_display_name",
                    "last_validated_at",
                    "last_error",
                    "updated_at",
                ]
            )
            try:
                sync_result = self._sync_folder_source_items(source)
            except GoogleDriveServiceError as exc:
                source.last_error = str(exc)
                source.save(update_fields=["last_error", "updated_at"])
                self.message_user(
                    request,
                    f"{source.nome}: validada, mas a sincronizacao do conteudo falhou: {exc}",
                    level=messages.WARNING,
                )
                continue

            self._log_folder_source_event(
                request,
                source,
                "validar_e_sincronizar_origem_drive",
                sync_result,
            )
            success_count += 1
            self.message_user(
                request,
                (
                    f"{source.nome}: pasta validada, {sync_result['total_itens']} item(ns) "
                    f"sincronizado(s), sendo {sync_result['total_pdfs']} PDF(s) elegivel(is) para IA."
                ),
            )

        if success_count:
            self.message_user(
                request,
                f"{success_count} origem(ns) de pasta validada(s) e sincronizada(s) com sucesso.",
            )

    @admin.action(description="Sincronizar conteudo do Google Drive")
    def sincronizar_conteudo_do_drive(self, request, queryset):
        success_count = 0
        for source in queryset:
            try:
                sync_result = self._sync_folder_source_items(source)
            except GoogleDriveServiceError as exc:
                source.last_error = str(exc)
                source.save(update_fields=["last_error", "updated_at"])
                self.message_user(request, f"{source.nome}: {exc}", level=messages.ERROR)
                continue

            source.last_error = ""
            source.save(update_fields=["last_error", "updated_at"])
            self._log_folder_source_event(
                request,
                source,
                "sincronizar_conteudo_origem_drive",
                sync_result,
            )
            success_count += 1
            self.message_user(
                request,
                (
                    f"{source.nome}: {sync_result['total_itens']} item(ns) sincronizado(s), "
                    f"com {sync_result['total_pdfs']} PDF(s) disponivel(is) para IA."
                ),
            )

        if success_count:
            self.message_user(
                request,
                f"{success_count} origem(ns) de pasta tiveram o conteudo sincronizado.",
            )


@admin.register(AIProviderIntegration)
class AIProviderIntegrationAdmin(AdminOnlyGoogleDriveCredentialMixin, UserStampedAdmin):
    list_display = (
        "nome",
        "provider_type",
        "status",
        "default_model",
        "last_validated_at",
        "timeout_seconds",
        "updated_at",
    )
    list_filter = ("provider_type", "status")
    search_fields = ("nome", "default_model", "organization_id", "project_id")
    readonly_fields = (
        "last_validated_at",
        "last_connection_at",
        "last_validation_summary",
        "last_error",
    )
    actions = ("validar_integracao_ia",)

    def _log_ai_provider_event(self, request, integration, action, payload):
        evento_model = django_apps.get_model("auditoria", "EventoAuditoria")
        if evento_model is None:
            return
        safe_payload = json.loads(json.dumps(payload, cls=DjangoJSONEncoder))
        evento_model.objects.create(
            modulo="integracoes",
            acao=action,
            actor=request.user,
            objeto_tipo="AIProviderIntegration",
            objeto_id=str(integration.pk),
            descricao=f"{action} da integracao de IA {integration.nome}",
            payload=safe_payload,
        )

    @admin.action(description="Validar conexao de IA")
    def validar_integracao_ia(self, request, queryset):
        success_count = 0
        for integration in queryset:
            try:
                adapter = get_ai_provider_adapter(integration)
                validation_result = adapter.validate_connection()
            except AIProviderServiceError as exc:
                integration.last_validated_at = timezone.now()
                integration.last_error = str(exc)
                integration.last_validation_summary = ""
                if integration.status == "ativa":
                    integration.status = "erro"
                integration.save(
                    update_fields=[
                        "last_validated_at",
                        "last_error",
                        "last_validation_summary",
                        "status",
                        "updated_at",
                    ]
                )
                self.message_user(
                    request,
                    f"{integration.nome}: {exc}",
                    level=messages.ERROR,
                )
                continue

            integration.last_validated_at = timezone.now()
            integration.last_connection_at = integration.last_validated_at
            integration.last_error = ""
            integration.last_validation_summary = validation_result.summary
            if integration.status == "erro":
                integration.status = "ativa"
            integration.save(
                update_fields=[
                    "last_validated_at",
                    "last_connection_at",
                    "last_error",
                    "last_validation_summary",
                    "status",
                    "updated_at",
                ]
            )
            self._log_ai_provider_event(
                request,
                integration,
                "validar_integracao_ia",
                {
                    "provider_type": integration.provider_type,
                    "model": integration.default_model,
                    "request_url": validation_result.request_url,
                    "summary": validation_result.summary,
                },
            )
            success_count += 1
            self.message_user(
                request,
                f"{integration.nome}: validacao concluida com sucesso.",
            )

        if success_count:
            self.message_user(
                request,
                f"{success_count} integracao(oes) de IA validada(s) com sucesso.",
            )
