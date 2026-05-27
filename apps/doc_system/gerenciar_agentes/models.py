from django.db import models


class GerenciarAgentesBaseModel(models.Model):
    """
    Modelo base reservado para futuras estruturas da area Gerenciar Agentes.
    """

    class Meta:
        abstract = True
