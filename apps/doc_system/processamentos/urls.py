from django.urls import path

from apps.doc_system.processamentos.views import ProcessamentosDocView

app_name = "processamentos"

urlpatterns = [
    path("", ProcessamentosDocView.as_view(), name="index"),
]
