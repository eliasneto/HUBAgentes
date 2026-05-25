from django.apps import apps as django_apps
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, Http404
from django.db.models import Sum
from django.urls import path, reverse
from django.utils.html import format_html

from apps.core.admin import ReadOnlyForOperatorsMixin, UserStampedAdmin
from apps.integracoes.services.ai_providers import AIProviderServiceError
from apps.integracoes.services.google_drive import GoogleDriveServiceError
from apps.integracoes.services.local_storage import LocalStorageServiceError
from apps.processamentos.services.agent_execution import (
    ProcessamentoExecutionError,
    execute_processing,
)
from apps.processamentos.services.document_sources import (
    DocumentSourcePreparationError,
    prepare_documentos,
)

from .models import (
    DocumentoEntrada,
    DocumentoSaidaProcessamento,
    Processamento,
    ProcessamentoExecucaoIA,
    ProcessingInputSourceType,
    ProcessingOutputFormat,
    ProcessingStatus,
)


class DocumentoEntradaInline(admin.TabularInline):
    model = DocumentoEntrada
    extra = 0
    fields = (
        "nome_arquivo",
        "source_type",
        "source_reference",
        "status",
        "uploaded_file",
        "processado_em",
        "mensagem_erro",
    )
    readonly_fields = ("processado_em", "mensagem_erro")


class DocumentoSaidaProcessamentoInline(admin.TabularInline):
    model = DocumentoSaidaProcessamento
    extra = 0
    can_delete = False
    fields = (
        "documento",
        "status",
        "formato",
        "download_arquivo",
        "mensagem_erro",
        "liberado_em",
        "created_at",
    )
    readonly_fields = fields

    @admin.display(description="Arquivo")
    def download_arquivo(self, obj):
        if not obj.arquivo:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">Baixar arquivo</a>',
            obj.arquivo.url,
        )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ProcessamentoExecucaoIAInline(admin.TabularInline):
    model = ProcessamentoExecucaoIA
    extra = 0
    can_delete = False
    fields = (
        "tentativa_numero",
        "status",
        "documento",
        "modelo_utilizado",
        "duracao_minutos",
        "input_tokens",
        "processing_tokens",
        "output_tokens",
        "total_tokens",
        "error_message",
        "created_at",
    )
    readonly_fields = fields

    @admin.display(description="Duracao (min)")
    def duracao_minutos(self, obj):
        if obj.duracao_ms is None:
            return "-"
        return round(obj.duracao_ms / 60000, 2)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Processamento)
