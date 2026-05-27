import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import FormView, RedirectView, TemplateView
from pathlib import Path

from apps.agentes_ia.forms import AgentePortalCreateForm
from apps.agentes_ia.models import AgenteIA, AgentTriggerMode, AgentVisibility
from apps.agentes_ia.selectors import (
    listar_agentes_para_gerenciamento,
    listar_agentes_para_portal,
)
from apps.agentes_ia.services import (
    montar_payload_execucao_padrao,
)
from apps.integracoes.selectors import (
    listar_fontes_documentos_para_portal,
    listar_integracoes_para_portal,
)
from apps.integracoes.forms import (
    AIProviderIntegrationPortalForm,
    GoogleDriveFolderSourcePortalForm,
    GoogleDriveIntegrationPortalForm,
    LocalStorageFontePortalForm,
    LocalStorageIntegrationPortalForm,
)
from apps.integracoes.models import (
    AIProviderIntegration,
    GoogleDriveFolderSource,
    GoogleDriveIntegration,
    LocalStorageIntegration,
)
from apps.integracoes.services.validation import (
    validate_ai_provider_integration,
    validate_google_drive_integration,
    validate_local_storage,
)
from apps.processamentos.forms import AgenteExecucaoForm
from apps.processamentos.selectors import (
    listar_processamentos_para_portal,
    obter_status_processamento_para_portal,
)
from apps.processamentos.models import Processamento
from apps.processamentos.services.operational_execution import (
    OperationalExecutionError,
    criar_e_iniciar_processamento_para_agente,
)
from apps.usuarios.selectors import listar_usuarios_acessos_para_portal
from apps.usuarios.forms import UsuarioPortalForm

logger = logging.getLogger(__name__)


class PortalAdministradorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = reverse_lazy("portal_login")

    def test_func(self):
        user = self.request.user
        return user.is_superuser or user.groups.filter(name="administrador").exists()

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        raise PermissionDenied("Apenas administradores podem gerenciar agentes.")


class PortalLoginView(LoginView):
    template_name = "portal_operacional/login.html"
    redirect_authenticated_user = True
    next_page = reverse_lazy("portal_painel")

    def form_invalid(self, form):
        messages.error(self.request, "Usuario ou senha invalidos.")
        redirect_url = reverse("portal_login")
        next_url = self.get_redirect_url()
        if next_url:
            redirect_url = f"{redirect_url}?{urlencode({self.redirect_field_name: next_url})}"
        return redirect(redirect_url)


class PortalLogoutView(LogoutView):
    next_page = reverse_lazy("portal_login")


class PortalPainelView(LoginRequiredMixin, TemplateView):
    template_name = "portal_operacional/menu_inicial.html"
    login_url = reverse_lazy("portal_login")


class AgentesLeituraView(LoginRequiredMixin, TemplateView):
    template_name = "portal_operacional/agentes_leitura.html"
    login_url = reverse_lazy("portal_login")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["agentes"] = listar_agentes_para_portal()
        return context


class AgentesGerenciamentoView(PortalAdministradorRequiredMixin, TemplateView):
    template_name = "portal_operacional/agentes_leitura.html"
    login_url = reverse_lazy("portal_login")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["agentes"] = listar_agentes_para_gerenciamento()
        context["modo_gerenciamento_agentes"] = True
        return context


