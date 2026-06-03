from django.urls import path

from apps.custos.views import (
    ConfiguracaoCustosView,
    ConfiguracaoFinanceiraUpdateView,
    PrecificacaoModeloCreateView,
    PrecificacaoModeloDeleteView,
    PrecificacaoModeloUpdateView,
)

urlpatterns = [
    path('', ConfiguracaoCustosView.as_view(), name='portal_configuracao_custos'),
    path('modelos/novo/', PrecificacaoModeloCreateView.as_view(), name='portal_precificacao_criar'),
    path('modelos/<int:pk>/editar/', PrecificacaoModeloUpdateView.as_view(), name='portal_precificacao_editar'),
    path('modelos/<int:pk>/excluir/', PrecificacaoModeloDeleteView.as_view(), name='portal_precificacao_excluir'),
    path('cotacao/salvar/', ConfiguracaoFinanceiraUpdateView.as_view(), name='portal_cotacao_salvar'),
]
