# Changelog

Todas as mudanças notáveis deste projeto serão documentadas neste arquivo.  
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

---

## [1.4.0] — 2026-06-07

### Adicionado

#### Gerenciamento de Arquivos em Pasta Local
- **Upload de arquivos via interface web** — nova página "Gerenciar arquivos" acessível pelo card de cada integração de pasta local. Suporta seleção de arquivos individuais, pasta inteira (preservando estrutura de subpastas via `webkitdirectory`) e drag & drop.
- **Progresso de upload em tempo real** — barra de progresso, lista de resultados por arquivo e mensagens de sucesso/erro individuais.
- **Exclusão de arquivos** — botão de exclusão por arquivo com confirmação, direto na listagem da página de gerenciamento.
- **Detecção automática de extensão** no modo "Definida pelo Prompt" — sistema detecta se o conteúdo é HTML (→ `.html`), JSON (→ `.json`) ou texto puro (→ `.txt`) e salva com a extensão correta.
- **Volume `entradas` gravável** — removido o modo somente-leitura (`:ro`) do volume Docker para permitir upload via web.

#### Sistema de Pastas Locais — Pastas Pessoais e Compartilhadas
- **Pasta pessoal automática** — ao criar um usuário via portal, o sistema cria automaticamente uma pasta `/app/entradas/{username}/` e uma integração "Pasta de {nome}" vinculada a esse usuário como proprietário.
- **Pastas compartilhadas** — nova seção em Configurações Gerais para criar pastas acessíveis a todos os usuários. Nome da pasta no servidor é gerado automaticamente a partir do nome da integração (slug).
- **Controle de usuários por pasta compartilhada** — botão "Gerenciar usuários" em cada pasta compartilhada permite adicionar ou remover usuários com duas permissões: **Leitura** (só executa agentes) e **Leitura e escrita** (pode fazer upload e excluir arquivos). Permissão alterável a qualquer momento com um clique.
- **Filtro de acesso no formulário de execução** — o dropdown de pasta local na execução exibe apenas pastas às quais o usuário tem acesso (pessoal ou compartilhadas onde foi adicionado).
- **Regras de acesso ao botão "Gerenciar arquivos"**: pasta pessoal → só o dono; pasta compartilhada → admin ou membro com permissão de escrita.

#### Sistema Híbrido de Permissões de Menu
- **Model `PermissaoMenu`** — tabela com todas as páginas do sistema (11 rotas), vinculada a grupos (permissão padrão) e a usuários individuais (permissão extra).
- **Perfis padrão por grupo:**
  - **Operador:** Painel, Agentes, Processamentos, Fontes de documentos.
  - **Analista:** tudo do Operador + Gerenciar agentes, Integrações, Histórico e auditoria, Configuração de Custos.
  - **Administrador:** acesso completo (todas as 11 páginas).
- **Permissões extras individuais** — na edição de usuário, o administrador pode marcar páginas adicionais além do padrão do grupo, sem alterar o grupo.
- **Sidebar dinâmico** — itens do menu aparecem apenas se o usuário tiver permissão para aquela página; grupos inteiros (Operação/Administrador) desaparecem se nenhum item estiver disponível.
- **Context processor `paginas_menu`** — injetado em todos os templates, evita N+1 queries calculando as páginas acessíveis uma única vez por request.
- **Comando `seed_permissoes_menu`** — popula as páginas e vincula grupos em uma execução; idempotente (pode rodar múltiplas vezes sem duplicar dados).

#### Formulário de Usuário Reformulado
- **Seleção de perfil por cartões visuais** — substitui o dropdown "Papel principal" + checkboxes de grupos por 4 cartões clicáveis: Operador, Analista, Administrador e Sem perfil.
- **Campos simplificados** — removidos "Acesso técnico/staff" e o multi-checkbox de grupos. Mantidos: Usuário ativo e Administrador total.
- **Seção "Páginas extras"** (apenas na edição) — grade de checkboxes mostrando todas as páginas disponíveis. Páginas concedidas pelo perfil aparecem em ciano e desativadas; páginas extras individuais são marcáveis separadamente.

