# Changelog

Todas as mudanças notáveis deste projeto serão documentadas neste arquivo.  
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

---

## [1.5.5] — 2026-06-22

### Melhorado
- **Painel de progresso compacto no card do agente** — o painel de acompanhamento de execução foi redesenhado para caber dentro do card sem esticá-lo. Antes exibia um bloco grande com cabeçalho destacado, etapa atual, documento em processamento, aviso de travamento e botão "Baixar resultado" com texto — tudo adicionado abaixo do formulário do card. Agora é uma barra fina de `4 px` com percentual e status em `0.68 rem` em linha única, mais o `<details>` de erro recolhível quando houver falha. O botão de download foi substituído por um ícone circular (`40×40 px`, mesmo tamanho do botão "Executar", gradiente neon) exibido ao lado do botão "Executar" no próprio rodapé do card — sem nenhum texto. O ícone fica oculto e é revelado apenas quando o arquivo de saída fica disponível, via o atributo `data-agent-exec-download` adicionado ao template (`templates/portal_operacional/agentes_leitura.html`), com referência armazenada em `panel._downloadBtn` pelo JS (`static/portal_operacional/js/agente_execucao.js`). Novos seletores CSS: `.agent-exec-progress-row`, `.agent-exec-progress-track`, `.agent-exec-progress-fill`, `.agent-exec-progress-pct`, `.agent-exec-progress-status`, `.agent-run-download-btn` (`static/portal_operacional/css/menu_inicial.css`).

### Corrigido
- **Nome do agente exibido com `-` no modal de confirmação de execução** — ao clicar em **Executar** em um agente cujo nome continha hífen (`-`), o modal de confirmação exibia o caractere como a sequência literal `-` (ex.: `Aliança - Licitação` em vez de `Aliança - Licitação`). A causa era o uso do filtro `|escapejs` do Django nos atributos `data-agent-*` do `<form>` do card (`templates/portal_operacional/agentes_leitura.html`). O `escapejs` é destinado a contextos de string JavaScript e converte o hífen para `-` como medida de segurança; num atributo HTML `data-*`, a sequência fica gravada literalmente no DOM e o `dataset` a retorna como texto puro, que o `textContent` exibe sem interpretação. Corrigido removendo `|escapejs` dos cinco atributos — a auto-escape padrão do Django já protege atributos HTML (escapa `<`, `>`, `&`, `"`, `'`) sem converter o hífen.

---

## [1.5.4] — 2026-06-22

### Adicionado
- **Modal de confirmação antes de executar agente** — ao clicar em **Executar** no card de um agente, o sistema agora exibe um modal de confirmação em vez de disparar a execução imediatamente. O modal apresenta um resumo da operação: **nome do agente**, **integração IA**, **origem dos documentos** (tipo de entrada + nome da integração local, quando houver) e **formato de saída**. Dois botões encerram o fluxo: **"Confirmar execução"** (prossegue) e **"Desistir"** (fecha o modal sem nada). O modal também fecha com **Esc** ou clique fora da caixa. O campo `formato_saida` (label legível de `default_output_format`) foi adicionado ao dataclass `AgenteLeituraResumo` e ao builder `_montar_resumos_agentes` (`apps/agentes_ia/selectors.py`); os dados são expostos para o JS via `data-*` attributes no `<form>` do card (`templates/portal_operacional/agentes_leitura.html`). O modal é renderizado uma única vez no `<body>` e reutilizado por todos os cards da página.
- **Progresso de execução inline no card do agente** — após confirmar a execução, o painel de progresso aparece **diretamente no card**, eliminando a necessidade de navegar à tela de Processamentos para acompanhar o resultado. O card exibe: **barra de progresso** com percentual, **etapa atual**, **documento sendo processado** (quando disponível), **aviso de possível travamento** (após 3 min sem atividade), **painel de erro** recolhível (vermelho para erro, amarelo para atenção) e **botão de download** do arquivo de saída assim que ele fica disponível — exatamente a mesma estrutura da tela de Processamentos. O polling consulta o endpoint `/processamentos/<codigo>/status/` a cada **8 segundos** (mesmo intervalo da tela dedicada). O indicador de disponibilidade do card muda para **amarelo** durante a execução e é restaurado automaticamente ao término; o botão **Executar** fica desabilitado durante a execução e volta ao normal ao finalizar. **Ao atualizar a página ou executar novamente**, o painel é removido/substituído — não há estado persistido entre sessões. Tecnicamente: a view `AgenteExecucaoView.post()` detecta requisições AJAX (`X-Requested-With: XMLHttpRequest`) e retorna `{"codigo": ..., "status_endpoint": ...}` em vez de redirecionar; erros retornam `{"erro": ...}` com HTTP 400. O JS submete o formulário via `fetch()` e cria o painel dinamicamente no DOM, reutilizando as classes CSS já existentes (`.processing-live-panel`, `.processing-progress-track`, `.processing-progress-fill`, `.processing-error-panel`) e adicionando `.agent-exec-progress` e `.agent-exec-download-btn` (`static/portal_operacional/css/menu_inicial.css`). O fluxo de upload em chunks para agentes com upload na execução foi mantido integralmente; apenas a submissão final foi convertida de `form.submit()` para `fetch()`.

