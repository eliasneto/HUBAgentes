from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import FormView, TemplateView

from apps.core.views import PortalAdministradorRequiredMixin
from apps.custos.forms import ConfiguracaoFinanceiraForm, PrecificacaoModeloForm
from apps.custos.models import ConfiguracaoFinanceira, PrecificacaoModelo
from apps.custos.selectors import listar_precificacoes, obter_configuracao_financeira


class ConfiguracaoCustosView(PortalAdministradorRequiredMixin, TemplateView):
    template_name = "portal_operacional/configuracao_custos.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        config = obter_configuracao_financeira()
        context["precificacoes"] = listar_precificacoes(
            page_number=self.request.GET.get("page"),
            per_page=20,
        )
        context["configuracao"] = config
        context["form_cotacao"] = ConfiguracaoFinanceiraForm(instance=config)
        return context


class PrecificacaoModeloCreateView(PortalAdministradorRequiredMixin, FormView):
    template_name = "portal_operacional/configuracao_custos_modelo_form.html"
    form_class = PrecificacaoModeloForm
    success_url = reverse_lazy("portal_configuracao_custos")

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Precificacao adicionada com sucesso.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["titulo"] = "Nova Precificacao"
        context["cancelar_url"] = reverse_lazy("portal_configuracao_custos")
        return context


class PrecificacaoModeloUpdateView(PortalAdministradorRequiredMixin, FormView):
    template_name = "portal_operacional/configuracao_custos_modelo_form.html"
    form_class = PrecificacaoModeloForm
    success_url = reverse_lazy("portal_configuracao_custos")

    def get_object(self):
        return get_object_or_404(PrecificacaoModelo, pk=self.kwargs["pk"])

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.get_object()
        return kwargs

    def form_valid(self, form):
        form.save()
        messages.success(self.request, "Precificacao atualizada com sucesso.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["titulo"] = "Editar Precificacao"
        context["objeto"] = self.get_object()
        context["cancelar_url"] = reverse_lazy("portal_configuracao_custos")
        return context


class PrecificacaoModeloDeleteView(PortalAdministradorRequiredMixin, View):
    def post(self, request, pk):
        obj = get_object_or_404(PrecificacaoModelo, pk=pk)
        nome = obj.nome_modelo
        obj.delete()
        messages.success(request, f"Precificacao '{nome}' excluida.")
        return redirect("portal_configuracao_custos")


class ConfiguracaoFinanceiraUpdateView(PortalAdministradorRequiredMixin, View):
    def post(self, request):
        config = ConfiguracaoFinanceira.objects.order_by("-created_at").first()
        form = ConfiguracaoFinanceiraForm(request.POST, instance=config)
        if form.is_valid():
            instance = form.save(commit=False)
            instance.atualizado_por = request.user
            instance.save()
            messages.success(request, "Cotacao do dolar atualizada com sucesso.")
        else:
            messages.error(request, "Valor invalido para a cotacao do dolar.")
        return redirect("portal_configuracao_custos")
