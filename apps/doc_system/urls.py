from django.urls import include, path

from apps.doc_system.views import DocSystemIndexView

app_name = "doc_system"

urlpatterns = [
    path("", DocSystemIndexView.as_view(), name="index"),
    path(
        "painel-inicial/",
        include("apps.doc_system.painel_inicial.urls"),
    ),
    path(
        "agentes/",
        include("apps.doc_system.agentes.urls"),
    ),
    path(
        "gerenciar-agentes/",
        include("apps.doc_system.gerenciar_agentes.urls"),
    ),
    path(
        "integracoes/",
        include("apps.doc_system.integracoes.urls"),
    ),
    path(
        "processamentos/",
        include("apps.doc_system.processamentos.urls"),
    ),
    path(
        "fontes-documentos/",
        include("apps.doc_system.fontes_documentos.urls"),
    ),
    path(
        "usuarios-e-acessos/",
        include("apps.doc_system.usuarios_acessos.urls"),
    ),
]
