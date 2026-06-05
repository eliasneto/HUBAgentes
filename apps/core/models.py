from django.conf import settings
from django.db import models
from django.utils import timezone


class TelaLoginOpcao(models.TextChoices):
    PRINCIPAL = "principal", "Tela Principal (robô animado)"
    V2 = "v2", "Tela 2 (robô + painel lateral)"
    V3 = "v3", "Tela 3 (robô neon + paleta do sistema)"


class VisibilidadeDashboard(models.TextChoices):
    ADMINISTRADOR = "administrador", "Apenas Administrador"
    ANALISTA      = "analista",      "Administrador e Analista"
    OPERACIONAL   = "operacional",   "Todos (Administrador, Analista e Operacional)"


class ConfiguracaoGeral(models.Model):
    visibilidade_dashboard = models.CharField(
        max_length=20,
        choices=VisibilidadeDashboard.choices,
        default=VisibilidadeDashboard.ADMINISTRADOR,
    )
    limpeza_automatica_ativa = models.BooleanField(
        default=False,
        help_text="Quando ativo, a limpeza roda no dia configurado de cada mes.",
    )
    dia_execucao_limpeza = models.PositiveSmallIntegerField(
        default=30,
        help_text="Dia do mes em que a limpeza e executada (ex: 30 = todo dia 30 de cada mes).",
    )
    dias_retencao_arquivos = models.PositiveIntegerField(
        default=30,
        help_text="Arquivos com mais de N dias serao deletados na execucao.",
    )
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuracao Geral"

    def __str__(self):
        return f"Dashboard visivel para: {self.visibilidade_dashboard}"

    @classmethod
    def obter(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class ConfiguracaoTelaLogin(models.Model):
    tela_ativa = models.CharField(
        max_length=20,
        choices=TelaLoginOpcao.choices,
        default=TelaLoginOpcao.PRINCIPAL,
    )
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuracao de Tela de Login"

    def __str__(self):
        return f"Tela ativa: {self.tela_ativa}"

    @classmethod
    def obter(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UserStampedModel(TimestampedModel):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_updated",
    )

    class Meta:
        abstract = True


class SoftDeleteManager(models.Manager):
    """Retorna apenas registros nao deletados (deleted_at is null)."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class SoftDeleteModel(models.Model):
    """
    Mixin de soft delete. Use .delete() para marcar como deletado.
    Use .hard_delete() para remover fisicamente.
    Use all_objects.all() para incluir registros deletados nas queries.
    """

    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    def delete(self, using=None, keep_parents=False):
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])

    def hard_delete(self, using=None, keep_parents=False):
        super().delete(using=using, keep_parents=keep_parents)

    def restore(self):
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])

    @property
    def is_deleted(self):
        return self.deleted_at is not None

    class Meta:
        abstract = True