---

## [1.5.3] — 2026-06-22

### Adicionado
- **Botão "Excluir fonte" no card Google Drive da listagem de fontes de documentos** — o card de cada fonte Google Drive na tela de listagem ganhou o botão **"Excluir fonte"** (visível apenas para administradores), equivalente ao que já existia nos cards de pastas locais. Ao clicar, o sistema exibe uma confirmação com o nome da fonte antes de submeter o formulário. A exclusão é tratada pela view `ExcluirGoogleDriveFolderSourceView` já existente (`apps/core/views.py`). Alterações em `GoogleDriveFonteResumo` (novo campo `pode_excluir`) e em `listar_fontes_documentos_para_portal` (`apps/integracoes/selectors.py`) para expor a permissão ao template `fontes_documentos.html`.
- **Navegação em cascata de subpastas do Google Drive ao configurar agente** — ao criar ou editar um agente com origem Google Drive, agora é possível **navegar por todos os níveis de subpastas** (PAI → FILHO → SUB-FILHO → ...) sem sair do formulário. Ao selecionar uma fonte de documentos, um dropdown aparece automaticamente com as subpastas diretas; ao selecionar uma delas, um novo dropdown surge com suas subpastas, e assim por diante até o nível desejado. A lista é consultada em tempo real diretamente do Google Drive via dois novos endpoints (`GoogleDriveSubpastasView` e `GoogleDriveSubpastasFilhasView`, `apps/core/views.py`), sem necessidade de sincronização manual — novas pastas criadas no Drive aparecem imediatamente. O caminho completo de seleção (ex: `[{id, nome}, ...]`) é exibido como trilha de navegação (📁 FILHO › SUB-FILHO) e salvo no campo `default_gdrive_subfolder_path` (JSONField, migração `agentes_ia/0014`). Ao editar um agente, o cascade é reconstruído automaticamente para restaurar a seleção anterior. Quando configurada, o processamento usa o ID Drive da pasta mais profunda selecionada para buscar os PDFs. **Permissões:** basta compartilhar apenas a pasta raiz (PAI) com a service account — o Google Drive herda o acesso para todas as subpastas automaticamente.

---

## [1.5.2] — 2026-06-21

### Adicionado
- **Exclusão de fonte de documentos Google Drive** — a tela de edição de uma fonte Google Drive ganhou o botão **"Excluir fonte"**, equivalente ao que já existia para pastas locais. Ao clicar, o sistema exibe uma confirmação com o nome da fonte; se nenhum agente ativo estiver configurado com ela como origem padrão, o registro é removido do banco. Caso contrário, uma mensagem de erro lista os agentes que precisam ser reconfigurados antes da exclusão. Referências em agentes já excluídos (`deleted_at` preenchido) são limpas automaticamente. Implementado em `ExcluirGoogleDriveFolderSourceView` (`apps/core/views.py`), rota `fontes-de-documentos/google-drive/<id>/excluir/` (`config/urls.py`) e `fonte_documento_form.html`.
- **Preview do nome da pasta ao cadastrar fonte Google Drive** — ao colar a URL de uma pasta compartilhada no formulário de nova/editar fonte de documentos, o sistema busca automaticamente o nome real da pasta via Google Drive API (`files.get`) e exibe `📁 Nome da Pasta` abaixo do campo URL sem precisar salvar o formulário. A consulta dispara 600 ms após o usuário parar de digitar (ou imediatamente ao trocar a integração selecionada), e na tela de edição o nome já aparece ao abrir a página. Se a conta de serviço não tiver acesso à pasta ou a URL for inválida, uma mensagem de erro é exibida no lugar. O recurso não altera o fluxo de salvar nem exige novas permissões (o escopo `drive.readonly` já cobre a leitura de metadados). Implementado em `get_folder_name()` (`apps/integracoes/services/google_drive.py`), `FonteDocumentoGDriveFolderNameView` (`apps/core/views.py`), rota `fontes-de-documentos/api/nome-pasta-gdrive/` e `fonte_documento_form.html`.

