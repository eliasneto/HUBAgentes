from django.urls import path

from apps.doc_system.usuarios_acessos.views import UsuariosAcessosDocView

app_name = "usuarios_acessos"

urlpatterns = [
    path("", UsuariosAcessosDocView.as_view(), name="index"),
]
