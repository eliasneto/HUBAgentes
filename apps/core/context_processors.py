from django.conf import settings


def app_version(_request):
    return {"APP_VERSION": getattr(settings, "APP_VERSION", "1.0.0")}