### Melhorado
- **Descrições dos formatos de saída reescritas para maior clareza** — as opções "Definida pela IA" e "Definida pelo Prompt" tinham textos técnicos que não deixavam claro o que o usuário devia (ou não) escrever no prompt. Os novos textos explicam o papel do usuário em cada modo: "Definida pela IA" deixa claro que o formato não precisa ser mencionado no prompt; "Definida pelo Prompt" mostra exemplos do que escrever. Os demais formatos (Excel, CSV, etc.) também foram ajustados para reforçar que não é necessário mencionar o formato no prompt quando ele já está selecionado.
- **Painel de formatos suportados abaixo do prompt** — ao selecionar "Definida pelo Prompt", um painel aparece logo abaixo do campo de prompt listando os formatos que a IA pode gerar (Excel, CSV, PDF, TXT, JSON, HTML — em verde) e os que não são suportados hoje (PowerPoint, Word, imagens, ZIP — em vermelho), com uma nota explicando como cada conversão funciona. O painel fica oculto nos demais modos de saída, onde o formato já está fixo.

### Corrigido
- **Formato "Definida pelo Prompt" ignorava a instrução do prompt e retornava JSON** — ao selecionar o formato de saída **Definida pelo Prompt (LIVRE)**, o sistema ainda enviava `response_mime_type: application/json` ao provedor de IA, sobrescrevendo qualquer instrução de formato do prompt do usuário. A IA, ao receber esse parâmetro técnico, retornava JSON independentemente do que o prompt pedisse (ex.: pedido de texto puro resultava em `{"resumo": "..."}` em vez do texto diretamente). Corrigido em `_build_execution_params` (`apps/processamentos/services/agent_execution.py`): o parâmetro `response_mime_type` agora é omitido quando o formato é LIVRE, deixando a IA responder livremente conforme o prompt.
- **"Definida pelo Prompt" não gerava Excel mesmo quando o prompt pedia** — ao pedir explicitamente uma saída em planilha/Excel no prompt com o formato LIVRE, a IA retornava os dados em JSON tabular (lista de objetos), mas o sistema ignorava a estrutura e salvava como texto puro (`.txt` com repr Python) em vez de gerar um arquivo `.xlsx`. Corrigido em `_render_output_file` (`apps/processamentos/services/agent_execution.py`): quando o modo é LIVRE e a IA retorna uma lista de dicts ou lista de listas (dado tabular), o sistema agora encaminha para o renderer Excel e entrega um `.xlsx` real — o mesmo comportamento de quando o formato é Excel fixo. Como subproduto, dicts e objetos não-string passaram a ser serializados como JSON válido em vez de repr Python.

---

## [1.5.1] — 2026-06-16

