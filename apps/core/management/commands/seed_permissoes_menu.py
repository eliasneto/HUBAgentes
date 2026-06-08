"""Popula as permissões de menu padrão por grupo."""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand

from apps.core.models import PermissaoMenu

PAGINAS = [
    # (chave, label, descricao, ordem)
    ("painel",              "Painel inicial",           "Dashboard com resumo do sistema",         1),
    ("agentes",             "Agentes",                  "Lista de agentes disponíveis para uso",   2),
    ("processamentos",      "Processamentos",           "Histórico de processamentos do usuário",  3),
    ("gerenciar_agentes",   "Gerenciar agentes",        "Criar e editar agentes de IA",            4),
    ("fontes_documentos",   "Fontes de documentos",     "Gerenciar pastas e fontes de entrada",    5),
    ("integracoes",         "Integrações",              "Configurar integrações (IA, Drive, etc)", 6),
    ("auditoria",           "Histórico e auditoria",    "Log de todas as ações do sistema",        7),
    ("usuarios_acessos",    "Usuários e acessos",       "Gerenciar usuários do sistema",           8),
    ("configuracao_custos", "Configuração de Custos",   "Precificação e configuração financeira",  9),
    ("tela_login",          "Tela de Login",            "Personalizar tela de login",              10),
    ("configuracao_geral",  "Configurações Gerais",     "Configurações gerais do sistema",         11),
]

GRUPOS = {
    "operador":       ["painel", "agentes", "processamentos", "fontes_documentos"],
    "analista":       ["painel", "agentes", "processamentos", "gerenciar_agentes",
                       "fontes_documentos", "integracoes", "auditoria", "configuracao_custos"],
    "administrador":  [p[0] for p in PAGINAS],  # tudo
}


class Command(BaseCommand):
    help = "Popula permissoes de menu padrao por grupo"

    def handle(self, *args, **options):
        # Cria/atualiza páginas
        for chave, label, descricao, ordem in PAGINAS:
            obj, criado = PermissaoMenu.objects.update_or_create(
                chave=chave,
                defaults={"label": label, "descricao": descricao, "ordem": ordem},
            )
            self.stdout.write(f"  {'criada' if criado else 'atualizada'}: {label}")

        # Associa grupos
        for nome_grupo, chaves in GRUPOS.items():
            grupo, _ = Group.objects.get_or_create(name=nome_grupo)
            paginas = PermissaoMenu.objects.filter(chave__in=chaves)
            grupo.permissoes_menu.set(paginas)
            self.stdout.write(f"Grupo '{nome_grupo}': {paginas.count()} paginas configuradas")

        self.stdout.write(self.style.SUCCESS("Permissoes de menu configuradas com sucesso."))