#### Novos Modos de Saída
- **"Definida pelo Prompt"** (`livre`) — sistema salva a resposta da IA exatamente como retornou, sem qualquer conversão. Extensão do arquivo detectada automaticamente pelo conteúdo (HTML → `.html`, JSON → `.json`, texto → `.txt`). Prompt não é modificado.
- **"Definida pela IA" aprimorado** — instrução injetada no prompt agora inclui tabela de critérios para escolha do formato (xlsx para dados tabulares, pdf para relatórios, json para integração de sistemas, etc.) e campo `justificativa` no JSON de resposta.

#### Card de Agente — Informações de Origem
- **"Origem dos documentos"** exibida no card — mostra o tipo de entrada configurado no agente (Pasta local · nome-da-pasta, Google Drive · nome-da-fonte, Upload na execução, Sem origem documental).
- **Verificação de acesso à pasta local** — se o agente usa pasta local fixa e o usuário não tem acesso a ela, o botão "Executar" é substituído por "Sem acesso" (desabilitado) e um aviso laranja é exibido no card.

#### Fontes de Documentos
- **Seção "Pastas locais" restaurada** em Fontes de documentos — exibe cards das pastas às quais o usuário tem acesso (pessoal ou compartilhadas), com botão "Gerenciar arquivos" para proprietários e membros com permissão de escrita.
- **Campo renomeado:** "Criado por" → "Proprietário" com exibição do nome completo do usuário.

### Corrigido
- **Fix de migrations conflitantes** — resolvidas múltiplas colisões de `0017_alter_*` entre ambientes local e servidor; introduzidas migrations de merge e dependências corrigidas.
- **`render` não importado em `core/views.py`** — causava `NameError` na página de gerenciamento de arquivos; import adicionado.
- **Toggle "Ler subpastas automaticamente" em `integracao_form.html`** — corrigido para usar o padrão `.toggle-line` do sistema, igual ao `fonte_documento_form.html`.
- **Prefixo `models/` no nome do modelo Gemini** — adaptador Gemini agora remove automaticamente o prefixo `models/` se o usuário o digitar por engano no campo Modelo padrão.
- **Worker parado causava processamentos travados** — ao reiniciar o worker, processamentos em estado `em_processamento` são reconciliados automaticamente para `concluido_erro`.
- **`compartilhada=True` em pastas pessoais** — pastas criadas manualmente antes do sistema automático eram marcadas como compartilhadas indevidamente; corrigidas via script e regra de criação ajustada.
- **`created_by` incorreto em pastas pessoais** — ao criar usuário via portal, a pasta era atribuída ao admin logado em vez do novo usuário; corrigido para `created_by=usuario`.
- **Acesso indevido do administrador a pastas de outros usuários** — regra de acesso ajustada: pasta pessoal é exclusiva do dono, mesmo para administradores; administradores gerenciam apenas pastas compartilhadas.
- **403 em Histórico e auditoria para usuário Analista** — `AuditoriaView` e `ConfiguracaoCustosView` atualizadas para usar `AnalistaOuAdminRequiredMixin`.
- **`TemplateSyntaxError` no sidebar** — `{% with var=expr %}` não aceita expressões booleanas em Django templates; substituído por `{% if %}` direto.

### Alterado
- **"Pasta local" movida de Fontes de documentos para Integrações** — criação de nova pasta local agora é feita exclusivamente em Integrações ou automaticamente ao criar usuário.
- **Formulário de criação de pasta local simplificado** — campo "Caminho local autorizado" substituído por "Nome da pasta compartilhada"; caminho gerado automaticamente como `/app/entradas/{slug}`.
- **"Fontes de documentos" movida para a aba Operação** no sidebar (era Administrador).
- **Nomenclatura dos modos de saída:** "Livre (saída direta da IA)" → "Definida pelo Prompt"; "Definido pela IA" → "Definida pela IA" (feminino, consistente com "saída").