### Adicionado
- **Filtro por mês no painel inicial** — o dashboard ganhou um seletor de **Período** que filtra todos os cards por mês (com base em `iniciado_em`). As opções são geradas automaticamente a partir dos meses que possuem processamentos (mais recente primeiro), além de "Todos os meses" (padrão). A seleção aplica o filtro a todas as agregações via um queryset base compartilhado. Implementado em `_obter_dados_dashboard(mes=...)`, `_meses_disponiveis_dashboard()` e `_parse_mes_dashboard()` (`apps/core/views.py`), com o seletor em `menu_inicial.html`.
- **Novo card "Custo (R$) por agente" no painel inicial** — o dashboard passou a exibir um quinto card mostrando o custo total em reais agrupado **por agente** (`Sum("custo_brl")` por `agente__nome`), complementando o já existente "Custo (R$) por integração". Permite ver quais agentes mais consomem orçamento, não só quais integrações. Implementado em `_obter_dados_dashboard()` (`apps/core/views.py`) e renderizado em `menu_inicial.html`.
- **Reprocessamento seletivo por tipo de erro** — ao reprocessar um agente, o sistema deixou de re-tentar **qualquer** documento em erro e passou a re-tentar **apenas erros transitórios** (que se resolvem sozinhos): provedor de IA indisponível/sobrecarregado, falha de conexão e timeout. Erros que exigem **intervenção manual** — chave de API inválida (401/403), requisição malformada (400/404), documento maior que o contexto do modelo, saída inválida/truncada da IA e limite de tentativas atingido — **não são mais reprocessados automaticamente**, pois repetir não resolveria e só gastaria tokens. As exceções (`AIProviderServiceError`, `ProcessamentoExecutionError`) carregam um flag `retryable` (padrão `False`, marcado `True` só nos pontos transitórios do `_post_json_request`); o novo campo `DocumentoEntrada.erro_reprocessavel` (migração `processamentos/0026`) registra a classificação por documento; e a regra de reprocessamento (`_update_documento_if_needed`) só devolve para `PENDENTE` os erros reprocessáveis. **Exceção:** se o arquivo de origem mudar (nome/caminho/conteúdo), o documento é reprocessado mesmo após erro permanente, pois o conteúdo novo pode não apresentar o mesmo problema. O comportamento foi documentado na página de ajuda do sistema (Documentação → Processamentos). Cobertura: `apps/processamentos/tests_reprocesso_seletivo.py`.

### Corrigido
- **Indisponibilidade temporária do provedor de IA exibida como erro vermelho** — quando o provedor de IA fica temporariamente indisponível/sobrecarregado (após esgotar as retentativas), a mensagem *"O provedor de IA está temporariamente indisponível ou sobrecarregado. Aguarde alguns instantes e execute o agente novamente."* era classificada como **erro técnico (vermelho)**, embora seja uma condição **transitória** em que o usuário só precisa tentar novamente. Os trechos `"temporariamente indisponivel"` e `"sobrecarregado"` foram adicionados a `_MENSAGENS_ATENCAO`, fazendo o processamento concluir com status `CONCLUIDO_ATENCAO` — a UI já renderiza esse estado em **amarelo/atenção** ("⚠ Ver atenção" em vez de "Detalhes do erro"), tanto no template quanto no polling ao vivo. Cobertura: `apps/processamentos/tests_classificacao_erro.py`.

---

## [1.5.0] — 2026-06-15

> Versão de funcionalidades e melhorias estruturais (não apenas correções), abrangendo itens do backlog de qualidade e do modelo de dados.

### Adicionado
- **Limites de execuções simultâneas (V142-1 e V142-2)** — dois novos controles de concorrência configuráveis em **Configuração Geral** (`ConfiguracaoGeral`): **"Máximo de execuções simultâneas no sistema"** (`max_execucoes_simultaneas`, padrão **5**) e **"Máximo de execuções simultâneas por usuário"** (`max_execucoes_por_usuario`, padrão **2**); `0 = sem limite` em ambos. As contagens somam processamentos em fila + em processamento. A verificação foi adicionada em `calcular_disponibilidade_agente()`: o **limite por usuário (V142-2) tem prioridade** sobre o global na mensagem exibida — ao atingi-lo, o usuário vê *"Você já atingiu o limite de agentes rodando ao mesmo tempo. Tente novamente assim que um terminar o processamento."*; ao atingir o limite global (V142-1), vê *"O sistema já tem muitos agentes rodando no momento. Tente novamente em alguns minutos."* O limite é aplicado tanto no momento do clique em **Executar** (gate em `operational_execution`) quanto refletido no estado dos cards na listagem de agentes. Para evitar N+1 na listagem, os dois contadores (globais para a lista inteira) são calculados uma única vez e repassados à função.
- **Limite de tentativas de execução por documento (DB-U2)** — novo campo **"Máximo de tentativas por documento"** na configuração do agente (`AgenteConfiguracaoOperacional.max_tentativas`, padrão **3**, `0 = sem limite`). O campo já existia no modelo mas **nunca era lido** — agora o worker o respeita. Como documentos em erro voltam para `PENDENTE` a cada reprocessamento (e são re-executados), um documento que falha repetidamente acumulava uma execução — e o custo de tokens — a cada re-run, sem teto. Agora, antes de executar cada documento (modo individual), o sistema conta quantos registros `ProcessamentoExecucaoIA` ele já possui no processamento; ao atingir o limite, o documento é marcado como erro com a mensagem *"O documento atingiu o limite de N tentativa(s) de execução e não será reprocessado."* e **nenhuma nova chamada à IA é feita** (sem consumir tokens nem inflar a contagem). O campo é exposto no formulário de criação/edição do agente e preservado na clonagem.

