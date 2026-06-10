from django.urls import path

from apps.doc_system.guia_google_drive.views import GuiaGoogleDriveDocView

app_name = "guia_google_drive"

urlpatterns = [
    path("", GuiaGoogleDriveDocView.as_view(), name="index"),
]
