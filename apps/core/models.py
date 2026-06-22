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
    # V142-1: limite global de execucoes simultaneas (em fila + em processamento).
    max_execucoes_simultaneas = models.PositiveSmallIntegerField(
        default=5,
        help_text="Maximo de execucoes simultaneas no sistema inteiro. 0 = sem limite.",
    )
    # V142-2: limite de execucoes simultaneas por usuario.
    max_execucoes_por_usuario = models.PositiveSmallIntegerField(
        default=2,
        help_text="Maximo de execucoes simultaneas por usuario. 0 = sem limite.",
    )
    mascote_ativo = models.BooleanField(
        default=True,
        help_text="Quando ativo, o assistente Biel aparece flutuando no portal para todos os usuarios.",
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


class PermissaoMenu(models.Model):
    """Página/rota do sistema que pode ser liberada por grupo ou por usuário."""

    chave = models.CharField(max_length=60, unique=True)
    label = models.CharField(max_length=100)
    descricao = models.CharField(max_length=200, blank=True)
    ordem = models.PositiveSmallIntegerField(default=0)

    # Grupos que têm essa página por padrão
    grupos = models.ManyToManyField(
        "auth.Group",
        blank=True,
        related_name="permissoes_menu",
    )
    # Usuários com acesso extra (além do grupo)
    usuarios_extras = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="permissoes_menu_extras",
    )

    class Meta:
        verbose_name = "Permissao de menu"
        verbose_name_plural = "Permissoes de menu"
        ordering = ["ordem", "label"]

    def __str__(self):
        return self.label


def usuario_pode_acessar_pagina(user, chave: str) -> bool:
    """Verifica se o usuário tem acesso à página identificada por chave."""
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    from django.db.models import Q
    return PermissaoMenu.objects.filter(chave=chave).filter(
        Q(grupos__in=user.groups.all()) | Q(usuarios_extras=user)
    ).exists()


def paginas_do_usuario(user) -> set:
    """Retorna o conjunto de chaves de páginas acessíveis pelo usuário."""
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return set(PermissaoMenu.objects.values_list("chave", flat=True))
    from django.db.models import Q
    return set(
        PermissaoMenu.objects.filter(
            Q(grupos__in=user.groups.all()) | Q(usuarios_extras=user)
        ).values_list("chave", flat=True)
    )


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