---

## [1.3.0] — 2026-06-04

### Adicionado

#### Painel Inicial — Dashboards
- **4 dashboards no painel inicial:** Processamentos por agente, Tokens por integração, Custo (R$) por integração e Documentos processados por agente — barras proporcionais com cores distintas por categoria.
- **Controle de visibilidade do dashboard** em Configurações Gerais: administrador, analista ou todos os perfis.

#### Limpeza Automática de Arquivos
- **Limpeza mensal automática de arquivos de saída:** configurável por dia do mês (padrão: dia 30). A cada execução deleta arquivos gerados há mais de 30 dias, mantendo os registros dos processamentos.
- **Toggle liga/desliga** na tela de Configurações Gerais. Próxima data de execução exibida em tempo real.
- **Configuração avançada** (dia de execução, dias de retenção) exclusiva do Django Admin.
- **Comando `limpar_arquivos_saida`** com suporte a `--dry-run`, `--force` e `--check-day` para testes e execução manual.

#### Suporte a Múltiplos Formatos de Arquivo
- **Entrada multi-formato liberada:** além de PDF, o sistema agora aceita TXT, CSV, PNG, JPG, JPEG e XLSX como arquivos de entrada — em pastas locais e no upload na execução.
- **Detecção automática de MIME type** por extensão de arquivo.
- **Limite de 50 MB** no upload de arquivo na execução (validado no form antes de processar).

#### Integração Groq
- **Novo provedor de IA: Groq** — API compatível com OpenAI, gratuita, com modelos Llama 3 e Mixtral de alta velocidade.
- Suporte a TXT e CSV como entrada (texto puro). PDF e imagens não são suportados pelo Groq.
- Instruções JSON injetadas automaticamente no prompt quando o formato de saída exige JSON.
- Cadastro via Integrações → Nova integração → tipo Groq.

#### Configurações Gerais
- **Nova tela "Configurações Gerais"** no sidebar de Administrador com controle de visibilidade do dashboard e limpeza automática.
- **Registro no Django Admin** com campos avançados de limpeza.

#### Experiência e Interface
- **Botão de download modernizado** na tela de Processamentos: ícone SVG + texto "Baixar", borda neon, hover com glow.
- **Modal de arquivo deletado** — ao tentar baixar um arquivo removido pela limpeza automática, exibe mensagem amigável explicando que o arquivo não está mais disponível.
- **Hints dinâmicos no formulário de agente:** ao selecionar Modo de Entrada (Individual, Grupo único, Lote por pasta) e Empacotamento da Saída, uma caixa explicativa aparece descrevendo o comportamento de cada opção.
- **Remoção da opção "Arquivo local fixo"** da interface de criação de agentes (mantida no backend para compatibilidade).

#### Telas de Login Alternativas
- **Sistema de seleção de tela de login** — novo model `ConfiguracaoTelaLogin` (singleton) com tela ativa configurável pelo administrador.
- **Tela 2** — layout split com robô animado à esquerda e card de login à direita, balão de fala com efeito máquina de escrever e data do dia dinâmica.
- **Tela 3** — tema escuro profundo (quase preto), robô com paleta neon do sistema via `mix-blend-mode: color`, sem iluminação branca.
- **Preview por URL** — rota `/login-preview/<tela>/` permite visualizar qualquer tela de login sem ativar.

