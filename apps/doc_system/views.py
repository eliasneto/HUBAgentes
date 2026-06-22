import json
import unicodedata

from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import TemplateView


class DocSystemIndexView(TemplateView):
    template_name = "portal_operacional/menu_inicial.html"


def _normalizar(texto):
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


_KNOWLEDGE_BASE = [
    {
        "keywords": ["oi", "ola", "bom dia", "boa tarde", "boa noite", "tudo bem", "tudo bom", "oi biel", "ola biel"],
        "resposta": "Oi! Sou o Biel 🤖, assistente do HUB Agentes. Posso te ajudar com dúvidas sobre agentes, processamentos, integrações e outras áreas do portal. O que você precisa?",
        "link": None,
    },
    {
        "keywords": ["agente", "agentes", "executar", "execucao", "como executar", "rodar agente", "iniciar agente", "card agente", "anexar arquivo", "enviar arquivo"],
        "resposta": "**Agentes** são os fluxos de leitura disponíveis para você.\n\n📋 **Para executar:**\n1. Vá em Operação > Agentes\n2. Localize o agente desejado\n3. Anexe um arquivo se necessário (PDF, TXT, CSV, XLSX — até 50 MB)\n4. Clique em **Executar**\n5. Confirme no modal\n\nO progresso aparece no próprio card com barra e percentual em tempo real.",
        "link": "/doc-system/agentes/",
    },
    {
        "keywords": ["processamento", "processamentos", "acompanhar", "status", "progresso", "download", "baixar resultado", "arquivo final", "concluido", "erro processamento", "falha execucao"],
        "resposta": "**Processamentos** é onde você acompanha cada execução.\n\n📊 **Status possíveis:**\n• **Aguardando** — na fila, ainda não iniciou\n• **Em andamento** — processando agora\n• **Concluído** — arquivo pronto para download\n• **Erro** — clique em \"Ver erro\" para ver o detalhe\n\nO botão de download aparece automaticamente quando o arquivo está pronto.",
        "link": "/doc-system/processamentos/",
    },
    {
        "keywords": ["integracao", "integracoes", "conectar", "api", "openai", "gemini", "anthropic", "modelo ia", "chave api", "validar integracao", "adicionar integracao", "nova integracao"],
        "resposta": "**Integrações** conectam o portal a serviços externos de IA e armazenamento.\n\n🔗 **Para adicionar:**\n1. Vá em Administrador > Integrações\n2. Clique em Nova integração\n3. Escolha o tipo (IA ou armazenamento)\n4. Informe a chave API\n5. Use **Validar** para testar antes de salvar\n\nSomente administradores podem gerenciar integrações.",
        "link": "/doc-system/integracoes/",
    },
    {
        "keywords": ["fonte", "fontes documento", "origem documento", "pasta local", "google drive", "gdrive", "storage", "fonte de documento"],
        "resposta": "**Fontes de documentos** definem de onde os agentes buscam arquivos.\n\n📁 **Tipos disponíveis:**\n• **Local** — pasta configurada no servidor\n• **Google Drive** — pasta de um Drive conectado\n\nCada fonte é vinculada a uma integração de armazenamento já cadastrada.",
        "link": "/doc-system/fontes-documentos/",
    },
    {
        "keywords": ["gerenciar agente", "criar agente", "novo agente", "configurar agente", "editar agente", "prompt agente", "slug agente", "modo acionamento", "visibilidade agente"],
        "resposta": "**Gerenciar agentes** é a área administrativa para criar e configurar agentes.\n\n⚙️ **Principais campos:**\n• Nome, slug e objetivo\n• Integração de IA e fonte de documentos\n• Modo de acionamento (portal, API)\n• Visibilidade (usuário ou técnico)\n• Prompt e configurações de saída\n\nSomente administradores têm acesso.",
        "link": "/doc-system/gerenciar-agentes/",
    },
    {
        "keywords": ["painel", "dashboard", "tela inicial", "metricas", "indicadores", "resumo geral", "estatisticas"],
        "resposta": "**Painel inicial** é a primeira tela após o login.\n\n📈 **Exibe em tempo real:**\n• Total de processamentos e seus status\n• Agentes disponíveis\n• Atividade recente do portal\n\nUse o painel como ponto de partida para navegar pelo sistema.",
        "link": "/doc-system/painel-inicial/",
    },
    {
        "keywords": ["usuario", "usuarios", "acesso", "acessos", "permissao", "criar usuario", "novo usuario", "senha usuario", "perfil usuario"],
        "resposta": "**Usuários e acessos** gerencia quem pode entrar e o que cada um pode fazer.\n\n👥 **Para criar um usuário:**\n1. Vá em Administrador > Usuários e acessos\n2. Clique em Novo usuário\n3. Informe nome, e-mail e senha\n4. Defina o perfil de acesso\n\nSomente administradores podem criar e editar usuários.",
        "link": "/doc-system/usuarios-e-acessos/",
    },
    {
        "keywords": ["custo", "custos", "limite custo", "orcamento", "gasto ia", "tokens", "credito", "configuracao custo"],
        "resposta": "**Configuração de custos** define limites e controles de uso de IA.\n\n💰 **O que você pode configurar:**\n• Limite de tokens por execução\n• Alertas de custo por agente\n• Relatório de gastos por período\n\nAcesse em Administrador > Configuração de Custos.",
        "link": "/doc-system/configuracao-custos/",
    },
    {
        "keywords": ["configuracao geral", "configuracoes gerais", "parametro sistema", "pasta compartilhada"],
        "resposta": "**Configurações gerais** centraliza parâmetros globais do sistema.\n\n🔧 **Inclui:**\n• Gerenciamento de pastas compartilhadas\n• Configurações de armazenamento\n• Parâmetros globais de operação\n\nAcesse em Administrador > Configurações Gerais.",
        "link": "/doc-system/configuracoes-gerais/",
    },
    {
        "keywords": ["google drive api", "oauth", "service account", "credencial google", "conectar drive", "configurar drive"],
        "resposta": "**Guia Google Drive API** mostra como conectar o portal ao Google Drive.\n\n🗂️ **Etapas principais:**\n1. Criar projeto no Google Cloud Console\n2. Ativar a Google Drive API\n3. Criar credenciais (Service Account ou OAuth)\n4. Baixar o JSON de credenciais\n5. Cadastrar a integração no portal\n\nVeja o guia completo para o passo a passo detalhado.",
        "link": "/doc-system/guia-google-drive-api/",
    },
    {
        "keywords": ["otimizacao custo", "otimizar ia", "economizar tokens", "reducao custo ia", "prompt eficiente", "custo baixo"],
        "resposta": "**Otimização de custos de IA** traz boas práticas para reduzir consumo de tokens.\n\n💡 **Estratégias principais:**\n• Escrever prompts objetivos e diretos\n• Usar modelos menores para tarefas simples\n• Evitar re-envio de contexto desnecessário\n• Monitorar o uso por agente regularmente",
        "link": "/doc-system/otimizacao-custos-ia/",
    },
    {
        "keywords": ["ajuda", "help", "suporte", "o que voce faz", "o que sabe", "topicos", "duvida", "nao sei"],
        "resposta": "Posso te ajudar com:\n\n• **Agentes** — como executar e interpretar cards\n• **Processamentos** — acompanhar status e baixar resultados\n• **Integrações** — conectar serviços de IA\n• **Fontes de documentos** — gerenciar origens de arquivos\n• **Usuários** — criar e gerenciar acessos\n• **Custos** — controlar gastos de IA\n• **Google Drive** — conectar ao Drive\n\nDigite o que você precisa!",
        "link": None,
    },
]


