import logging
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
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


class PagePermissionMixin(LoginRequiredMixin):
    """Verifica se o usuário tem acesso à página via PermissaoMenu."""
    page_key = ""
    login_url = reverse_lazy("portal_login")

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        from apps.core.models import usuario_pode_acessar_pagina
        if not usuario_pode_acessar_pagina(request.user, self.page_key):
            raise PermissionDenied("Voce nao tem permissao para acessar esta pagina.")
        return super().dispatch(request, *args, **kwargs)


class PortalAdministradorRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    login_url = reverse_lazy("portal_login")

    def test_func(self):
        user = self.request.user
        return user.is_superuser or user.groups.filter(name="administrador").exists()

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        raise PermissionDenied("Apenas administradores podem acessar esta area.")


class AnalistaOuAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Permite acesso a administradores e analistas."""
    login_url = reverse_lazy("portal_login")

    def test_func(self):
        user = self.request.user
        return user.is_superuser or user.groups.filter(
            name__in=["administrador", "analista"]
        ).exists()

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return super().handle_no_permission()
        raise PermissionDenied("Apenas administradores e analistas podem acessar esta area.")


_TEMPLATE_MAP = {
    "principal": "portal_operacional/login.html",
    "v2": "portal_operacional/login_v2.html",
    "v3": "portal_operacional/login_v3.html",
}


def _garantir_pasta_pessoal(usuario):
    """Cria a pasta pessoal do usuário se ela não existir (usada no login e na criação de usuário)."""
    from apps.integracoes.models import LocalStorageIntegration, IntegrationStatus
    if LocalStorageIntegration.objects.filter(created_by=usuario, compartilhada=False).exists():
        return
    caminho = f"/app/entradas/{usuario.username}"
    try:
        Path(caminho).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    nome = f"Pasta de {usuario.get_full_name() or usuario.username}"
    sufixo = 1
    nome_final = nome
    while LocalStorageIntegration.objects.filter(nome=nome_final).exists():
        sufixo += 1
        nome_final = f"{nome} ({sufixo})"
    LocalStorageIntegration.objects.create(
        nome=nome_final,
        base_path=caminho,
        status=IntegrationStatus.ATIVA,
        recursive_scan=True,
        allowed_extensions=[],
        created_by=usuario,
        updated_by=usuario,
    )


class PortalLoginView(LoginView):
    redirect_authenticated_user = True
    next_page = reverse_lazy("portal_painel")

    def form_valid(self, form):
        response = super().form_valid(form)
        _garantir_pasta_pessoal(self.request.user)
        return response

    @property
    def template_name(self):
        from apps.core.models import ConfiguracaoTelaLogin
        config = ConfiguracaoTelaLogin.obter()
        return _TEMPLATE_MAP.get(config.tela_ativa, "portal_operacional/login.html")

    def form_invalid(self, form):
        messages.error(self.request, "Usuario ou senha invalidos.")
        redirect_url = reverse("portal_login")
        next_url = self.get_redirect_url()
        if next_url:
            redirect_url = f"{redirect_url}?{urlencode({self.redirect_field_name: next_url})}"
        return redirect(redirect_url)


class PortalLogoutView(LogoutView):
    next_page = reverse_lazy("portal_login")


def _obter_dados_dashboard():
    from django.db.models import Count, Sum, Q
    from apps.processamentos.models import Processamento, ProcessingStatus, DocumentStatus

    concluidos = {
        ProcessingStatus.CONCLUIDO_SUCESSO,
        ProcessingStatus.CONCLUIDO_ERRO,
    }

    # 1. Processamentos por agente
    proc_por_agente = (
        Processamento.objects
        .filter(agente__isnull=False)
        .values("agente__nome")
        .annotate(total=Count("id"))
        .order_by("-total")[:10]
    )

    # 2. Tokens totais por integração de IA
    tokens_por_integracao = (
        Processamento.objects
        .filter(ai_provider_integration_snapshot__isnull=False, total_tokens__isnull=False)
        .values("ai_provider_integration_snapshot__nome")
        .annotate(total=Sum("total_tokens"))
        .order_by("-total")[:10]
    )

    # 3. Custo em BRL por integração de IA
    custo_por_integracao = (
        Processamento.objects
        .filter(ai_provider_integration_snapshot__isnull=False, custo_brl__isnull=False)
        .values("ai_provider_integration_snapshot__nome")
        .annotate(total=Sum("custo_brl"))
        .order_by("-total")[:10]
    )

    # 4. Documentos processados por agente
    docs_por_agente = (
        Processamento.objects
        .filter(agente__isnull=False)
        .values("agente__nome")
        .annotate(total=Sum("total_processados"))
        .order_by("-total")[:10]
    )

    return {
        "proc_por_agente": list(proc_por_agente),
        "tokens_por_integracao": list(tokens_por_integracao),
        "custo_por_integracao": list(custo_por_integracao),
        "docs_por_agente": list(docs_por_agente),
    }


class PortalPainelView(LoginRequiredMixin, TemplateView):
    template_name = "portal_operacional/menu_inicial.html"
    login_url = reverse_lazy("portal_login")

    def get_context_data(self, **kwargs):
        from apps.core.models import ConfiguracaoGeral
        context = super().get_context_data(**kwargs)
        config = ConfiguracaoGeral.obter()
        visibilidade = config.visibilidade_dashboard
        user = self.request.user

        pode_ver = False
        if visibilidade == "operacional":
            pode_ver = True
        elif visibilidade == "analista":
            pode_ver = (
                user.is_superuser
                or user.groups.filter(name__in=["administrador", "analista"]).exists()
            )
        else:  # administrador
            pode_ver = (
                user.is_superuser
                or user.groups.filter(name="administrador").exists()
            )

        context["exibir_dashboard"] = pode_ver
        if pode_ver:
            context["dashboard"] = _obter_dados_dashboard()
        return context


class AgentesLeituraView(LoginRequiredMixin, TemplateView):
    template_name = "portal_operacional/agentes_leitura.html"
    login_url = reverse_lazy("portal_login")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["agentes"] = listar_agentes_para_portal(usuario=self.request.user)
        return context


class AgentesGerenciamentoView(AnalistaOuAdminRequiredMixin, TemplateView):
    template_name = "portal_operacional/agentes_leitura.html"
    login_url = reverse_lazy("portal_login")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["agentes"] = listar_agentes_para_gerenciamento()
        context["modo_gerenciamento_agentes"] = True
        return context


class AgentePortalFormMixin(AnalistaOuAdminRequiredMixin):
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


class AgentePortalDeleteView(AnalistaOuAdminRequiredMixin, View):
    login_url = reverse_lazy("portal_login")

    def post(self, request, slug):
        agente = get_object_or_404(AgenteIA, slug=slug)
        nome = agente.nome
        agente.delete()
        messages.success(request, f"Agente '{nome}' excluído com sucesso.")
        return redirect("portal_agentes_gerenciar")


class AgentePortalLegacyCreateRedirectView(
    AnalistaOuAdminRequiredMixin,
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
            actor=request.user,
        )
        show_upload = form.runtime_fields_schema.get("show_file_upload")
        if show_upload:
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
        context["fontes"] = listar_fontes_documentos_para_portal(usuario=self.request.user)
        return context


class FonteDocumentoPortalFormMixin(PortalAdministradorRequiredMixin):
    template_name = "portal_operacional/fonte_documento_form.html"
    login_url = reverse_lazy("portal_login")

    form_classes = {
        "google-drive-folder": GoogleDriveFolderSourcePortalForm,
    }
    model_classes = {
        "google-drive-folder": GoogleDriveFolderSource,
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

    def form_valid(self, form):
        integration = form.save(commit=False)
        if self.integration_type == "storage-local":
            integration.compartilhada = True
            integration.save()
            form.save_m2m()
            try:
                Path(integration.base_path).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        else:
            integration.save()
            form.save_m2m()
        messages.success(
            self.request,
            f"Conexao {integration.nome} criada com sucesso.",
        )
        return redirect("portal_integracoes")


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


class IntegracaoDeleteView(PortalAdministradorRequiredMixin, View):
    login_url = reverse_lazy("portal_login")

    model_classes = {
        "ia": AIProviderIntegration,
        "google-drive": GoogleDriveIntegration,
        "storage-local": LocalStorageIntegration,
    }

    def post(self, request, tipo, integracao_id):
        model_class = self.model_classes.get(tipo)
        if model_class is None:
            raise Http404("Tipo de integracao nao suportado.")
        integration = get_object_or_404(model_class, pk=integracao_id)
        nome = integration.nome
        integration.delete()
        messages.success(request, f"Integracao '{nome}' excluida com sucesso.")
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
    def form_valid(self, form):
        usuario = form.save()
        _garantir_pasta_pessoal(usuario)
        messages.success(
            self.request,
            f"Usuario {usuario.username} criado. Pasta pessoal configurada automaticamente.",
        )
        return redirect(reverse("portal_usuario_editar", kwargs={"user_id": usuario.pk}))


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
        from apps.core.models import PermissaoMenu
        context = super().get_context_data(**kwargs)
        context["modo_edicao"] = True
        context["usuario_edicao"] = self.usuario_edicao
        context["todas_paginas"] = PermissaoMenu.objects.all()
        # Páginas que o grupo do usuário já concede
        context["paginas_grupo"] = set(
            PermissaoMenu.objects.filter(
                grupos__in=self.usuario_edicao.groups.all()
            ).values_list("chave", flat=True)
        )
        # Páginas extras individuais do usuário
        context["paginas_extras"] = set(
            self.usuario_edicao.permissoes_menu_extras.values_list("chave", flat=True)
        )
        return context

    def form_valid(self, form):
        usuario = form.save()
        # Salva permissões extras individuais
        from apps.core.models import PermissaoMenu
        chaves_extras = self.request.POST.getlist("permissao_extra")
        # Filtra apenas as que NÃO vêm do grupo (não salvar redundâncias)
        paginas_grupo = set(
            PermissaoMenu.objects.filter(
                grupos__in=usuario.groups.all()
            ).values_list("chave", flat=True)
        )
        chaves_validas = [c for c in chaves_extras if c not in paginas_grupo]
        extras = PermissaoMenu.objects.filter(chave__in=chaves_validas)
        usuario.permissoes_menu_extras.set(extras)
        messages.success(self.request, f"Usuario {usuario.username} salvo com sucesso.")
        return redirect(reverse("portal_usuario_editar", kwargs={"user_id": usuario.pk}))


class LocalStorageSubpastasView(LoginRequiredMixin, View):
    login_url = reverse_lazy("portal_login")

    def get(self, request, integration_id):
        from apps.integracoes.models import LocalStorageIntegration
        from apps.integracoes.services.local_storage import (
            list_subfolders_from_relative_folder,
            LocalStorageServiceError,
        )
        try:
            integration = LocalStorageIntegration.objects.get(pk=integration_id)
            subpastas = list_subfolders_from_relative_folder(integration, "")
            return JsonResponse({
                "subpastas": [p.name for p in subpastas],
                "base_path": integration.base_path,
            })
        except LocalStorageIntegration.DoesNotExist:
            return JsonResponse({"subpastas": [], "erro": "Integracao nao encontrada"})
        except LocalStorageServiceError as exc:
            return JsonResponse({"subpastas": [], "erro": str(exc)})


class LocalStorageArquivosView(AnalistaOuAdminRequiredMixin, View):
    """Página de gerenciamento de arquivos de uma integração local."""

    def _get_integration(self, pk):
        return get_object_or_404(LocalStorageIntegration, pk=pk)

    def _listar_arquivos(self, base_path: Path):
        arquivos = []
        if base_path.exists():
            for f in sorted(base_path.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(base_path)
                    arquivos.append({
                        "nome": f.name,
                        "caminho": str(rel).replace("\\", "/"),
                        "pasta": str(rel.parent).replace("\\", "/") if str(rel.parent) != "." else "",
                        "tamanho": f.stat().st_size,
                    })
        return arquivos

    def get(self, request, integracao_id):
        integration = self._get_integration(integracao_id)
        base_path = Path(integration.base_path)
        arquivos = self._listar_arquivos(base_path)
        return render(request, "portal_operacional/local_storage_arquivos.html", {
            "integration": integration,
            "arquivos": arquivos,
            "total": len(arquivos),
        })


def _usuario_pode_escrever(usuario, integration):
    """Retorna True se o usuário tem permissão de escrita na integração."""
    from apps.integracoes.models import PastaCompartilhadaUsuario, PermissaoPasta
    # Pasta pessoal: só o dono, nunca outro (nem admin)
    if not integration.compartilhada:
        return integration.created_by_id == usuario.pk
    # Pasta compartilhada: admin sempre pode; membros com escrita também
    if usuario.is_superuser or usuario.groups.filter(name="administrador").exists():
        return True
    membro = PastaCompartilhadaUsuario.objects.filter(
        integracao=integration, usuario=usuario
    ).first()
    return membro is not None and membro.permissao == PermissaoPasta.ESCRITA


class LocalStorageUploadView(AnalistaOuAdminRequiredMixin, View):
    """Recebe arquivos via POST e salva na base_path da integração."""

    EXTENSOES_PERMITIDAS = {"pdf", "txt", "csv", "png", "jpg", "jpeg", "xlsx"}
    MAX_ARQUIVO_MB = 100

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return JsonResponse({"enviados": [], "erros": ["Sessão expirada. Faça login novamente."]}, status=401)
        return JsonResponse({"enviados": [], "erros": ["Você não tem permissão para fazer upload nesta pasta."]}, status=403)

    def post(self, request, integracao_id):
        from apps.integracoes.models import LocalStorageIntegration
        integration = get_object_or_404(LocalStorageIntegration, pk=integracao_id)
        if not _usuario_pode_escrever(request.user, integration):
            return JsonResponse({"enviados": [], "erros": ["Voce nao tem permissao de escrita nesta pasta."]}, status=403)
        base_path = Path(integration.base_path)
        base_path.mkdir(parents=True, exist_ok=True)

        enviados = []
        erros = []

        for campo, arquivo in request.FILES.items():
            rel_path = request.POST.get(f"rel_{campo}", arquivo.name)
            # segurança: impede path traversal
            try:
                destino = (base_path / rel_path).resolve()
                destino.relative_to(base_path.resolve())
            except ValueError:
                erros.append(f"{arquivo.name}: caminho invalido")
                continue

            ext = destino.suffix.lstrip(".").lower()
            if ext not in self.EXTENSOES_PERMITIDAS:
                erros.append(f"{arquivo.name}: extensao .{ext} nao suportada")
                continue

            if arquivo.size > self.MAX_ARQUIVO_MB * 1024 * 1024:
                erros.append(f"{arquivo.name}: arquivo maior que {self.MAX_ARQUIVO_MB} MB")
                continue

            destino.parent.mkdir(parents=True, exist_ok=True)
            with open(destino, "wb+") as f:
                for chunk in arquivo.chunks():
                    f.write(chunk)
            enviados.append(str(Path(rel_path).as_posix()))

        return JsonResponse({"enviados": enviados, "erros": erros})


class LocalStorageExcluirArquivoView(AnalistaOuAdminRequiredMixin, View):
    """Exclui um arquivo da base_path da integração via DELETE."""

    def post(self, request, integracao_id):
        import json
        from apps.integracoes.models import LocalStorageIntegration
        integration = get_object_or_404(LocalStorageIntegration, pk=integracao_id)
        if not _usuario_pode_escrever(request.user, integration):
            return JsonResponse({"ok": False, "erro": "Voce nao tem permissao de escrita nesta pasta."}, status=403)
        base_path = Path(integration.base_path).resolve()

        try:
            body = json.loads(request.body)
            rel_path = body.get("caminho", "")
        except (ValueError, KeyError):
            return JsonResponse({"ok": False, "erro": "Payload invalido"}, status=400)

        try:
            alvo = (base_path / rel_path).resolve()
            alvo.relative_to(base_path)
        except ValueError:
            return JsonResponse({"ok": False, "erro": "Caminho invalido"}, status=400)

        if not alvo.is_file():
            return JsonResponse({"ok": False, "erro": "Arquivo nao encontrado"}, status=404)

        alvo.unlink()
        return JsonResponse({"ok": True})


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


class ProcessamentoVerificarSaidaView(LoginRequiredMixin, View):
    """Verifica se o arquivo de saída ainda existe antes do download."""
    login_url = reverse_lazy("portal_login")

    def get(self, request, codigo):
        user = request.user
        is_admin = user.is_superuser or user.groups.filter(name="administrador").exists()
        filtro = {} if is_admin else {"iniciado_por": user}
        processamento = get_object_or_404(Processamento, codigo=codigo, **filtro)
        if processamento.arquivo_saida:
            return JsonResponse({"disponivel": True})
        return JsonResponse({"disponivel": False}, status=410)


class ProcessamentoSaidaDownloadView(LoginRequiredMixin, View):
    login_url = reverse_lazy("portal_login")

    def get(self, request, codigo):
        user = request.user
        is_admin = user.is_superuser or user.groups.filter(name="administrador").exists()
        filtro = {} if is_admin else {"iniciado_por": user}
        processamento = get_object_or_404(Processamento, codigo=codigo, **filtro)
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


def _proxima_data_limpeza(dia: int):
    from datetime import date
    import calendar
    hoje = date.today()
    # Tenta no mês atual
    ultimo_dia = calendar.monthrange(hoje.year, hoje.month)[1]
    dia_mes = min(dia, ultimo_dia)
    candidato = date(hoje.year, hoje.month, dia_mes)
    if candidato <= hoje:
        # Já passou — próximo mês
        if hoje.month == 12:
            ano, mes = hoje.year + 1, 1
        else:
            ano, mes = hoje.year, hoje.month + 1
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        candidato = date(ano, mes, min(dia, ultimo_dia))
    return candidato


class ConfiguracaoGeralView(PortalAdministradorRequiredMixin, TemplateView):
    template_name = "portal_operacional/configuracao_geral.html"

    def get_context_data(self, **kwargs):
        from apps.core.models import ConfiguracaoGeral, VisibilidadeDashboard
        from apps.integracoes.models import LocalStorageIntegration
        context = super().get_context_data(**kwargs)
        config = ConfiguracaoGeral.obter()
        context["config"] = config
        context["opcoes"] = VisibilidadeDashboard.choices
        if config.limpeza_automatica_ativa:
            context["proxima_limpeza"] = _proxima_data_limpeza(config.dia_execucao_limpeza)
        context["pastas_compartilhadas"] = (
            LocalStorageIntegration.objects
            .filter(compartilhada=True)
            .select_related("created_by")
            .prefetch_related("membros__usuario")
            .order_by("nome")
        )
        User = get_user_model()
        context["todos_usuarios"] = (
            User.objects.filter(is_active=True).order_by("first_name", "username")
        )
        return context


class CriarPastaCompartilhadaView(PortalAdministradorRequiredMixin, View):
    def post(self, request):
        import re
        nome_pasta = request.POST.get("nome_pasta", "").strip()
        nome_integracao = request.POST.get("nome_integracao", "").strip()

        if not nome_pasta or not nome_integracao:
            messages.error(request, "Informe o nome da pasta e o nome da integração.")
            return redirect("portal_configuracao_geral")

        slug = re.sub(r"[^\w\-]", "_", nome_pasta).strip("_")
        caminho = f"/app/entradas/{slug}"

        if LocalStorageIntegration.objects.filter(base_path=caminho).exists():
            messages.error(request, f"Já existe uma pasta configurada em {caminho}.")
            return redirect("portal_configuracao_geral")

        if LocalStorageIntegration.objects.filter(nome=nome_integracao).exists():
            messages.error(request, f"Já existe uma integração com o nome '{nome_integracao}'.")
            return redirect("portal_configuracao_geral")

        try:
            Path(caminho).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messages.error(request, f"Não foi possível criar a pasta no servidor: {exc}")
            return redirect("portal_configuracao_geral")

        from apps.integracoes.models import IntegrationStatus
        LocalStorageIntegration.objects.create(
            nome=nome_integracao,
            base_path=caminho,
            status=IntegrationStatus.ATIVA,
            compartilhada=True,
            recursive_scan=True,
            allowed_extensions=[],
            created_by=request.user,
            updated_by=request.user,
        )
        messages.success(request, f"Pasta compartilhada '{nome_integracao}' criada com sucesso.")
        return redirect("portal_configuracao_geral")


class ExcluirPastaCompartilhadaView(PortalAdministradorRequiredMixin, View):
    def post(self, request, integracao_id):
        import shutil
        integration = get_object_or_404(LocalStorageIntegration, pk=integracao_id)
        nome = integration.nome
        base_path = integration.base_path
        eh_compartilhada = integration.compartilhada
        integration.hard_delete()
        try:
            if base_path and Path(base_path).exists():
                shutil.rmtree(base_path)
        except OSError:
            pass
        messages.success(request, f"Pasta '{nome}' removida do sistema e do servidor.")
        if eh_compartilhada:
            return redirect("portal_configuracao_geral")
        return redirect("portal_fontes_documentos")


class AdicionarUsuarioPastaView(PortalAdministradorRequiredMixin, View):
    def post(self, request, integracao_id):
        from apps.integracoes.models import PastaCompartilhadaUsuario, PermissaoPasta
        integration = get_object_or_404(
            LocalStorageIntegration, pk=integracao_id, compartilhada=True
        )
        User = get_user_model()
        user_id = request.POST.get("user_id")
        if not user_id:
            messages.error(request, "Selecione um usuário.")
            return redirect("portal_configuracao_geral")
        usuario = get_object_or_404(User, pk=user_id)
        PastaCompartilhadaUsuario.objects.get_or_create(
            integracao=integration,
            usuario=usuario,
            defaults={"permissao": PermissaoPasta.LEITURA},
        )
        messages.success(
            request,
            f"Usuário {usuario.get_full_name() or usuario.username} adicionado com permissão de leitura.",
        )
        return redirect("portal_configuracao_geral")


class RemoverUsuarioPastaView(PortalAdministradorRequiredMixin, View):
    def post(self, request, integracao_id, user_id):
        from apps.integracoes.models import PastaCompartilhadaUsuario
        integration = get_object_or_404(
            LocalStorageIntegration, pk=integracao_id, compartilhada=True
        )
        User = get_user_model()
        usuario = get_object_or_404(User, pk=user_id)
        PastaCompartilhadaUsuario.objects.filter(
            integracao=integration, usuario=usuario
        ).delete()
        messages.success(
            request,
            f"Usuário {usuario.get_full_name() or usuario.username} removido da pasta '{integration.nome}'.",
        )
        return redirect("portal_configuracao_geral")


class AlterarPermissaoPastaView(PortalAdministradorRequiredMixin, View):
    def post(self, request, integracao_id, user_id):
        from apps.integracoes.models import PastaCompartilhadaUsuario, PermissaoPasta
        membro = get_object_or_404(
            PastaCompartilhadaUsuario,
            integracao_id=integracao_id,
            usuario_id=user_id,
        )
        nova = (
            PermissaoPasta.ESCRITA
            if membro.permissao == PermissaoPasta.LEITURA
            else PermissaoPasta.LEITURA
        )
        membro.permissao = nova
        membro.save()
        label = dict(PermissaoPasta.choices)[nova]
        messages.success(
            request,
            f"Permissão de {membro.usuario.get_full_name() or membro.usuario.username} alterada para {label}.",
        )
        return redirect("portal_configuracao_geral")


class SalvarConfiguracaoGeralView(PortalAdministradorRequiredMixin, View):
    def post(self, request):
        from apps.core.models import ConfiguracaoGeral, VisibilidadeDashboard
        valor = request.POST.get("visibilidade_dashboard", "administrador")
        if valor not in dict(VisibilidadeDashboard.choices):
            valor = "administrador"
        try:
            dias = max(1, min(365, int(request.POST.get("dias_retencao_arquivos", 30))))
        except (ValueError, TypeError):
            dias = 30
        config = ConfiguracaoGeral.obter()
        config.visibilidade_dashboard = valor
        config.limpeza_automatica_ativa = "limpeza_automatica_ativa" in request.POST
        config.atualizado_por = request.user
        config.save()
        messages.success(request, "Configurações gerais salvas com sucesso.")
        return redirect("portal_configuracao_geral")


class ConfiguracaoTelaLoginView(PortalAdministradorRequiredMixin, TemplateView):
    template_name = "portal_operacional/configuracao_tela_login.html"

    def get_context_data(self, **kwargs):
        from apps.core.models import ConfiguracaoTelaLogin, TelaLoginOpcao
        context = super().get_context_data(**kwargs)
        config = ConfiguracaoTelaLogin.obter()
        context["tela_ativa"] = config.tela_ativa
        context["tela_ativa_label"] = dict(TelaLoginOpcao.choices).get(config.tela_ativa, config.tela_ativa)
        return context


class AtivarTelaLoginView(PortalAdministradorRequiredMixin, View):
    def post(self, request):
        from apps.core.models import ConfiguracaoTelaLogin, TelaLoginOpcao
        tela = request.POST.get("tela", "principal")
        if tela not in dict(TelaLoginOpcao.choices):
            tela = "principal"
        config = ConfiguracaoTelaLogin.obter()
        config.tela_ativa = tela
        config.atualizado_por = request.user
        config.save()
        messages.success(request, f"Tela de login alterada com sucesso.")
        return redirect("portal_tela_login")


class LoginPreviewView(PortalAdministradorRequiredMixin, View):
    def get(self, request, tela):
        template = _TEMPLATE_MAP.get(tela, "portal_operacional/login.html")
        from django.template.response import TemplateResponse
        return TemplateResponse(request, template, {})
