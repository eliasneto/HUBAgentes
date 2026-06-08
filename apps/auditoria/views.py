from django.views.generic import TemplateView

from apps.auditoria.selectors import listar_eventos_para_portal
from apps.core.views import AnalistaOuAdminRequiredMixin


class AuditoriaView(AnalistaOuAdminRequiredMixin, TemplateView):
    template_name = "portal_operacional/auditoria.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["auditoria"] = listar_eventos_para_portal(
            page_number=self.request.GET.get("page"),
            filtro_modulo=self.request.GET.get("modulo", ""),
            filtro_busca=self.request.GET.get("busca", ""),
            per_page=25,
        )
        return context
