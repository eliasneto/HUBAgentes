from django.urls import path
from apps.doc_system.configuracoes_gerais.views import ConfiguracoesGeraisDocView

urlpatterns = [
    path("", ConfiguracoesGeraisDocView.as_view(), name="doc_configuracoes_gerais"),
]