class ProcessamentoAdmin(
    ReadOnlyForOperatorsMixin,
    UserStampedAdmin,
):
    base_exclude = (
        "iniciado_por",
        "google_drive_integration",
        "drive_folder_id_escolhida",
        "drive_folder_nome_escolhida",
        "drive_folder_url_escolhida",
    )
    list_display = (
        "codigo",
        "status",
        "agente",
        "origem_resumida",
        "output_format",
        "iniciado_por",
        "duracao_total_minutos_historico",
        "total_tokens_historico",
        "total_documentos",
        "total_processados",
        "download_saida",
        "iniciado_em",
    )
    list_filter = ("status", "agente", "input_source_type", "output_format")
    search_fields = (
        "codigo",
        "drive_folder_id_escolhida",
        "local_relative_input_path",
        "arquivo_saida_nome",
    )
    readonly_fields = (
        "iniciado_por",
        "google_drive_integration",
        "drive_folder_id_escolhida",
        "drive_folder_nome_escolhida",
        "drive_folder_url_escolhida",
        "ai_provider_integration_snapshot",
        "prompt_snapshot",
        "modelo_snapshot",
        "mensagem_erro",
        "mensagem_erro_tecnico",
        "finalizado_em",
        "execucao_iniciada_em",
        "execucao_finalizada_em",
        "duracao_ultima_execucao_minutos",
        "tokens_historicos_total",
        "input_tokens",
        "processing_tokens",
        "output_tokens",
        "total_tokens",
        "arquivo_saida_formato",
        "arquivo_saida_liberado_em",
        "created_at",
        "updated_at",
    )
    inlines = (
        DocumentoEntradaInline,
        DocumentoSaidaProcessamentoInline,
        ProcessamentoExecucaoIAInline,
    )
    actions = ("preparar_documentos_da_origem", "executar_agente_nos_documentos")

    @admin.display(description="Origem")
    def origem_resumida(self, obj):
        if obj.input_source_type == ProcessingInputSourceType.GOOGLE_DRIVE_FOLDER:
            return obj.folder_source or "-"
        if obj.input_source_type in {
            ProcessingInputSourceType.LOCAL_FOLDER,
            ProcessingInputSourceType.LOCAL_FILE,
        }:
            return obj.local_relative_input_path or "-"
        if obj.input_source_type == ProcessingInputSourceType.UPLOAD_AT_EXECUTION:
            return "Arquivo informado na execucao"
        return "-"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:processamento_id>/download-saida/",
                self.admin_site.admin_view(self.download_saida_view),
                name="processamentos_processamento_download_saida",
            ),
        ]
        return custom_urls + urls

    def get_exclude(self, request, obj=None):
        excluded_fields = list(self.base_exclude)
        if obj is None:
            excluded_fields.extend(
                [
                    "total_documentos",
                    "total_processados",
                    "arquivo_saida",
                    "arquivo_saida_nome",
                ]
            )
        return tuple(excluded_fields)

    @admin.display(description="Saida")
    def download_saida(self, obj):
        if not obj.arquivo_saida:
            return "-"
        url = reverse(
            "admin:processamentos_processamento_download_saida",
            args=[obj.pk],
        )
        return format_html('<a href="{}">Baixar arquivo</a>', url)

    @admin.display(description="Ultima execucao (min)")
    def duracao_ultima_execucao_minutos(self, obj):
        if obj.duracao_processamento_ms is None:
            return "-"
        return round(obj.duracao_processamento_ms / 60000, 2)

    @admin.display(description="Tempo historico (min)")
    def duracao_total_minutos_historico(self, obj):
        aggregate = obj.execucoes_ia.aggregate(total_ms=Sum("duracao_ms"))
        total_ms = aggregate.get("total_ms")
        if total_ms is None:
            return "-"
        return round(total_ms / 60000, 2)

    @admin.display(description="Tokens historicos")
    def total_tokens_historico(self, obj):
        aggregate = obj.execucoes_ia.aggregate(total_tokens=Sum("total_tokens"))
        return aggregate.get("total_tokens") or "-"

    @admin.display(description="Tokens historicos")
    def tokens_historicos_total(self, obj):
        return self.total_tokens_historico(obj)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.iniciado_por = request.user
        super().save_model(request, obj, form, change)
        if obj.status == ProcessingStatus.CONCLUIDO_SUCESSO and obj.arquivo_saida:
            messages.success(
                request,
                "Processamento concluido com sucesso. A saida foi liberada automaticamente.",
            )

    @admin.action(description="Preparar documentos da origem")
    def preparar_documentos_da_origem(self, request, queryset):
        success_count = 0
        for processamento in queryset:
            try:
                sync_result = prepare_documentos(processamento)
            except (
                DocumentSourcePreparationError,
                GoogleDriveServiceError,
                LocalStorageServiceError,
            ) as exc:
                processamento.mensagem_erro = str(exc)
                processamento.save(update_fields=["mensagem_erro", "updated_at"])
                self.message_user(
                    request,
                    f"{processamento.codigo}: {exc}",
                    level=messages.ERROR,
                )
                continue

            processamento.total_documentos = processamento.documentos.count()
            processamento.mensagem_erro = ""
            processamento.save(
                update_fields=["total_documentos", "mensagem_erro", "updated_at"]
            )
            success_count += 1
            self.message_user(
                request,
                (
                    f"{processamento.codigo}: {sync_result['created']} documento(s) novo(s), "
                    f"{sync_result['updated']} atualizado(s) e "
                    f"{sync_result['total']} total(is) materializado(s)."
                ),
            )

        if success_count:
            self.message_user(
                request,
                f"{success_count} processamento(s) tiveram documentos preparados.",
            )

    @admin.action(description="Executar agente nos documentos disponiveis")
    def executar_agente_nos_documentos(self, request, queryset):
        success_count = 0
        for processamento in queryset:
            try:
                execution_data = execute_processing(processamento, request.user)
            except (
                AIProviderServiceError,
                GoogleDriveServiceError,
                LocalStorageServiceError,
                DocumentSourcePreparationError,
                ProcessamentoExecutionError,
            ) as exc:
                self.message_user(
                    request,
                    f"{processamento.codigo}: {exc}",
                    level=messages.ERROR,
                )
                continue
            except Exception as exc:  # pragma: no cover
                self.message_user(
                    request,
                    f"{processamento.codigo}: falha inesperada na execucao: {exc}",
                    level=messages.ERROR,
                )
                continue

            success_count += 1
            if (
                execution_data["documentos_processados"] == 0
                and execution_data["documentos_com_erro"] > 0
            ):
                self.message_user(
                    request,
                    (
                        f"{processamento.codigo}: nenhum documento foi processado com sucesso. "
                        f"{execution_data['documentos_com_erro']} tentativa(s) terminaram com erro."
                    ),
                    level=messages.ERROR,
                )
            elif execution_data["documentos_com_erro"]:
                self.message_user(
                    request,
                    (
                        f"{processamento.codigo}: {execution_data['documentos_processados']} documento(s) "
                        f"processado(s) com sucesso, {execution_data['documentos_com_erro']} com erro e "
                        f"{execution_data['saidas_geradas']} saida(s) gerada(s) em {execution_data['formato_saida']}."
                    ),
                    level=messages.WARNING,
                )
            else:
                self.message_user(
                    request,
                    (
                        f"{processamento.codigo}: {execution_data['documentos_processados']} documento(s) "
                        f"processado(s) com sucesso e {execution_data['saidas_geradas']} saida(s) gerada(s) "
                        f"em {execution_data['formato_saida']}."
                    ),
                )

        if success_count:
            self.message_user(
                request,
                f"{success_count} processamento(s) executado(s).",
            )

    def download_saida_view(self, request, processamento_id):
        processamento = self.get_object(request, processamento_id)
        if processamento is None:
            raise Http404("Processamento nao encontrado.")
        if not self.has_view_permission(request, processamento):
            raise PermissionDenied
        if not processamento.arquivo_saida:
            raise Http404("Arquivo de saida indisponivel.")

        evento_model = django_apps.get_model("auditoria", "EventoAuditoria")
        evento_model.objects.create(
            modulo="processamentos",
            acao="download_saida",
            actor=request.user,
            processamento=processamento,
            objeto_tipo="Processamento",
            objeto_id=str(processamento.pk),
            descricao=f"Download da saida do processamento {processamento.codigo}",
            payload={"arquivo_saida": processamento.arquivo_saida.name},
        )
        return FileResponse(
            processamento.arquivo_saida.open("rb"),
            as_attachment=True,
            filename=processamento.arquivo_saida_nome or processamento.codigo,
        )