### Melhorado
- **Contadores de documentos do processamento recalculados de forma atômica (DB-A1)** — `Processamento.total_documentos` e `total_processados` eram recalculados em pontos espalhados usando **duas queries separadas** (`documentos.count()` e `documentos.filter(status=PROCESSADO).count()`), abrindo uma janela em que os dois valores podiam ficar incoerentes entre si. O helper `Processamento.recalcular_totais()` (uma única query `aggregate` com `Count`/`Q`) já existia mas **nunca era chamado**. Agora ele é usado nos dois pontos de finalização autoritativos — o bloco final de `execute_processing` e o reconciliador de processamentos órfãos (`stalled_processing`) —, garantindo que ambos os totais venham do mesmo snapshot do banco. Os campos físicos foram mantidos (o dashboard depende de `Sum("total_processados")` em SQL, que exige a coluna). Cobertura: `apps/processamentos/tests_recalcular_totais.py`.

### Segurança
- **Credenciais sensíveis re-criptografadas em repouso (DB-U1)** — os campos `GoogleDriveIntegration.credentials_json` (JSON da service account) e `OpenAIIntegration.api_key` já haviam sido convertidos para campos criptografados (`EncryptedTextField`/`EncryptedCharField`) na versão anterior, mas a alteração foi apenas de schema: os registros que já existiam no banco permaneciam em **texto puro**, sendo criptografados somente quando re-salvos manualmente. Um dump do banco ainda exporia essas credenciais antigas. A migração de dados `integracoes/0012_encrypt_existing_credentials` percorre todos os registros — **incluindo os soft-deletados**, que um dump também exporia — e os re-salva forçando a criptografia Fernet em repouso. A migração é idempotente (o `EncryptedFieldMixin` detecta valores já cifrados e não os re-encripta) e exige a `FIELD_ENCRYPTION_KEY` configurada (garantida pelo system check `core.E001`, que bloqueia o `migrate` se a chave estiver ausente).

---

## [1.4.5] — 2026-06-10

### Corrigido
- **Erro "Storage can not find an available filename ... max_length" ao enviar arquivos com nome longo** — uploads de editais com nomes longos falhavam de forma recorrente. Os quatro `FileField` do app `processamentos` (`arquivo_execucao_upload`, `arquivo_saida`, `DocumentoEntrada.uploaded_file`, `DocumentoSaidaProcessamento.arquivo`) usavam o `max_length` padrão do Django (**100 caracteres**). O caminho gerado — ex.: `processamentos/PROC-20260611170541-43AD3BF0/entradas/5542360_..._AGENTE_DE_PORTARIA.pdf` — ultrapassava 100 caracteres e o Django abortava o salvamento com `SuspiciousFileOperation` ("Storage can not find an available filename... allows sufficient max_length"). Os quatro campos passaram a ter `max_length=255` (migração `0025_filefield_max_length_255`). Nomes longos de arquivo agora são salvos sem erro.
- **Documento maior que o contexto do modelo retornava erro técnico genérico** — quando o documento + prompt ultrapassava a janela de contexto do modelo, o provedor retornava HTTP 400 (ex.: Anthropic `"prompt is too long: 212993 maximum context length"`) que era mascarado como o genérico "Ocorreu um erro técnico". Agora `BaseAIProviderAdapter._post_json_request` detecta erros de contexto excedido (HTTP 400/413 com trechos como `prompt is too long`, `maximum context length`, `context_length_exceeded`, `input token count`, etc. — cobrindo Anthropic, OpenAI e Gemini) e mostra a mensagem clara *"O documento é muito grande para este modelo de IA... Use um modelo com janela de contexto maior ou divida o documento em partes menores."*, mantendo o detalhe técnico (código + corpo) em `mensagem_erro_tecnico`.