class AgentePortalFormMixin(PortalAdministradorRequiredMixin):
    form_class = AgentePortalCreateForm
    template_name = "portal_operacional/agente_criar.html"
    login_url = reverse_lazy("portal_login")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        return kwargs

    def form_valid(self, form):
        agente = form.save()
        messages.success(
            self.request,
            f"Agente {agente.nome} salvo com sucesso.",
        )
        return redirect(
            reverse("portal_agente_editar", kwargs={"slug": agente.slug})
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("modo_edicao", False)
        return context


class AgentePortalCreateView(AgentePortalFormMixin, FormView):
    pass


class AgentePortalUpdateView(AgentePortalFormMixin, FormView):
    def dispatch(self, request, *args, **kwargs):
        self.agente = get_object_or_404(
            AgenteIA.objects.select_related(
                "ai_provider_integration",
                "configuracao_operacional",
            ),
            slug=kwargs["slug"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        try:
            configuracao_instance = self.agente.configuracao_operacional
        except ObjectDoesNotExist:
            configuracao_instance = None
        kwargs["instance"] = self.agente
        kwargs["configuracao_instance"] = configuracao_instance
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["agente_edicao"] = self.agente
        context["modo_edicao"] = True
        return context


class AgentePortalLegacyCreateRedirectView(
    PortalAdministradorRequiredMixin,
    RedirectView,
):
    permanent = False
    login_url = reverse_lazy("portal_login")

    def get_redirect_url(self, *args, **kwargs):
        return reverse("portal_agente_criar")


class AgenteExecucaoView(LoginRequiredMixin, View):
    login_url = reverse_lazy("portal_login")

    def dispatch(self, request, *args, **kwargs):
        self.agente = get_object_or_404(
            AgenteIA.objects.select_related(
                "ai_provider_integration",
                "configuracao_operacional",
            ).filter(
                visibilidade=AgentVisibility.USUARIO,
                modo_acionamento=AgentTriggerMode.PORTAL,
            ),
            slug=kwargs["slug"],
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        messages.info(
            request,
            "Use o botao Executar no card do agente para iniciar o processamento.",
        )
        return redirect("portal_agentes_leitura")

    def post(self, request, *args, **kwargs):
        form = AgenteExecucaoForm(
            request.POST,
            request.FILES,
            agente=self.agente,
        )
        if form.runtime_fields_schema.get("show_file_upload"):
            if not form.is_valid():
                messages.error(self.request, self._first_form_error(form))
                return redirect("portal_agentes_leitura")
            return self._executar_com_payload(form.cleaned_data)
        return self._executar_com_defaults()

    def _executar_com_defaults(self):
        try:
            cleaned_data = montar_payload_execucao_padrao(self.agente)
            return self._executar_com_payload(cleaned_data)
        except (OperationalExecutionError, ValueError) as exc:
            messages.error(self.request, str(exc))
            return redirect("portal_agentes_leitura")

    def _executar_com_payload(self, cleaned_data):
        try:
            processamento = criar_e_iniciar_processamento_para_agente(
                agente=self.agente,
                actor=self.request.user,
                cleaned_data=cleaned_data,
            )
        except (OperationalExecutionError, ValueError) as exc:
            messages.error(self.request, str(exc))
            return redirect("portal_agentes_leitura")

        messages.success(
            self.request,
            (
                f"Processamento {processamento.codigo} iniciado para o agente "
                f"{self.agente.nome}."
            ),
        )
        return redirect("portal_processamentos")

    def _first_form_error(self, form):
        for errors in form.errors.values():
            if errors:
                return errors[0]
        non_field_errors = form.non_field_errors()
        if non_field_errors:
            return non_field_errors[0]
        return "Nao foi possivel executar este agente. Revise os dados enviados."


class FontesDocumentosView(LoginRequiredMixin, TemplateView):
    template_name = "portal_operacional/fontes_documentos.html"
    login_url = reverse_lazy("portal_login")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["fontes"] = listar_fontes_documentos_para_portal()
        return context


class FonteDocumentoPortalFormMixin(PortalAdministradorRequiredMixin):
    template_name = "portal_operacional/fonte_documento_form.html"
    login_url = reverse_lazy("portal_login")

    form_classes = {
        "google-drive-folder": GoogleDriveFolderSourcePortalForm,
        "storage-local": LocalStorageFontePortalForm,
    }
    model_classes = {
        "google-drive-folder": GoogleDriveFolderSource,
        "storage-local": LocalStorageIntegration,
    }
    type_metadata = {
        "google-drive-folder": {
            "label": "Google Drive",
            "title": "Cadastrar fonte Google Drive",
            "description": (
                "Cadastre a pasta do Google Drive que sera usada como origem documental."
            ),
            "orb": "GD",
        },
        "storage-local": {
            "label": "Pasta local",
            "title": "Cadastrar fonte local",
            "description": (
                "Cadastre uma pasta local autorizada para leitura de documentos."
            ),
            "orb": "PC",
        },
    }

    def get_form_class(self):
        return self.form_classes[self.source_type]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        return kwargs

    def form_valid(self, form):
        source = form.save()
        action_message = "atualizada" if self.get_modo_edicao() else "criada"
        messages.success(
            self.request,
            f"Fonte de documentos {source.nome} {action_message} com sucesso.",
        )
        return redirect("portal_fontes_documentos")

    def get_modo_edicao(self):
        return False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["source_type"] = self.source_type
        context["source_metadata"] = self.type_metadata[self.source_type]
        context["modo_edicao"] = self.get_modo_edicao()
        context["source_type_tabs"] = [
            {
                "key": key,
                "label": metadata["label"],
                "url": f"{reverse('portal_fonte_documento_criar')}?{urlencode({'tipo': key})}",
                "active": key == self.source_type,
            }
            for key, metadata in self.type_metadata.items()
        ]
        return context


class FonteDocumentoCreateView(FonteDocumentoPortalFormMixin, FormView):
    def dispatch(self, request, *args, **kwargs):
        self.source_type = request.GET.get("tipo") or "google-drive-folder"
        if self.source_type not in self.form_classes:
            self.source_type = "google-drive-folder"
        return super().dispatch(request, *args, **kwargs)


class FonteDocumentoUpdateView(FonteDocumentoPortalFormMixin, FormView):
    def dispatch(self, request, *args, **kwargs):
        self.source_type = kwargs["tipo"]
        model_class = self.model_classes.get(self.source_type)
        if model_class is None:
            raise Http404("Tipo de fonte documental nao suportado.")
        self.source = get_object_or_404(model_class, pk=kwargs["fonte_id"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.source
        return kwargs

    def get_modo_edicao(self):
        return True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["source_edicao"] = self.source
        return context


class IntegracoesView(LoginRequiredMixin, TemplateView):
    template_name = "portal_operacional/integracoes.html"
    login_url = reverse_lazy("portal_login")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["integracoes"] = listar_integracoes_para_portal()
        user = self.request.user
        context["pode_validar_integracoes"] = (
            user.is_superuser or user.groups.filter(name="administrador").exists()
        )
        return context


class IntegracaoPortalFormMixin(PortalAdministradorRequiredMixin):
    template_name = "portal_operacional/integracao_form.html"
    login_url = reverse_lazy("portal_login")

    form_classes = {
        "ia": AIProviderIntegrationPortalForm,
        "google-drive": GoogleDriveIntegrationPortalForm,
        "storage-local": LocalStorageIntegrationPortalForm,
    }
    model_classes = {
        "ia": AIProviderIntegration,
        "google-drive": GoogleDriveIntegration,
        "storage-local": LocalStorageIntegration,
    }
    type_metadata = {
        "ia": {
            "label": "IA",
            "title": "Cadastrar provedor de IA",
            "description": (
                "Crie a credencial usada pelos agentes para conversar com o provedor."
            ),
            "orb": "IA",
        },
        "google-drive": {
            "label": "Google Drive",
            "title": "Cadastrar Google Drive",
            "description": (
                "Cadastre a conta tecnica usada para acessar documentos na nuvem."
            ),
            "orb": "GD",
        },
        "storage-local": {
            "label": "Pasta local",
            "title": "Cadastrar pasta local",
            "description": (
                "Autorize uma pasta local para leitura de documentos pelo sistema."
            ),
            "orb": "PC",
        },
    }

    def get_form_class(self):
        return self.form_classes[self.integration_type]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        return kwargs

    def form_valid(self, form):
        integration = form.save()
        action_message = "atualizada" if self.get_modo_edicao() else "criada"
        messages.success(
            self.request,
            f"Conexao {integration.nome} {action_message} com sucesso.",
        )
        return redirect("portal_integracoes")

    def get_modo_edicao(self):
        return False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["integration_type"] = self.integration_type
        context["integration_metadata"] = self.type_metadata[self.integration_type]
        context["modo_edicao"] = self.get_modo_edicao()
        context["integration_type_tabs"] = [
            {
                "key": key,
                "label": metadata["label"],
                "url": f"{reverse('portal_integracao_criar')}?{urlencode({'tipo': key})}",
                "active": key == self.integration_type,
            }
            for key, metadata in self.type_metadata.items()
        ]
        return context


class IntegracaoCreateView(IntegracaoPortalFormMixin, FormView):
    def dispatch(self, request, *args, **kwargs):
        self.integration_type = request.GET.get("tipo") or "ia"
        if self.integration_type not in self.form_classes:
            self.integration_type = "ia"
        return super().dispatch(request, *args, **kwargs)


class IntegracaoUpdateView(IntegracaoPortalFormMixin, FormView):
    def dispatch(self, request, *args, **kwargs):
        self.integration_type = kwargs["tipo"]
        model_class = self.model_classes.get(self.integration_type)
        if model_class is None:
            raise Http404("Tipo de integracao nao suportado.")
        self.integration = get_object_or_404(model_class, pk=kwargs["integracao_id"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.integration
        return kwargs

    def get_modo_edicao(self):
        return True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["integration_edicao"] = self.integration
        return context


class IntegracaoValidarView(PortalAdministradorRequiredMixin, View):
    login_url = reverse_lazy("portal_login")

    validators = {
        "ia": (AIProviderIntegration, validate_ai_provider_integration),
        "google-drive": (GoogleDriveIntegration, validate_google_drive_integration),
        "storage-local": (LocalStorageIntegration, validate_local_storage),
    }

    def get(self, request, tipo, integracao_id):
        messages.info(
            request,
            "Use o botao Validar conexao para conferir a comunicacao.",
        )
        return redirect("portal_integracoes")

    def post(self, request, tipo, integracao_id):
        model_and_validator = self.validators.get(tipo)
        if model_and_validator is None:
            raise Http404("Tipo de integracao nao suportado.")

        model_class, validator = model_and_validator
        integration = get_object_or_404(model_class, pk=integracao_id)
        try:
            result = validator(integration)
        except Exception:
            logger.exception(
                "Falha inesperada ao validar integracao %s %s.",
                tipo,
                integracao_id,
            )
            messages.error(
                request,
                (
                    f"{integration.nome}: falha tecnica ao validar a integracao. "
                    "Contate o administrador do sistema."
                ),
            )
            return redirect("portal_integracoes")
        if result.success:
            messages.success(request, result.message)
        else:
            messages.error(request, result.message)
        return redirect("portal_integracoes")


class ProcessamentosView(LoginRequiredMixin, TemplateView):
    template_name = "portal_operacional/processamentos.html"
    login_url = reverse_lazy("portal_login")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["processamentos"] = listar_processamentos_para_portal(
            page_number=self.request.GET.get("page"),
            per_page=20,
        )
        return context


class UsuariosAcessosView(PortalAdministradorRequiredMixin, TemplateView):
    template_name = "portal_operacional/usuarios_acessos.html"
    login_url = reverse_lazy("portal_login")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["usuarios_acessos"] = listar_usuarios_acessos_para_portal()
        return context


class UsuarioPortalFormMixin(PortalAdministradorRequiredMixin):
    form_class = UsuarioPortalForm
    template_name = "portal_operacional/usuario_form.html"
    login_url = reverse_lazy("portal_login")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor"] = self.request.user
        return kwargs

    def form_valid(self, form):
        usuario = form.save()
        messages.success(
            self.request,
            f"Usuario {usuario.username} salvo com sucesso.",
        )
        return redirect(
            reverse("portal_usuario_editar", kwargs={"user_id": usuario.pk})
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("modo_edicao", False)
        return context


class UsuarioPortalCreateView(UsuarioPortalFormMixin, FormView):
    pass


class UsuarioPortalUpdateView(UsuarioPortalFormMixin, FormView):
    def dispatch(self, request, *args, **kwargs):
        User = get_user_model()
        self.usuario_edicao = get_object_or_404(User, pk=kwargs["user_id"])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.usuario_edicao
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["modo_edicao"] = True
        context["usuario_edicao"] = self.usuario_edicao
        return context


class ProcessamentoStatusView(LoginRequiredMixin, View):
    login_url = reverse_lazy("portal_login")

    def get(self, request, codigo):
        status = obter_status_processamento_para_portal(codigo)
        return JsonResponse(
            {
                "codigo": status.codigo,
                "status": status.status,
                "status_codigo": status.status_codigo,
                "origem": status.origem,
                "formato_saida": status.formato_saida,
                "total_documentos": status.total_documentos,
                "total_processados": status.total_processados,
                "total_tokens": status.total_tokens,
                "percentual": status.percentual,
                "duracao_minutos": status.duracao_minutos,
                "iniciado_em": status.iniciado_em,
                "finalizado_em": status.finalizado_em,
                "mensagem_erro": status.mensagem_erro,
                "etapa_atual": status.etapa_atual,
                "documento_atual_nome": status.documento_atual_nome,
                "ultima_atividade_em": status.ultima_atividade_em,
                "ultima_atividade_humanizada": status.ultima_atividade_humanizada,
                "possivel_travamento": status.possivel_travamento,
                "tem_arquivo_saida": status.tem_arquivo_saida,
                "download_saida_url": status.download_saida_url,
                "resumo": {
                    "total": status.resumo_total,
                    "em_andamento": status.resumo_em_andamento,
                    "concluidos": status.resumo_concluidos,
                    "com_erro": status.resumo_com_erro,
                },
            }
        )


class ProcessamentoSaidaDownloadView(LoginRequiredMixin, View):
    login_url = reverse_lazy("portal_login")

    def get(self, request, codigo):
        processamento = get_object_or_404(Processamento, codigo=codigo)
        if not processamento.arquivo_saida:
            raise Http404("Este processamento ainda nao possui arquivo de saida.")

        processamento.arquivo_saida.open("rb")
        return FileResponse(
            processamento.arquivo_saida,
            as_attachment=True,
            filename=self._build_download_filename(processamento),
        )

    def _build_download_filename(self, processamento):
        source_name = processamento.arquivo_saida_nome or processamento.arquivo_saida.name
        extension = Path(source_name).suffix or ""
        return f"saida_{processamento.codigo}{extension}"
