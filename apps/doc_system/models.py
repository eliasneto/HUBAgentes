from django.db import models


class DocSystemBaseModel(models.Model):
    """
    Modelo base reservado para futuros registros do modulo Doc System.
    """

    class Meta:
        abstract = True
