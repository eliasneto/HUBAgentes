from django.views.generic import TemplateView


class AgentesDocView(TemplateView):
    template_name = "portal_operacional/doc_system_agentes.html"
