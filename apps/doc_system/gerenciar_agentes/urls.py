from django.urls import path

from apps.doc_system.gerenciar_agentes.views import GerenciarAgentesDocView

app_name = "gerenciar_agentes"

urlpatterns = [
    path("", GerenciarAgentesDocView.as_view(), name="index"),
]
