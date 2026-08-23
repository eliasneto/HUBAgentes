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
    # Leitura recursiva de subpastas (AgenteConfiguracaoOperacional.
    # include_subfolders): limite de PDFs novos processados por execucao
    # para nao ultrapassar o timeout do servidor em pastas com muitos
    # documentos. Quando a arvore tem mais PDFs pendentes que o limite, o
    # front-end dispara automaticamente a proxima execucao (lote seguinte)
    # ate esgotar os arquivos.
    max_pdfs_lote_subpastas = models.PositiveSmallIntegerField(
        default=25,
        help_text=(
            "Maximo de PDFs processados por lote quando um agente le "
            "subpastas recursivamente. 0 = sem limite."
        ),
    )
    # Espaca as chamadas a IA quando um agente processa varios documentos em
    # sequencia (modo Individual), para reduzir a chance de estourar o
    # limite de requisicoes por minuto (RPM) do provedor em lotes grandes
    # (ex.: cliente que as vezes envia ate 50 documentos de uma vez). 0 =
    # sem espera entre documentos (comportamento anterior). So se aplica
    # entre chamadas de IA de documentos diferentes, nunca dentro de uma
    # unica chamada.
    intervalo_entre_documentos_ia_segundos = models.PositiveSmallIntegerField(
        default=2,
        help_text=(
            "Segundos de espera entre o processamento de um documento e o "
            "proximo, quando um agente processa varios documentos em "
            "sequencia. Reduz a chance de estourar o limite de requisicoes "
            "por minuto do provedor de IA em lotes grandes. 0 = sem espera."
        ),
    )
    mascote_ativo = models.BooleanField(
        default=True,
        help_text="Quando ativo, o assistente Biel aparece flutuando no portal para todos os usuarios.",
    )
    # Rotina automatica de agentes (AgenteConfiguracaoOperacional.
    # execucao_automatica_ativa): interruptor e intervalo sao globais —
    # cada agente so decide SE participa, o QUANDO e o mesmo para todos.
    # Quando rotina_automatica_agentes_ativa=False, a rotina nao roda para
    # nenhum agente, mesmo que ele tenha a participacao ativada
    # individualmente.
    rotina_automatica_agentes_ativa = models.BooleanField(
        default=True,
        help_text=(
            "Liga ou desliga a rotina automatica de execucao de agentes em "
            "todo o sistema. Quando desligada, nenhum agente processa "
            "documentos automaticamente, mesmo que tenha a rotina ativada "
            "individualmente nas suas configuracoes."
        ),
    )
    rotina_automatica_intervalo_minutos = models.PositiveSmallIntegerField(
        default=60,
        help_text=(
            "Intervalo entre rodadas da rotina automatica, em minutos "
            "(minimo 10, maximo 1440 = 24h). Vale para todos os agentes "
            "com a rotina ativada. Se for menor que 30 minutos, cada "
            "rodada processa no maximo 6 documentos por agente, "
            "ignorando rotina_automatica_lote_tamanho."
        ),
    )
    rotina_automatica_lote_tamanho = models.PositiveSmallIntegerField(
        default=10,
        help_text=(
            "Quantos documentos pendentes cada agente participante da "
            "rotina automatica processa por rodada. Os demais ficam "
            "pendentes para a rodada seguinte. Vale para todos os agentes "
            "com a rotina ativada. Ignorado (fixo em 6) quando o "
            "intervalo entre rodadas for menor que 30 minutos."
        ),
    )
    # Editavel — agenda a PRIMEIRA rodada apos essa configuracao ser salva
    # (ex.: "20/08/2026 as 19:20"). So tem efeito ate a primeira rodada
    # rodar; a partir dai, as rodadas seguintes usam so
    # rotina_automatica_intervalo_minutos (ver executar_rotinas_
    # automaticas_agentes). Em branco = elegivel na proxima checagem do
    # worker, sem agendamento especifico.
    rotina_automatica_inicio_em = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Data e hora em que a primeira rodada apos salvar essa "
            "configuracao deve acontecer (ex.: 20/08/2026 as 19:20). "
            "Depois dessa primeira rodada, as demais seguem so o "
            "intervalo configurado acima. Deixe em branco para nao "
            "agendar um inicio especifico."
        ),
    )
    # Calculado automaticamente (nao editavel) — quando a proxima rodada da
    # rotina automatica pode rodar. Nulo = elegivel imediatamente na
    # proxima checagem do worker (ou respeita rotina_automatica_inicio_em,
    # se configurado).
    rotina_automatica_proxima_execucao_em = models.DateTimeField(null=True, blank=True)
    # Calculado automaticamente (nao editavel) — atualizado a CADA vez que o
    # comando executar_rotinas_automaticas_agentes roda (chamado pelo worker
    # a cada ~5min via docker-compose.yml), independente do interruptor
    # geral estar ligado ou de haver rodada elegivel agora. Sem isso, a tela
    # Administrador > Rotina automatica nao tinha como distinguir "worker
    # rodando mas ainda sem rodada elegivel/documento pendente" de "worker
    # parado" — as duas situacoes deixavam o historico igualmente vazio.
    # Caso real: usuario deixou a rotina rodando ~3h sem nenhum documento
    # pendente e nao tinha como confirmar que a checagem estava de fato
    # acontecendo (21/08/2026).
    rotina_automatica_ultima_verificacao_em = models.DateTimeField(null=True, blank=True)
    # IA no assistente Biel (chat de ajuda do portal): quando ligado, uma
    # pergunta que a base de conhecimento estatica (apps.doc_system.views.
    # _KNOWLEDGE_BASE) nao sabe responder (score 0 na busca por palavra-chave,
    # o caso que hoje cai em "nao encontrei isso na documentacao") e
    # respondida por um provedor de IA em vez do texto generico — com a
    # propria base de conhecimento como contexto, pra reduzir risco de
    # inventar funcionalidade que nao existe. Perguntas que ja batem com
    # algo na base continuam respondidas so por palavra-chave, sem custo de
    # IA. Se a chamada falhar por qualquer motivo (sem integracao escolhida,
    # erro do provedor, etc.), cai de volta pro "nao encontrei isso" de
    # sempre, sem expor erro tecnico ao usuario do portal.
    biel_ia_ativa = models.BooleanField(default=False)
    biel_ai_provider_integration = models.ForeignKey(
        "integracoes.AIProviderIntegration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # Em branco, usa o modelo padrao da integracao escolhida acima — mesmo
    # padrao ja usado por AgenteIA.modelo_preferencial (ver
    # apps.agentes_ia.services: "modelo = agente.modelo_preferencial or
    # integracao.default_model").
    biel_ia_modelo = models.CharField(max_length=120, blank=True)
    # Acumuladores de uso da IA do Biel — atualizados via F() (update
    # atomico direto na tabela, ver apps.doc_system.views._acumular_uso_biel)
    # a cada resposta com sucesso, pra nao perder incremento em chamadas
    # concorrentes. Custo calculado no momento de CADA chamada, com o
    # modelo realmente usado naquele momento (apps.processamentos.services.
    # agent_execution._custo_de_tokens) — nao recalculado a partir do
    # modelo atual, entao continua correto mesmo se o modelo/integracao for
    # trocado depois. Ficam None/0 (sem custo) se nao houver precificacao
    # (apps.custos.models.PrecificacaoModelo) ou cotacao do dolar
    # (ConfiguracaoFinanceira) cadastradas — os tokens continuam contando
    # normalmente mesmo sem custo calculavel. Zerados via
    # "Zerar contador" na propria tela (ver ZerarUsoBielView), pra permitir
    # medir uso por periodo (ex.: por mes) em vez de so o total desde
    # sempre.
    biel_tokens_input_total = models.PositiveBigIntegerField(default=0)
    biel_tokens_output_total = models.PositiveBigIntegerField(default=0)
    biel_custo_usd_total = models.DecimalField(max_digits=14, decimal_places=6, default=0)
    biel_custo_brl_total = models.DecimalField(max_digits=14, decimal_places=4, default=0)
    biel_uso_zerado_em = models.DateTimeField(null=True, blank=True)
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
