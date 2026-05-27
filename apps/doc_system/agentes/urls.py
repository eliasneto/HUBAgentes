from django.urls import path

from apps.doc_system.agentes.views import AgentesDocView

app_name = "agentes"

urlpatterns = [
    path("", AgentesDocView.as_view(), name="index"),
]
