from django.conf import settings


def app_version(_request):
    return {"APP_VERSION": getattr(settings, "APP_VERSION", "1.0.0")}


def paginas_menu(request):
    """Injeta o set de chaves de páginas acessíveis pelo usuário logado."""
    if not request.user.is_authenticated:
        return {"paginas_menu": set()}
    from apps.core.models import paginas_do_usuario
    return {"paginas_menu": paginas_do_usuario(request.user)}


def mascote_config(request):
    """Injeta se o mascote Biel está ativo (lido do singleton ConfiguracaoGeral)."""
    if not request.user.is_authenticated:
        return {"mascote_ativo": False}
    try:
        from apps.core.models import ConfiguracaoGeral
        return {"mascote_ativo": ConfiguracaoGeral.obter().mascote_ativo}
    except Exception:
        return {"mascote_ativo": True}