#### Custo por Processamento
- **App `custos`** — novo módulo com models `PrecificacaoModelo` (preço por 1M tokens de entrada/saída por modelo de IA) e `ConfiguracaoFinanceira` (cotação do dólar em reais).
- **Tela "Configuração de Custos"** — nova seção no sidebar de Administrador para cadastrar precificações por modelo e atualizar a cotação do dólar manualmente.
- **Cálculo automático de custo** — após cada processamento, o sistema calcula `custo_usd` e `custo_brl` com base nos tokens consumidos, no preço do modelo e na cotação configurada. Tokens de raciocínio (thinking) são somados aos de saída, pois a API os cobra à mesma taxa.
- **Exibição de custo na Auditoria** — chip "Custo R$ X,XXXX" adicionado na faixa de tokens do card de auditoria, exibindo o custo com 4 casas decimais.
- **Campos `custo_usd` e `custo_brl`** adicionados nos models `Processamento` e `ProcessamentoExecucaoIA`.

#### Telas de Login Alternativas
- **Sistema de seleção de tela de login** — novo model `ConfiguracaoTelaLogin` (singleton) com tela ativa configurável pelo administrador.
- **Tela "Tela de Login"** no sidebar de Administrador — cards com preview real (iframe) de cada tela e botão para ativar sem reiniciar o sistema.
- **Tela 2** — layout split com robô animado à esquerda e card de login à direita, balão de fala com efeito máquina de escrever e data do dia dinâmica.
- **Tela 3** — tema escuro profundo (quase preto), robô com paleta neon do sistema via `mix-blend-mode: color`, sem iluminação branca.
- **Preview por URL** — rota `/login-preview/<tela>/` permite visualizar qualquer tela de login sem ativar.

#### Pasta Local — Mapeamento Windows
- **Tradução automática de caminhos** — ao cadastrar uma fonte local com caminho Windows (ex: `C:\HubAgentes\contratos`), o sistema converte automaticamente para o caminho interno do container (`/app/entradas/contratos`), sem exigir que o usuário conheça a estrutura interna Docker.
- **Exibição do caminho no formato do sistema operacional** — integrações e fontes locais exibem o caminho no formato Windows (`C:\HubAgentes\...`) independentemente do servidor onde o sistema roda.
- **Volume Docker `C:\HubAgentes → /app/entradas`** — mapeamento configurado via variável `LOCAL_STORAGE_PATH` no `.env`.

#### Subpastas no Formulário de Agente
- **Carregamento automático de subpastas** — ao selecionar uma pasta local no cadastro de agente, o sistema busca as subpastas via AJAX e exibe um dropdown, eliminando a necessidade de digitar o caminho relativo manualmente.
- **Endpoint `/agentes/api/subpastas-local/<id>/`** — retorna JSON com as subpastas disponíveis da integração selecionada.

#### Interface e Documentação
- **Favicon** — ícone do robô adicionado a todas as 22 páginas do portal.
- **Sidebar mais vibrante** — cores do menu atualizadas para neon cyan, fundo mais escuro e profundo, text-shadow nas opções ativas.
- **Mensagem amigável para pasta local offline** — quando o agente não consegue acessar a pasta local configurada, a mensagem de erro informa que a máquina que hospeda a pasta pode estar desligada ou fora da rede.
- **Documentação de Configuração de Custos** — nova página em Documentação → Configuração de Custos com fórmula de cálculo, campos explicados e observações importantes.
- **Documentação de Integrações atualizada** — seção "Pasta local" reescrita com tabela de mapeamento Windows → servidor e exemplos corretos de caminho.
- **Documentação de Gerenciar Agentes atualizada** — campo "Caminho relativo padrão" agora documenta o carregamento automático de subpastas.
- **Documentação de Fontes de Documentos atualizada** — nova seção "Como funciona o mapeamento" com exemplos de correspondência entre caminhos Windows e container.

### Corrigido

#### Críticos (CHECKLIST)
- **C-1:** `SECRET_KEY` sem fallback público — o servidor agora falha ao subir se a variável não estiver definida.
- **C-2:** `FIELD_ENCRYPTION_KEY` elevada de Warning para Error — o servidor não sobe sem a chave de criptografia.
- **C-3:** Integração Groq agora exige `api_key` obrigatória para ser salva como Ativa.