def _biel_responder(mensagem):
    texto_norm = _normalizar(mensagem)
    melhor, melhor_score = None, 0
    for item in _KNOWLEDGE_BASE:
        score = sum(
            len(kw.split())
            for kw in item["keywords"]
            if _normalizar(kw) in texto_norm
        )
        if score > melhor_score:
            melhor_score, melhor = score, item

    if melhor and melhor_score > 0:
        return melhor

    return {
        "resposta": "Hmm, não encontrei isso na documentação. Tente perguntar sobre: agentes, processamentos, integrações, fontes de documentos, usuários ou configurações.",
        "link": None,
    }


class BielChatView(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            mensagem = (data.get("mensagem") or "").strip()
        except (json.JSONDecodeError, AttributeError):
            mensagem = ""

        if not mensagem:
            return JsonResponse({"resposta": "Pode digitar sua pergunta!", "link": None})

        resultado = _biel_responder(mensagem)
        return JsonResponse({"resposta": resultado["resposta"], "link": resultado["link"]})


@method_decorator(staff_member_required, name="dispatch")
class BielToggleView(View):
    def post(self, request):
        from apps.core.models import ConfiguracaoGeral
        config = ConfiguracaoGeral.obter()
        config.mascote_ativo = not config.mascote_ativo
        config.atualizado_por = request.user
        config.save(update_fields=["mascote_ativo", "atualizado_por", "updated_at"])
        return JsonResponse({"mascote_ativo": config.mascote_ativo})