### Melhorado
- **Tokens e custo de execuções com erro agora são contabilizados** — quando a chamada à IA retornava com sucesso no HTTP (o provedor gerava a resposta e **cobrava os tokens**), mas o sistema rejeitava o conteúdo (resposta truncada por limite de tokens ou JSON inválido), o processamento era marcado como erro com **0 tokens e R$ 0** — porque o registro de erro só copiava os totais anteriores do processamento (geralmente nulos) e nunca os tokens efetivamente consumidos naquela chamada. Resultado: a Anthropic descontava no painel dela, mas o nosso sistema não refletia esse consumo. Agora o `usage_metadata` (tokens de entrada/saída) "viaja" junto com a exceção desde o adapter até o registro de erro: as exceções `AIProviderServiceError` e `ProcessamentoExecutionError` carregam o `usage_metadata`; o adapter Anthropic o preenche ao detectar truncamento (`stop_reason=max_tokens`); e `_parse_structured_output` o repassa quando o JSON vem inválido. As funções `_mark_document_error` e `_mark_document_group_error` passam a gravar os tokens reais e o custo calculado (USD/BRL) no `ProcessamentoExecucaoIA` com status de erro, e o agregador de telemetria soma esses valores ao total do processamento. Assim o consumo registrado no sistema bate com o que o provedor efetivamente cobrou, mesmo quando a execução falha.

---

## [1.4.4] — 2026-06-10

### Corrigido
- **Anthropic truncava saídas grandes → "A resposta da IA nao veio em JSON valido"** — o mesmo prompt que gerava JSON válido no Gemini falhava na Anthropic com erro de JSON inválido. Causa: a API da Anthropic **exige** o campo `max_tokens` (o Gemini usa o default alto do modelo quando o campo é omitido), e o adapter forçava um teto fixo de **8192 tokens**. Saídas estruturadas grandes (ex.: análise de edital do prompt Aliança, com dezenas de itens) ultrapassavam esse limite e a resposta era **cortada no meio do JSON**, resultando em JSON inválido no parser. Correção em três camadas no `AnthropicProviderAdapter`: (1) teto padrão elevado de 8192 para **32000 tokens**, suficiente para as saídas grandes e suportado pelos modelos Claude atuais; (2) **retry automático com clamp** — se um modelo antigo (ex.: Claude 3.5 Sonnet, teto 8192) rejeitar o valor alto com HTTP 400, o adapter repete uma vez com o teto seguro de 8192, sem quebrar; (3) **detecção de truncamento** — quando a Anthropic sinaliza `stop_reason=max_tokens`, o usuário recebe a mensagem clara *"A resposta da IA foi truncada porque atingiu o limite de tokens de saída do modelo..."* em vez do confuso erro de JSON inválido, com o detalhe técnico preservado em `mensagem_erro_tecnico`.
- **Erros intermitentes "Ocorreu um erro técnico ao executar o agente"** — execuções falhavam de forma inconstante (o mesmo agente funcionava numa execução e falhava na seguinte, sem nenhuma mudança). A causa era a ausência de qualquer retentativa na camada HTTP: qualquer erro transitório do provedor de IA derrubava a execução de imediato. A Anthropic retorna `529 Overloaded` de forma intermitente quando seus servidores estão ocupados; o Gemini retorna `429`/`503` ao atingir limite de uso; timeouts pontuais também ocorrem. Esses erros eram mascarados como a mensagem genérica. Solução em `BaseAIProviderAdapter._post_json_request` (beneficia **todos os provedores** — Anthropic, Gemini, OpenAI e Groq — de uma vez): até 3 retentativas automáticas com backoff exponencial (1,5s → 3s → 6s, com jitter) para status transitórios (`408`, `409`, `425`, `429`, `500`, `502`, `503`, `504`, `529`), falhas de conexão e timeouts. O cabeçalho `Retry-After` da resposta é respeitado quando presente. Erros definitivos (`400`, `401`, `403`, `404` — chave inválida, request malformado) **não** são retentados, pois repetir não resolveria. Se as retentativas se esgotarem, o usuário recebe a mensagem clara *"O provedor de IA está temporariamente indisponível ou sobrecarregado. Aguarde alguns instantes e execute o agente novamente."* em vez do erro técnico genérico — e o detalhe técnico (código HTTP + corpo) fica preservado no campo `mensagem_erro_tecnico` para o administrador. As retentativas são registradas em log (`logger.warning`) para diagnóstico.
- **Exclusão de pasta local bloqueada por agente já excluído** — ao tentar excluir uma pasta local, o sistema exibia a mensagem "Ela está configurada como fonte padrão dos agentes: '...' " mesmo quando o agente já havia sido removido via soft delete. O `ProtectedError` do Django ocorria porque o registro `AgenteConfiguracaoOperacional` permanece no banco após o soft delete do agente (apenas `deleted_at` é preenchido, o registro não é apagado). A view agora verifica separadamente agentes ativos (que bloqueiam a exclusão) e agentes soft-deletados (cuja FK é nulificada antes do `hard_delete()`), permitindo excluir a pasta sem erro quando todos os vínculos são com agentes já removidos.

