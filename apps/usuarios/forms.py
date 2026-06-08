from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


PERFIS = [
    ("", "— Sem perfil definido —"),
    ("operador",      "Operador — acesso básico (agentes, processamentos, fontes)"),
    ("analista",      "Analista — acesso operacional + auditoria e integrações"),
    ("administrador", "Administrador — acesso total ao sistema"),
]


class UsuarioPortalForm(forms.Form):
    username    = forms.CharField(label="Usuário", max_length=150)
    first_name  = forms.CharField(label="Nome", max_length=150, required=False)
    last_name   = forms.CharField(label="Sobrenome", max_length=150, required=False)
    email       = forms.EmailField(label="E-mail", required=False)

    perfil = forms.ChoiceField(
        label="Perfil de acesso",
        choices=PERFIS,
        required=False,
        help_text="Define quais páginas do menu este usuário pode acessar por padrão.",
    )
    is_active    = forms.BooleanField(label="Usuário ativo", required=False, initial=True)
    is_superuser = forms.BooleanField(
        label="Administrador total",
        required=False,
        help_text="Acesso irrestrito a todas as páginas e funcionalidades.",
    )

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
        self.actor    = kwargs.pop("actor", None)
        super().__init__(*args, **kwargs)

        if self.instance is None:
            self.fields["password1"].required = True
            self.fields["password2"].required = True
            self.initial["is_active"] = True
            return

        # Detecta perfil atual pelo grupo principal
        grupos = list(self.instance.groups.values_list("name", flat=True))
        perfil_atual = ""
        for p in ("administrador", "analista", "operador"):
            if p in grupos:
                perfil_atual = p
                break

        self.initial.update({
            "username":    self.instance.username,
            "first_name":  self.instance.first_name,
            "last_name":   self.instance.last_name,
            "email":       self.instance.email,
            "perfil":      perfil_atual,
            "is_active":   self.instance.is_active,
            "is_superuser": self.instance.is_superuser,
        })
        self.fields["password1"].help_text = "Preencha somente se quiser trocar a senha."

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        User = get_user_model()
        qs = User.objects.filter(username__iexact=username)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("Já existe um usuário com este login.")
        return username

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1") or ""
        p2 = cleaned.get("password2") or ""

        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "As senhas não conferem.")
            else:
                try:
                    validate_password(p1, user=self.instance)
                except ValidationError as exc:
                    self.add_error("password1", exc)

        if self.instance and self.actor == self.instance:
            if not cleaned.get("is_active"):
                self.add_error("is_active", "Você não pode desativar seu próprio usuário.")
            if not cleaned.get("is_superuser") and self.instance.is_superuser:
                self.add_error("is_superuser", "Você não pode remover seu próprio acesso de administrador total.")

        return cleaned

    def save(self):
        if not self.is_valid():
            raise ValueError("Use save() apenas com formulário válido.")

        User = get_user_model()
        user = self.instance or User()
        user.username    = self.cleaned_data["username"]
        user.first_name  = self.cleaned_data["first_name"]
        user.last_name   = self.cleaned_data["last_name"]
        user.email       = self.cleaned_data["email"]
        user.is_active   = self.cleaned_data["is_active"]
        user.is_superuser = self.cleaned_data["is_superuser"]
        user.is_staff    = self.cleaned_data["is_superuser"]  # staff segue superuser

        password = self.cleaned_data.get("password1")
        if password:
            user.set_password(password)
        user.save()

        # Atribui o grupo correspondente ao perfil
        perfil = self.cleaned_data.get("perfil") or ""
        if perfil:
            grupo, _ = Group.objects.get_or_create(name=perfil)
            user.groups.set([grupo])
        else:
            user.groups.clear()

        return user
