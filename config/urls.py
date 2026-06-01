"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

from apps.auditoria.views import AuditoriaView
from apps.core.views import (
    AgenteExecucaoView,
    AgentePortalCreateView,
    AgentePortalLegacyCreateRedirectView,
    AgentePortalUpdateView,
    AgentesLeituraView,
    AgentesGerenciamentoView,
    FonteDocumentoCreateView,
    FonteDocumentoUpdateView,
    FontesDocumentosView,
    IntegracaoCreateView,
    IntegracaoDeleteView,
    IntegracaoUpdateView,
    IntegracoesView,
    IntegracaoValidarView,
    PortalLoginView,
    PortalLogoutView,
    PortalPainelView,
    ProcessamentoStatusView,
    ProcessamentoSaidaDownloadView,
    ProcessamentosView,
    UsuarioPortalCreateView,
    UsuarioPortalUpdateView,
    UsuariosAcessosView,
)

urlpatterns = [
    path('', PortalLoginView.as_view(), name='portal_login'),
    path('doc-system/', include('apps.doc_system.urls')),
    path('painel/', PortalPainelView.as_view(), name='portal_painel'),
    path('agentes-de-leitura/', AgentesLeituraView.as_view(), name='portal_agentes_leitura'),
    path('agentes/', AgentesGerenciamentoView.as_view(), name='portal_agentes_gerenciar'),
    path('agentes/novo/', AgentePortalCreateView.as_view(), name='portal_agente_criar'),
    path('agentes/<slug:slug>/editar/', AgentePortalUpdateView.as_view(), name='portal_agente_editar'),
    path('agentes-de-leitura/novo/', AgentePortalLegacyCreateRedirectView.as_view(), name='portal_agente_criar_legacy'),
    path('agentes-de-leitura/<slug:slug>/executar/', AgenteExecucaoView.as_view(), name='portal_agente_executar'),
    path('fontes-de-documentos/', FontesDocumentosView.as_view(), name='portal_fontes_documentos'),
    path('fontes-de-documentos/nova/', FonteDocumentoCreateView.as_view(), name='portal_fonte_documento_criar'),
    path('fontes-de-documentos/<str:tipo>/<int:fonte_id>/editar/', FonteDocumentoUpdateView.as_view(), name='portal_fonte_documento_editar'),
    path('integracoes/', IntegracoesView.as_view(), name='portal_integracoes'),
    path('integracoes/novo/', IntegracaoCreateView.as_view(), name='portal_integracao_criar'),
    path('integracoes/<str:tipo>/<int:integracao_id>/editar/', IntegracaoUpdateView.as_view(), name='portal_integracao_editar'),
    path('integracoes/<str:tipo>/<int:integracao_id>/validar/', IntegracaoValidarView.as_view(), name='portal_integracao_validar'),
    path('integracoes/<str:tipo>/<int:integracao_id>/excluir/', IntegracaoDeleteView.as_view(), name='portal_integracao_excluir'),
    path('processamentos/', ProcessamentosView.as_view(), name='portal_processamentos'),
    path('processamentos/<str:codigo>/status/', ProcessamentoStatusView.as_view(), name='portal_processamento_status'),
    path('processamentos/<str:codigo>/saida/', ProcessamentoSaidaDownloadView.as_view(), name='portal_processamento_download_saida'),
    path('historico-e-auditoria/', AuditoriaView.as_view(), name='portal_auditoria'),
    path('usuarios-e-acessos/', UsuariosAcessosView.as_view(), name='portal_usuarios_acessos'),
    path('usuarios-e-acessos/novo/', UsuarioPortalCreateView.as_view(), name='portal_usuario_criar'),
    path('usuarios-e-acessos/<int:user_id>/editar/', UsuarioPortalUpdateView.as_view(), name='portal_usuario_editar'),
    path('sair/', PortalLogoutView.as_view(), name='portal_logout'),
    path('admini/', admin.site.urls),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
