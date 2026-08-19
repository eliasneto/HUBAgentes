import json
import re
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
        "keywords": ["processamento", "processamentos", "acompanhar", "status", "progresso", "download", "baixar resultado", "arquivo final", "concluido", "erro processamento", "falha execucao", "concluido com atencao", "atencao amarelo", "qual documento deu erro", "qual arquivo deu erro", "qual documento falhou", "qual arquivo falhou", "documento com erro", "arquivo com erro", "tokens por documento"],
        "resposta": "**Processamentos** é onde você acompanha cada execução.\n\n📊 **Status possíveis:**\n• **Aguardando** — na fila, ainda não iniciou\n• **Em andamento** — processando agora\n• **Concluído com sucesso** — arquivo pronto para download\n• **Concluído com atenção** (amarelo) — situação normal, não é falha técnica: pasta vazia, arquivos já processados antes, ou instabilidade passageira do provedor de IA\n• **Concluído com erro** (vermelho) — falha técnica real, clique em \"Ver erro\" para ver o detalhe\n\nAbra **Ver tokens por documento** no card para ver o status e a mensagem de erro de cada arquivo do lote individualmente. O botão de download aparece automaticamente quando o arquivo está pronto.",
        "link": "/doc-system/processamentos/",
    },
    {
        "keywords": ["retentativa", "tenta de novo", "tenta novamente", "tentar de novo", "reprocessar automatico", "reprocessa sozinho", "reprocessa automaticamente", "erro sumiu", "tentou de novo sozinho", "quantas tentativas", "maximo de tentativas", "resposta invalida da ia", "json invalido", "ia nao respondeu", "rodou de novo", "de novo automaticamente", "corrigiu sozinho"],
        "resposta": "**Retentativa automática:** quando um agente processa vários arquivos (modo Individual) e um deles falha por um erro vindo da própria IA (instabilidade, timeout, resposta vazia ou em JSON inválido), o sistema tenta esse arquivo **de novo automaticamente, ao final do lote**, antes de marcar o processamento como concluído — sem você precisar fazer nada.\n\n⚠️ **Erros de configuração não são re-tentados** (chave de API inválida, modelo inexistente, documento maior que o contexto do modelo) — repetir não resolveria, é preciso corrigir a causa.\n\nO limite de tentativas por documento é configurável em **Gerenciar agentes** (campo \"Máximo de tentativas\").",
        "link": "/doc-system/processamentos/",
    },
    {
        "keywords": ["reprocessar", "reprocessar arquivo", "arquivo ja processado", "ja foi executado", "arquivo que ja foi executado", "arquivos ignorados", "pular arquivo", "nao processou de novo", "forcar reprocessamento", "reprocessar pasta"],
        "resposta": "**Arquivos já processados:** por padrão, se um arquivo de uma pasta (Google Drive ou local) já foi processado com sucesso antes por aquele agente, ele é **ignorado** nas execuções seguintes — só os novos são processados. Durante a execução, uma nota mostra \"X de Y arquivo(s) já haviam sido processados e foram ignorados\".\n\n🔁 Para forçar o reprocessamento de tudo (inclusive os já feitos), marque a caixa **\"Reprocessar arquivos já executados anteriormente\"** no modal de confirmação, antes de clicar em Executar. Essa opção só aparece para agentes com origem em pasta.",
        "link": "/doc-system/agentes/",
    },
    {
        "keywords": ["subpasta", "subpastas", "ler subpastas", "todas as subpastas", "recursivo", "recursiva", "varrer pasta", "pasta dentro de pasta", "sub-pasta", "sub-pastas", "arquivos dentro de subpastas", "lote de pdfs", "continuando lote", "proximo lote", "quantos pdfs por vez", "limite de pdfs por lote", "nao encontrou todos os arquivos", "so leu a raiz"],
        "resposta": "**Ler PDFs de todas as subpastas:** opção por agente (em Gerenciar agentes, na seção Entrada), desligada por padrão. Quando ativa, o agente passa a ler os PDFs de **todas as subpastas abaixo da pasta raiz configurada, em qualquer profundidade** — não só os arquivos soltos na raiz (comportamento padrão) e não só 1 nível de subpastas (como no modo \"Lote por sub-pastas\" sem essa opção). Vale tanto para pasta local quanto para pasta do Google Drive.\n\n📦 **Pastas com muitos PDFs são processadas em lotes automáticos**, para não travar a execução: cada \"clique\" processa até um limite configurável (padrão 25 PDFs — ajustável em Administrador > Configurações Gerais, campo \"Máximo de PDFs por lote ao ler subpastas\"). Se sobrar arquivo, o botão do card muda para **\"Continuando (lote N)...\"** e o sistema dispara o próximo lote sozinho, sem precisar clicar de novo, até esgotar a pasta. Arquivos já processados com sucesso em lotes anteriores nunca são repetidos.\n\nNo modal de confirmação de execução, uma linha **\"Subpastas: sim...\"** avisa quando essa opção está ativa para o agente.",
        "link": "/doc-system/agentes/",
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
        "resposta": "**Gerenciar agentes** é a área administrativa para criar e configurar agentes.\n\n⚙️ **Principais campos:**\n• Nome, slug e objetivo\n• Integração de IA e fonte de documentos\n• Modo de acionamento (portal, API)\n• Visibilidade (usuário ou técnico)\n• Prompt e configurações de saída\n• Máximo de tentativas por documento\n• Ler PDFs de todas as subpastas (para origem em pasta local ou Google Drive)\n• Filtro por nome de arquivo (ex.: `Edital*`, para só processar arquivos com esse nome)\n• Pré-processar PDF antes da IA (reduz custo)\n• Reduzir custo de raciocínio da IA (reduz custo)\n\nSomente administradores têm acesso.",
        "link": "/doc-system/gerenciar-agentes/",
    },
    {
        "keywords": ["pre-processar pdf", "pre processar pdf", "reduzir tokens pdf", "duplicata pdf", "paginas duplicadas", "economizar tokens pdf", "custo pdf", "reduzir custo ia pdf"],
        "resposta": "**Pré-processar PDF antes da IA:** opção por agente (em Gerenciar agentes) que remove páginas idênticas ou quase-idênticas de um PDF **antes** de enviá-lo à IA — sem usar IA nessa etapa, é 100% determinístico. Reduz o número de tokens cobrados sem perder informação relevante.\n\n📉 Ideal para editais e documentos com muita repetição de cabeçalho/rodapé ou páginas duplicadas. Vem desligada por padrão; se algo der errado no pré-processamento, o sistema envia o documento original sem interromper a análise.\n\nSó tem efeito no modo de execução **Individual**.",
        "link": "/doc-system/gerenciar-agentes/",
    },
    {
        "keywords": ["reduzir raciocinio", "reduzir custo de raciocinio", "thinking budget", "custo de pensamento", "tokens de pensamento", "thoughts token", "reduzir custo ia raciocinio", "desligar raciocinio ia"],
        "resposta": "**Reduzir custo de raciocínio da IA:** opção por agente (em Gerenciar agentes) que pede para a IA responder direto, sem gastar tokens com um rascunho interno (\"thinking\") antes da resposta final — um custo cobrado mas que nunca aparece pro usuário.\n\n📉 Medido em produção: reduziu o total de tokens em cerca de 22-27% num checklist de análise de edital, sem deixar nenhum item sem resposta.\n\nSó tem efeito em modelos que suportam esse ajuste (hoje, Gemini). Vem desligada por padrão — como a IA passa a \"pensar menos\", vale revisar as respostas depois de ligar, principalmente em itens que exigem julgamento mais fino (ex.: habilitação em editais).",
        "link": "/doc-system/gerenciar-agentes/",
    },
    {
        "keywords": ["filtro nome arquivo", "filtro por nome", "filtrar por nome", "filtrar arquivo", "filtrar arquivos", "nome do arquivo", "padrao de nome", "arquivos que comecam com", "arquivo que comeca com", "ler arquivos que comecam", "processar arquivos que comecam", "nome comeca com", "so processar arquivos que comecam", "ignorar arquivos pelo nome", "so ler editais", "processar so editais", "edital estrela", "edital*", "allowed_filename_pattern", "arquivo errado", "documento errado", "leu o arquivo errado", "leu o documento errado", "processou arquivo errado", "ia leu arquivo errado"],
        "resposta": "**Filtro por nome de arquivo:** opção por agente (em Gerenciar agentes, na seção Entrada) que aceita um padrão estilo **glob** — por exemplo `Edital*` — para processar só os arquivos cujo NOME bater esse padrão. Os demais são descartados **antes** de serem baixados ou lidos, sem gastar nenhum token com eles.\n\n💡 Isso é diferente de pedir a mesma coisa dentro do prompt (\"leia só arquivos que começam com Edital\"): o sistema já baixa e envia o conteúdo do arquivo inteiro pra IA antes dela processar o prompt, então essa instrução vira um pedido pra IA \"ignorar\" um conteúdo que ela já recebeu — sem garantia nenhuma de obediência consistente, principalmente em lote. O filtro por nome resolve isso na raiz, antes do envio.\n\n`*` substitui qualquer sequência de caracteres, em qualquer posição, sem diferenciar mai/minúsculas. Deixe em branco para não filtrar por nome (processa todos os arquivos, comportamento padrão). Só tem efeito quando a origem é pasta local ou Google Drive — não afeta upload na execução nem arquivo local fixo.",
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
        "keywords": ["configuracao geral", "configuracoes gerais", "parametro sistema", "pasta compartilhada", "maximo de pdfs por lote", "limite de execucoes simultaneas"],
        "resposta": "**Configurações gerais** centraliza parâmetros globais do sistema.\n\n🔧 **Inclui:**\n• Gerenciamento de pastas compartilhadas\n• Limites de execuções simultâneas (global e por usuário)\n• Máximo de PDFs por lote ao ler subpastas recursivamente\n• Configurações de armazenamento\n• Parâmetros globais de operação\n\nAcesse em Administrador > Configurações Gerais.",
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


def _keyword_presente(kw_norm, texto_norm):
    """Casa a keyword por limite de palavra, nao por substring cru — sem
    isso, uma keyword curta como "oi" da falso positivo dentro de "foi",
    "dois" etc. e sequestra a resposta (ex.: qualquer pergunta com "foi"
    caia na saudacao do Biel)."""
    return re.search(r"(?<!\w)" + re.escape(kw_norm) + r"(?!\w)", texto_norm) is not None


def _biel_responder(mensagem):
    texto_norm = _normalizar(mensagem)
    melhor, melhor_score = None, 0
    for item in _KNOWLEDGE_BASE:
        score = sum(
            len(kw.split())
            for kw in item["keywords"]
            if _keyword_presente(_normalizar(kw), texto_norm)
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