#### Altos (CHECKLIST)
- **H-1:** `DocumentoEntrada.clean()` atualizado para aceitar todas as extensões suportadas além de PDF.
- **H-2:** Groq adapter removeu implementação duplicada de `_post_json_request` — usa validações da classe base.
- **H-3:** Reconciliador de processamentos removido dos selectors GET — executado apenas via worker periódico.
- **H-4:** Sufixo aleatório do código de processamento aumentado de `token_hex(2)` para `token_hex(4)` (4B possibilidades).
- **H-5:** Groq injeta instrução JSON no prompt quando `response_mime_type=application/json`.

#### Médios (CHECKLIST)
- **M-2:** `prefetch_related` adicionado ao selector de status — elimina N+1 queries em `_erro_operacional`.
- **M-3:** Contagem de membros por grupo consolidada com `annotate(Count)` em vez de N+1 queries.
- **M-4:** 4 queries COUNT no poll de status consolidadas em 1 query com `Case/When`.
- **M-5:** Limite de 50 MB no upload de arquivo.
- **M-6:** Import morto `groupby` removido de `agent_execution.py`.
- **M-7:** Cache de precificação/cotação em batch — reduz de 2N queries para 2 por lote de documentos.
- **M-8:** Download de saída restrito ao dono do processamento (admins acessam todos).
- **M-9:** `runtime_fields_schema` lido antes do condicional — valida corretamente em todos os casos.

#### Baixos (CHECKLIST)
- **L-1:** Guard adicionado para FK de integração soft-deleted em `Processamento.save()`.
- **L-2:** Checksum MD5 de arquivo local calculado em chunks de 64KB sem carregar o arquivo inteiro na memória.
- **L-3:** `DEBUG` padrão alterado para `False`.
- **L-7:** `LOCAL_FILE` preservado nas choices do form quando agente já usa esse tipo (legado).
- **L-8:** `.env.example` documentado com aviso sobre `CSRF_TRUSTED_ORIGINS` obrigatório em produção.

#### Interface e formulários
- **Botão "Excluir" fora do padrão visual** em Configuração de Custos e outras telas — padronizado para `secondary-action danger-action`.
- **Checkbox "Ler subpastas automaticamente"** no formulário de fonte local — substituído pelo toggle padrão do sistema (`.toggle-line`).
- **Campo "Ativo" no formulário de precificação** — substituído pelo toggle padrão do sistema.
- **Caminho `/app/media/entradas` desatualizado** nos guias de fontes locais — corrigido para `/app/entradas/...` em todos os exemplos e modelos de preenchimento.
- **Usuário admin padrão** no entrypoint alterado de `eliasneto` para `admin` com senha `admin`.
- **Formato de exibição da cotação** na tela de Configuração de Custos — exibe R$ com 2 casas decimais e só a data (sem horário).

#### Perfis de Acesso
- **Sistema de perfis implementado corretamente:** Operador (qualquer usuário logado) só executa agentes; Analista (grupo `analista`) cria, edita e executa agentes; Administrador (grupo `administrador` ou superusuário) tem acesso completo ao sistema.
- **Mixin `AnalistaOuAdminRequiredMixin`** criado — analistas agora conseguem acessar a tela Gerenciar Agentes e criar/editar agentes, antes restrito apenas a administradores.

#### Nomenclatura
- **"Lote por pasta" renomeado para "Lote por sub-pastas"** — nome mais claro para o usuário final, refletindo que cada sub-pasta é um processamento separado enviado à IA.

### Removido
- **Atalhos de navegação do painel inicial** (módulos Agentes, Processamentos, etc.) — substituídos pelos dashboards.
- **Opção "Arquivo local fixo"** do formulário de criação/edição de agentes.

---

## [1.2.0] — 2026-06-01

### Adicionado
- **Django system check `core.W001`** — avisa no startup do servidor quando `FIELD_ENCRYPTION_KEY` não está configurada, antes que o problema cause erro em runtime.
- **`makemigrations` automático no entrypoint** — o container roda `makemigrations` antes do `migrate` a cada inicialização, detectando e criando migrations de model que o desenvolvedor esqueceu de gerar.

