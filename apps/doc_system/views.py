from django.views.generic import TemplateView


class DocSystemIndexView(TemplateView):
    template_name = "portal_operacional/menu_inicial.html"
