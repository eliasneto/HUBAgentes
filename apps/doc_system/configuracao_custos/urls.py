from django.urls import path
from apps.doc_system.configuracao_custos.views import ConfiguracaoCustosDocView

urlpatterns = [
    path("", ConfiguracaoCustosDocView.as_view(), name="doc_configuracao_custos"),
]