### Corrigido
- **500 ao criar/editar integração sem `FIELD_ENCRYPTION_KEY`** — `EncryptedFieldMixin.get_prep_value` causava `ValueError` não tratada quando a chave não estava configurada. Agora loga erro e salva sem criptografia em vez de derrubar o servidor.
- **Migration pendente `agenteia.objetivo`** — campo `objetivo` de `AgenteIA` alterado para `blank=True` sem migration correspondente; migration `0009_alter_agenteia_objetivo` gerada.

### Documentado
- `docker compose restart` não recarrega o `.env` — usar sempre `docker compose up -d --force-recreate <serviço>` ao alterar variáveis de ambiente.

---

## [1.1.0] — 2026-06-01

### Adicionado
- **Responsividade mobile** — sidebar vira drawer lateral em telas até 1080px: botão hamburguer fixo no topo, slide com animação, backdrop escuro ao abrir, fecha ao tocar fora ou pressionar Esc, e fecha automaticamente ao navegar para outro link.
- **Timeout de sessão por inatividade** — usuário é deslogado automaticamente após 2 horas sem nenhuma ação no sistema (`SESSION_COOKIE_AGE = 7200`, `SESSION_SAVE_EVERY_REQUEST = True`).
- **Hints de combinação para modo "Uma saída por grupo"** — adicionadas as 3 combinações de empacotamento (`arquivo_unico`, `zip_se_multiplos`, `sempre_zip`) ao painel de hints contextuais do formulário de criação de agentes.

### Corrigido
- **Campos fantasmas no formulário de criação de agentes** — removidos blocos de campos (`tipo`, `categoria_operacional`, `visibilidade`, `modo_acionamento`, `objetivo`) que não existiam no formulário e causavam desalinhamento visual no grid da seção Identidade.
- **Hint de combinação com fundo branco** — caixa de hint de saída ajustada para o tema escuro do portal (fundo translúcido, borda neon, textos em ciano e muted).
- **Tokens de auditoria exibidos verticalmente** — bloco de tokens (`Total`, `Entrada`, `Processo`, `Saída`) movido da coluna lateral para uma faixa horizontal na base do card de auditoria, exibido como chips lado a lado.

### Removido
- **Container Ollama removido do Docker Compose** — serviço `ollama` e volume `ollama_data` removidos do `docker-compose.yml` pois a IA local não será utilizada nesta etapa.

---

## [1.0.0] — 2026-05-31

Primeira versão de produção do **HUB Agentes** — plataforma para configuração, execução e auditoria de agentes de IA sobre documentos.

### Adicionado

#### Portal Operacional
- Sidebar de navegação com seções Operação, Administrador e Documentação.
- Painel inicial com visão geral do sistema.
- Tela de listagem de agentes disponíveis para execução.
- Tela de listagem e acompanhamento de processamentos.
- Rodapé de sidebar com usuário logado, versão do sistema e botão de saída.

#### Agentes de IA
- Tela de criação e edição de agentes com formulário completo.
- Configuração de identidade: nome, status (ativo/inativo) e modelo preferencial.
- Configuração de prompt base com suporte a variáveis via `{{nome_variavel}}`.
- Sistema de parâmetros de prompt reutilizáveis: campos com rótulo, variável gerada automaticamente e remoção individual.
- Hints contextuais de combinação que explicam o comportamento esperado conforme as opções de execução, saída e empacotamento selecionadas.
- Somente agentes ativos e visíveis para usuário aparecem na lista operacional.

#### Modos de Execução de Documentos
- **Individual** — cada arquivo é processado separadamente pela IA.
- **Grupo único** — todos os arquivos do lote são enviados juntos em uma única chamada à IA.
- **Lote por pasta** — os arquivos são processados pasta por pasta no Google Drive; cada pasta é tratada como um lote independente.

