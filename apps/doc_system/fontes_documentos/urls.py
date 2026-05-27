from django.urls import path

from apps.doc_system.fontes_documentos.views import FontesDocumentosDocView

app_name = "fontes_documentos"

urlpatterns = [
    path("", FontesDocumentosDocView.as_view(), name="index"),
]
