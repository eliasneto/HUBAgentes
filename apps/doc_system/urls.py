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
    path(
        "configuracao-custos/",
        include("apps.doc_system.configuracao_custos.urls"),
    ),
    path(
        "configuracoes-gerais/",
        include("apps.doc_system.configuracoes_gerais.urls"),
    ),
    path(
        "guia-google-drive-api/",
        include("apps.doc_system.guia_google_drive.urls"),
    ),
    path(
        "otimizacao-custos-ia/",
        include("apps.doc_system.otimizacao_custos_ia.urls"),
    ),
]
