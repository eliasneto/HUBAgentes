from django.urls import path
from apps.doc_system.rotina_automatica.views import RotinaAutomaticaDocView

urlpatterns = [
    path("", RotinaAutomaticaDocView.as_view(), name="doc_rotina_automatica"),
]