---

## [1.4.3] — 2026-06-10

### Corrigido
- **Provedor Anthropic não suportava execução de documentos** — `AnthropicProviderAdapter` implementava apenas a validação de conexão; ao executar qualquer agente com integração Anthropic, o sistema lançava `AIProviderServiceError` com "ainda nao suporta execucao de documento neste backend". Adicionados `execute_prompt_with_document`, `execute_prompt_without_document` e `execute_prompt_with_documents` usando a API `/v1/messages`: PDFs enviados como `type: document` (base64), imagens como `type: image`, arquivos de texto decodificados como `type: text`. Parâmetros mapeados: `temperature`, `top_p`, `top_k`, `max_output_tokens`, `stop_sequences`. Quando `response_mime_type: application/json`, instrução adicional é injetada no prompt (mesmo padrão do adapter Groq).
- **Erro 500 ao executar agente com upload de arquivo** — o formulário de execução enviava o PDF diretamente no corpo do POST, que excede o limite de ~8,8 KB do proxy reverso (o mesmo limite identificado no upload de arquivos locais). Solução idêntica à do upload local: o JS agora envia o arquivo em chunks de 7 KB via `AgenteExecucaoUploadView` (endpoint `/upload-execucao/`), recebe um token de arquivo temporário montado no servidor e, ao final, submete o formulário de execução com o token em vez do arquivo bruto. O Django carrega o arquivo montado do diretório temporário antes de passar ao formulário.
- **Provedor OpenAI não suportava execução de documentos** — `OpenAIProviderAdapter` herdava apenas os stubs da classe base que lançam `AIProviderServiceError`. Adicionados `execute_prompt_with_document`, `execute_prompt_without_document` e `execute_prompt_with_documents` usando a Responses API (`/v1/responses`): PDFs e binários enviados como `type: input_file` com data URL base64, imagens como `type: input_image`, arquivos de texto decodificados como `type: input_text`. Parâmetros mapeados: `temperature`, `top_p`, `max_output_tokens`. Quando `response_mime_type: application/json`, instrução JSON é injetada no prompt (mesmo padrão dos outros adapters).
- **Erro 500 ao criar ou editar agente com prompt longo** — o formulário de criação/edição de agente usava a codificação padrão `application/x-www-form-urlencoded`, que expande cada caractere português especial (`ã`, `é`, `ç`) de 2 bytes UTF-8 para 6 bytes percent-encoded (`%C3%A3`). Um prompt de ~6,6 KB (como o prompt Aliança) chegava a ~8,8 KB codificado, esbarrando intermitentemente no limite do proxy reverso. Solução: formulário alterado para `enctype="multipart/form-data"`, que envia o texto como UTF-8 puro sem expansão de encoding. Aplica-se tanto à criação quanto à edição de agentes (mesmo template).
- **Coluna de agrupamento repetia o valor em todas as linhas no Excel** — em tabelas com 3 colunas como `parte/pergunta/resposta` (ex.: prompt Aliança), a primeira coluna exibia o mesmo valor (`1 - Disposições Essenciais`, etc.) em cada linha do grupo. O renderer agora suporta a flag `"agrupar_primeira_coluna": true` na definição da aba (JSON de saída): quando presente, valores consecutivos idênticos na primeira coluna são substituídos por célula vazia, deixando o rótulo do grupo somente na primeira linha. Sem a flag, todos os valores aparecem normalmente (comportamento anterior preservado). O prompt Aliança foi atualizado para incluir a flag.

---

## [1.4.2] — 2026-06-10