#### Modos de Montagem da Saída
- **Uma saída por entrada** — cada arquivo de entrada gera seu próprio arquivo de saída.
- **Uma saída por grupo** — cada pasta/lote gera um arquivo de saída consolidado.
- **Uma saída final** — todos os arquivos geram um único arquivo de saída consolidado.

#### Empacotamento da Saída
- **Arquivo único** — entrega um arquivo por vez, sem compactação.
- **ZIP se múltiplos** — compacta em ZIP automaticamente quando há mais de uma saída.
- **Sempre ZIP** — entrega sempre em ZIP, mesmo com uma única saída.

#### Formatos de Saída
- **JSON** — estrutura de dados bruta retornada pela IA.
- **PDF** — documento formatado com quebras de linha e layout limpo.
- **Excel (.xlsx)** — planilha com dados tabulados.
- **CSV** — arquivo de valores separados por vírgula.
- **TXT** — texto simples.
- **Definido pela IA** — a IA informa o formato via campo `formato_saida` no JSON; o sistema valida e gera o arquivo correspondente.

#### Origens de Documento
- **Google Drive — pasta** — lê arquivos de uma pasta configurada no Google Drive.
- **Pasta local** — lê arquivos de uma pasta local autorizada no servidor.
- **Arquivo local fixo** — aponta para um arquivo fixo no armazenamento local.
- **Sem origem documental** — agente sem entrada de arquivo; permite upload avulso na execução quando habilitado.
- Campo "Permitir documento na execução" para agentes sem origem fixa.

#### Integrações
- Tela de listagem e cadastro de integrações com formulário.
- Suporte a provedores de IA externos (Gemini, OpenAI e compatíveis).
- Integração com Google Drive para leitura de pastas e arquivos.
- Integração com armazenamento local (pasta autorizada no servidor).
- Validação de conexão ao cadastrar integrações.

#### Fontes de Documento
- Tela de listagem e cadastro de fontes de documento.
- Vinculação de pastas do Google Drive como fontes reutilizáveis.

#### Processamentos
- Execução de agente com seleção de arquivos de entrada.
- Acompanhamento de status em tempo real (pendente, em execução, concluído, erro).
- Download do arquivo de saída gerado.
- Documentos de referência vinculados ao processamento.
- Campo `pasta_grupo` no documento de entrada para rastreamento de lote por pasta.
- Worker dedicado com reconciliação automática de processamentos órfãos a cada 5 minutos.

#### Auditoria
- Tela de auditoria com listagem de todos os processamentos do sistema.
- Filtros por agente, status, período e usuário.
- Contagem de tokens consumidos por processamento.

#### Documentação do Sistema
- Sistema de documentação integrado ao portal, acessível por módulo:
  - Painel inicial, Agentes, Processamentos, Integrações, Fontes de Documentos, Gerenciar Agentes, Usuários e Acessos.
- Cada tela de documentação explica o funcionamento, campos e boas práticas do módulo.

#### Usuários e Acessos
- Tela de listagem e cadastro de usuários.
- Formulário de criação e edição de usuário com campo de senha.

#### Infraestrutura
- Configuração Docker com serviços: aplicação web (`web`), banco de dados MySQL (`db`) e worker (`worker`).
- Healthchecks em `db` e `web` para garantir ordem de inicialização.
- Volumes persistentes para banco de dados, arquivos de mídia e arquivos estáticos.
- Arquivo `.env.example` com todas as variáveis de ambiente necessárias.
- Arquivo `VERSION` com controle de versão.

### Corrigido
- Alinhamento de campos no formulário de criação de agentes — removidos blocos fantasmas de campos inexistentes no formulário.
- Geração de PDF com quebras de linha e formatação correta.
- Ortografia e detalhamento na contagem de tokens exibida na auditoria.

### Removido
- Container Ollama (IA local) removido da configuração Docker — não utilizado nesta versão.
