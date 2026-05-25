from django.db import models

from apps.core.models import TimestampedModel


class EventoAuditoria(TimestampedModel):
    modulo = models.CharField(max_length=40)
    acao = models.CharField(max_length=60)
    actor = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventos_auditoria",
    )
    processamento = models.ForeignKey(
        "processamentos.Processamento",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="eventos_auditoria",
    )
    objeto_tipo = models.CharField(max_length=80)
    objeto_id = models.CharField(max_length=64)
    descricao = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Evento de auditoria"
        verbose_name_plural = "Eventos de auditoria"
        indexes = [
            models.Index(fields=["modulo"]),
            models.Index(fields=["actor"]),
            models.Index(fields=["processamento"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.modulo} - {self.acao}"
