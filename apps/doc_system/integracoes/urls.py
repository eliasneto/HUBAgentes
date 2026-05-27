from django.urls import path

from apps.doc_system.integracoes.views import IntegracoesDocView

app_name = "integracoes"

urlpatterns = [
    path("", IntegracoesDocView.as_view(), name="index"),
]
