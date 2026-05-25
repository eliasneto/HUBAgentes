from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.usuarios.models import UserProfile


class UsuarioPortalForm(forms.Form):
    username = forms.CharField(label="Usuario", max_length=150)
    first_name = forms.CharField(label="Nome", max_length=150, required=False)
    last_name = forms.CharField(label="Sobrenome", max_length=150, required=False)
    email = forms.EmailField(label="E-mail", required=False)
    papel_principal = forms.ChoiceField(
        label="Papel principal",
        choices=[("", "---------"), *UserProfile.PapelPrincipal.choices],
        required=False,
    )
    groups = forms.ModelMultipleChoiceField(
        label="Grupos",
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    is_active = forms.BooleanField(label="Usuario ativo", required=False, initial=True)
    is_staff = forms.BooleanField(label="Acesso tecnico/staff", required=False)
    is_superuser = forms.BooleanField(label="Administrador total", required=False)
    password1 = forms.CharField(
        label="Senha",
        required=False,
        widget=forms.PasswordInput(render_value=False),
    )
    password2 = forms.CharField(
        label="Confirmar senha",
        required=False,
        widget=forms.PasswordInput(render_value=False),
    )

    def __init__(self, *args, **kwargs):
        self.instance = kwargs.pop("instance", None)
        self.actor = kwargs.pop("actor", None)
        super().__init__(*args, **kwargs)
        self.fields["groups"].queryset = Group.objects.order_by("name")
        if self.instance is None:
            self.fields["password1"].required = True
            self.fields["password2"].required = True
            return

        profile = getattr(self.instance, "profile", None)
        self.initial.update(
            {
                "username": self.instance.username,
                "first_name": self.instance.first_name,
                "last_name": self.instance.last_name,
                "email": self.instance.email,
                "papel_principal": (
                    profile.papel_principal
                    if profile and profile.papel_principal
                    else ""
                ),
                "groups": self.instance.groups.all(),
                "is_active": self.instance.is_active,
                "is_staff": self.instance.is_staff,
                "is_superuser": self.instance.is_superuser,
            }
        )
        self.fields["password1"].help_text = "Preencha somente se quiser trocar a senha."

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        User = get_user_model()
        queryset = User.objects.filter(username__iexact=username)
        if self.instance is not None:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise forms.ValidationError("Ja existe um usuario com este login.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1") or ""
        password2 = cleaned_data.get("password2") or ""

        if password1 or password2:
            if password1 != password2:
                self.add_error("password2", "As senhas nao conferem.")
            else:
                try:
                    validate_password(password1, user=self.instance)
                except ValidationError as exc:
                    self.add_error("password1", exc)

        if cleaned_data.get("is_superuser"):
            cleaned_data["is_staff"] = True

        if self.instance is not None and self.actor == self.instance:
            if not cleaned_data.get("is_active"):
                self.add_error("is_active", "Voce nao pode desativar seu proprio usuario.")
            if not cleaned_data.get("is_superuser") and self.instance.is_superuser:
                self.add_error(
                    "is_superuser",
                    "Voce nao pode remover seu proprio acesso de administrador total.",
                )

        return cleaned_data

    def save(self):
        if not self.is_valid():
            raise ValueError("Use save() apenas com o formulario valido.")

        User = get_user_model()
        user = self.instance or User()
        user.username = self.cleaned_data["username"]
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
        user.is_active = self.cleaned_data["is_active"]
        user.is_staff = self.cleaned_data["is_staff"]
        user.is_superuser = self.cleaned_data["is_superuser"]
        password = self.cleaned_data.get("password1")
        if password:
            user.set_password(password)
        user.save()
        user.groups.set(self.cleaned_data["groups"])

        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.papel_principal = self.cleaned_data.get("papel_principal") or ""
        profile.save()
        return user
