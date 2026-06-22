from django.urls import path

from apps.doc_system.otimizacao_custos_ia.views import OtimizacaoCustosIADocView

app_name = "otimizacao_custos_ia"

urlpatterns = [
    path("", OtimizacaoCustosIADocView.as_view(), name="index"),
]