@admin.register(DocumentoEntrada)
class DocumentoEntradaAdmin(
    ReadOnlyForOperatorsMixin,
    UserStampedAdmin,
):
    list_display = (
        "nome_arquivo",
        "processamento",
        "source_type",
        "status",
        "source_reference",
        "processado_em",
    )
    list_filter = ("status", "source_type")
    search_fields = (
        "nome_arquivo",
        "drive_file_id",
        "source_reference",
        "processamento__codigo",
    )


@admin.register(ProcessamentoExecucaoIA)
class ProcessamentoExecucaoIAAdmin(ReadOnlyForOperatorsMixin, UserStampedAdmin):
    list_display = (
        "processamento",
        "tentativa_numero",
        "status",
        "modelo_utilizado",
        "duracao_minutos",
        "total_tokens",
        "created_at",
    )
    list_filter = ("status", "ai_provider_integration")
    search_fields = (
        "processamento__codigo",
        "documento__nome_arquivo",
        "modelo_utilizado",
        "error_message",
    )
    readonly_fields = (
        "processamento",
        "documento",
        "ai_provider_integration",
        "tentativa_numero",
        "status",
        "modelo_utilizado",
        "execucao_iniciada_em",
        "execucao_finalizada_em",
        "duracao_ms",
        "duracao_minutos",
        "input_tokens",
        "processing_tokens",
        "output_tokens",
        "total_tokens",
        "usage_metadata",
        "response_summary",
        "error_message",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Duracao (min)")
    def duracao_minutos(self, obj):
        if obj.duracao_ms is None:
            return "-"
        return round(obj.duracao_ms / 60000, 2)

    def has_add_permission(self, request):
        return False


@admin.register(DocumentoSaidaProcessamento)
class DocumentoSaidaProcessamentoAdmin(ReadOnlyForOperatorsMixin, UserStampedAdmin):
    list_display = (
        "processamento",
        "documento",
        "status",
        "formato",
        "download_arquivo",
        "liberado_em",
        "created_at",
    )
    list_filter = ("status", "formato")
    search_fields = (
        "processamento__codigo",
        "documento__nome_arquivo",
        "arquivo_nome",
        "mensagem_erro",
    )
    readonly_fields = (
        "processamento",
        "documento",
        "execucao_ia",
        "status",
        "formato",
        "download_arquivo",
        "arquivo_nome",
        "mensagem_erro",
        "liberado_em",
        "created_at",
        "updated_at",
    )

    @admin.display(description="Arquivo")
    def download_arquivo(self, obj):
        if not obj.arquivo:
            return "-"
        return format_html(
            '<a href="{}" target="_blank" rel="noopener noreferrer">Baixar arquivo</a>',
            obj.arquivo.url,
        )

    def has_add_permission(self, request):
        return False