### Corrigido
- **Subpastas de outras integrações apareciam no dropdown de caminho relativo** — ao configurar um agente com pasta local cuja `base_path` contém o diretório raiz compartilhado, o dropdown exibia subpastas que já são `base_path` de outras integrações (ex.: pasta pessoal de outro usuário). `LocalStorageSubpastasView` agora filtra qualquer subpasta cujo caminho absoluto coincide com o `base_path` de outra integração cadastrada.
- **Botão hamburguer sobrepunha ícones do menu no mobile** — ao abrir o sidebar o botão ☰ agora se oculta (`display: none`) e volta a aparecer ao fechar o menu (backdrop, Escape ou navegação para nova página). Evita que o botão fique fixo sobre o conteúdo do drawer enquanto ele está aberto.
- **Imagem do robô não aparecia na tela de login no servidor** — o proxy reverso (Nginx Proxy Manager / OpenResty) truncava respostas grandes, causando `ERR_CONTENT_LENGTH_MISMATCH`; o browser recebia menos bytes do que o `Content-Length` declarado e descartava a imagem (só o topo era visível antes do corte). Solução em duas camadas: (1) `robo-login-v2.png` reduzida de 1004×1004 para 320×320 px como fallback PNG (871 KB → 89 KB, −90%); (2) adicionado `robo-login-v2.webp` a 640×640 px com qualidade 85 (36 KB), servido via `<picture><source type="image/webp">` — todos os navegadores modernos usam o WebP e evitam o limite do proxy com folga. `robo-login.png.png` também recomprimida (493 KB → 355 KB, −27%) como medida preventiva.

---

## [1.4.1] — 2026-06-08

### Adicionado
- **Upload em partes (chunked) com envio paralelo** — arquivos são enviados em pedaços de 7 KB em lotes de 4 paralelos, contornando uma falha intermitente do proxy reverso (Nginx Proxy Manager / OpenResty). Testes de carga mostraram que requests com corpo acima de ~8,8 KB exigem gravação de body temporário no NPM e falham de forma intermitente sob carga (HTTP 500 do OpenResty via `proxy_intercept_errors`); corpo de ~7,8 KB (chunk de 7 KB + overhead multipart) passa de forma consistente. Lotes paralelos reduzem o número de round-trips; o último chunk é sempre enviado por último para garantir montagem atômica sem corrida de processos no servidor.
- **Exclusão de agente** — botão "Excluir" com confirmação aparece ao lado de "Editar" na tela Gerenciar agentes. Executa soft delete (preenche `deleted_at`); o agente é ocultado da listagem e dos processamentos sem ser apagado do banco.
- **Hints de formato de saída** — no formulário de agente, ao selecionar o campo "Formato padrão de saída", uma descrição dinâmica aparece logo abaixo explicando o comportamento de cada opção (Definida pela IA, Definida pelo Prompt, JSON, Excel, CSV, PDF, TXT).

### Corrigido
- **Upload para pasta sem permissão retornava HTML em vez de JSON** — `LocalStorageUploadView` agora retorna `JsonResponse` em todos os cenários de negação de acesso; o JS da tela de arquivos foi protegido contra respostas não-JSON, exibindo mensagem legível "Sem permissão de escrita nesta pasta" em vez de "Unexpected token '<'".
- **Upload com falha exibia "Upload concluído" mesmo sem enviar arquivos** — JS da tela de arquivos agora rastreia `totalEnviados` e `totalErros` separadamente; toast e status final refletem o resultado real (sucesso, parcial ou falha total) em vez de sempre mostrar mensagem verde.
- **Upload podia retornar 500 HTML em caso de erro inesperado** — `LocalStorageUploadView.post()` envolvido em try/except amplo; `OSError` em gravação de arquivo individual capturado por arquivo; qualquer exceção inesperada agora retorna `JsonResponse` com status 500 em vez de página de erro HTML.
- **Exclusão de pasta local bloqueada por agente gerava 500** — `ExcluirPastaCompartilhadaView` agora captura `ProtectedError` (FK `on_delete=PROTECT` em `AgenteConfiguracaoOperacional`) e exibe mensagem indicando quais agentes precisam ser reconfigurados antes da exclusão. Adicionado fallback `except Exception` com log para erros inesperados.
- **Mensagens do sistema não apareciam imediatamente** em quatro páginas de listagem — adicionado bloco `{% if messages %}` nos templates `fontes_documentos.html`, `processamentos.html`, `usuarios_acessos.html` e `auditoria.html`; anteriormente as mensagens acumulavam na sessão e só apareciam ao navegar para outra página que já tinha o bloco.

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
