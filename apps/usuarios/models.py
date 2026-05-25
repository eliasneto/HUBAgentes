from django.db import models


class UserProfile(models.Model):
    class PapelPrincipal(models.TextChoices):
        ADMINISTRADOR = "administrador", "Administrador"
        ANALISTA = "analista", "Analista"
        OPERADOR = "operador", "Operador"

    user = models.OneToOneField(
        "auth.User",
        on_delete=models.CASCADE,
        related_name="profile",
    )
    papel_principal = models.CharField(
        max_length=30,
        choices=PapelPrincipal.choices,
        blank=True,
    )
    observacoes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Perfil de usuario"
        verbose_name_plural = "Perfis de usuarios"

    def __str__(self):
        return f"Perfil de {self.user}"
