from django.urls import path

from apps.doc_system.painel_inicial.views import PainelInicialDocView

app_name = "painel_inicial"

urlpatterns = [
    path("", PainelInicialDocView.as_view(), name="index"),
]
