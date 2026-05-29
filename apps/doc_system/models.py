from django.db import models

# B1: Este modulo e seus subapps (agentes, processamentos, integracoes,
# gerenciar_agentes, fontes_documentos, usuarios_acessos, painel_inicial)
# estao RESERVADOS para implementacao futura — nenhuma tabela real existe aqui.
# Nao adicione logica de negocio ate que o escopo esteja definido.


class DocSystemBaseModel(models.Model):
    """
    Modelo base reservado para futuros registros do modulo Doc System.
    """

    class Meta:
        abstract = True
