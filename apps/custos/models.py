from django.conf import settings
from django.db import models

from apps.core.models import TimestampedModel


class PrecificacaoModelo(TimestampedModel):
    nome_modelo = models.CharField(max_length=120, unique=True)
    preco_input_por_milhao = models.DecimalField(max_digits=12, decimal_places=6)
    preco_output_por_milhao = models.DecimalField(max_digits=12, decimal_places=6)
    ativo = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Precificacao de Modelo"
        verbose_name_plural = "Precificacoes de Modelos"
        ordering = ["nome_modelo"]

    def __str__(self):
        return self.nome_modelo


class ConfiguracaoFinanceira(TimestampedModel):
    cotacao_dolar = models.DecimalField(max_digits=10, decimal_places=4)
    atualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Configuracao Financeira"
        verbose_name_plural = "Configuracoes Financeiras"

    def __str__(self):
        return f"Cotacao dolar: R$ {self.cotacao_dolar}"
