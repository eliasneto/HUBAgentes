from django import forms

from apps.integracoes.models import (
    AIProviderIntegration,
    GoogleDriveFolderSource,
    GoogleDriveIntegration,
    IntegrationStatus,
    LocalStorageIntegration,
)


class IntegrationPortalFormMixin:
    secret_fields = ()

    def __init__(self, *args, **kwargs):
        self.actor = kwargs.pop("actor", None)
        super().__init__(*args, **kwargs)
        self._original_secret_values = {
            field_name: getattr(self.instance, field_name, "")
            for field_name in self.secret_fields
            if getattr(self, "instance", None) is not None and self.instance.pk
        }
        self._prepare_secret_fields_for_edit()
        self._apply_portal_widgets()

    def _prepare_secret_fields_for_edit(self):
        if not self._original_secret_values:
            return
        for field_name in self.secret_fields:
            field = self.fields.get(field_name)
            if field is None:
                continue
            field.required = False
            field.help_text = "Deixe em branco para manter a credencial atual."
            field.widget.attrs["placeholder"] = "••••••••••••••••••••••••••••••••"
            self.initial[field_name] = ""

    def _apply_portal_widgets(self):
        for field_name, field in self.fields.items():
            css_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css_class} portal-input".strip()
            if field_name not in {"api_key", "credentials_json"}:
                field.widget.attrs.setdefault("autocomplete", "off")
        # Erro e definido pelo sistema, nao pelo usuario
        if "status" in self.fields:
            self.fields["status"].choices = [
                (IntegrationStatus.ATIVA, "Ativa"),
                (IntegrationStatus.INATIVA, "Inativa"),
            ]

    def save(self, commit=True):
        instance = super().save(commit=False)
        for field_name, original_value in self._original_secret_values.items():
            if field_name in self.fields and not self.cleaned_data.get(field_name):
                setattr(instance, field_name, original_value)
        if hasattr(instance, "allowed_extensions"):
            instance.allowed_extensions = ["pdf"]
        if self.actor is not None:
            if not instance.pk and hasattr(instance, "created_by"):
                instance.created_by = self.actor
            if hasattr(instance, "updated_by"):
                instance.updated_by = self.actor
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class AIProviderIntegrationPortalForm(IntegrationPortalFormMixin, forms.ModelForm):
    secret_fields = ("api_key",)

    class Meta:
        model = AIProviderIntegration
        fields = [
            "nome",
            "provider_type",
            "status",
            "default_model",
            "timeout_seconds",
            "api_key",
            "api_base_url",
            "organization_id",
            "project_id",
        ]
        labels = {
            "nome": "Nome",
            "provider_type": "Provedor",
            "status": "Status",
            "default_model": "Modelo padrao",
            "timeout_seconds": "Timeout em segundos",
            "api_key": "Chave de API",
            "api_base_url": "URL base da API",
            "organization_id": "Organization ID",
            "project_id": "Project ID",
        }
        widgets = {
            "api_key": forms.PasswordInput(
                render_value=False,
                attrs={"autocomplete": "new-password"},
            ),
        }


class GoogleDriveIntegrationPortalForm(IntegrationPortalFormMixin, forms.ModelForm):
    secret_fields = ("credentials_json",)

    class Meta:
        model = GoogleDriveIntegration
        fields = [
            "nome",
            "status",
            "service_account_email",
            "credentials_json",
        ]
        labels = {
            "nome": "Nome",
            "status": "Status",
            "service_account_email": "E-mail da service account",
            "credentials_json": "Credenciais JSON",
        }
        widgets = {
            "credentials_json": forms.Textarea(
                attrs={
                    "rows": 10,
                    "spellcheck": "false",
                    "autocomplete": "off",
                }
            ),
        }


class LocalStorageIntegrationPortalForm(IntegrationPortalFormMixin, forms.ModelForm):
    class Meta:
        model = LocalStorageIntegration
        fields = [
            "nome",
            "status",
            "base_path",
            "recursive_scan",
        ]
        labels = {
            "nome": "Nome",
            "status": "Status",
            "base_path": "Caminho local autorizado",
            "recursive_scan": "Ler subpastas automaticamente",
        }
        help_texts = {
            "base_path": (
                "Use o caminho Windows (ex: C:\\HubAgentes\\contratos) "
                "ou diretamente o caminho do servidor (ex: /app/entradas/contratos)."
            ),
        }


class GoogleDriveFolderSourcePortalForm(IntegrationPortalFormMixin, forms.ModelForm):
    class Meta:
        model = GoogleDriveFolderSource
        fields = [
            "nome",
            "status",
            "google_drive_integration",
            "folder_url",
        ]
        labels = {
            "nome": "Nome",
            "status": "Status",
            "google_drive_integration": "Integracao Google Drive",
            "folder_url": "URL da pasta",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["google_drive_integration"].queryset = (
            GoogleDriveIntegration.objects.filter(status=IntegrationStatus.ATIVA)
            .order_by("nome")
        )


class LocalStorageFontePortalForm(LocalStorageIntegrationPortalForm):
    pass
