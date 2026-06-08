# Instrução de Sistema — Tela de Agentes

**HUB Agentes v1.4.0**  
Documento de referência para criação de documentação ao usuário final.

---

## O que é um Agente?

Um **agente** é uma configuração de inteligência artificial que sabe onde buscar documentos, como processá-los e em qual formato entregar o resultado. Pense nele como uma "receita": você define os ingredientes (documentos de entrada), as instruções (prompt), o cozinheiro (modelo de IA) e a forma de servir (formato de saída).

Uma vez configurado, qualquer usuário com permissão pode executar o agente com um clique.

---

## Telas do Módulo de Agentes

O sistema possui duas telas para agentes:

| Tela | Acesso | Finalidade |
|---|---|---|
| **Agentes** (Operação) | Todos os usuários com permissão | Executar agentes disponíveis |
| **Gerenciar agentes** (Administrador/Analista) | Analista e Administrador | Criar, editar e visualizar todos os agentes |

---

## 1. Tela de Agentes — Operação

### O que o usuário vê

Cada agente aparece como um **card** com as seguintes informações:

- **Status** — Ativo / Inativo / Pausado
- **Categoria operacional** — Leitura de documento, Decisão sobre documento, etc.
- **Indicador de disponibilidade** (bolinha colorida):
  - 🟢 **Verde** — Agente liberado para execução
  - 🟡 **Amarelo** — Execução em andamento (aguardar)
  - 🔴 **Vermelho** — Erro de configuração (contate o administrador)
  - ⚫ **Cinza** — Agente indisponível
- **Mensagem de status** — Explica o estado atual
- **Tipo** — Classificador, Extrator, Validador, Estruturador ou Genérico
- **Visibilidade** — Agente para usuário ou Técnico
- **Integração IA** — Qual provedor de IA está conectado
- **Origem dos documentos** — Pasta local, Google Drive, Upload na execução, etc.
- **Aviso de acesso** — Aparece quando o usuário não tem acesso à pasta configurada no agente

### Botão Executar

| Situação | Botão | Comportamento |
|---|---|---|
| Agente disponível | **Executar** (verde) | Abre formulário de execução |
| Agente com upload | **Ícone de pasta + Executar** | Permite anexar arquivo antes de executar |
| Execução em andamento | **Indisponível** (cinza) | Desabilitado — aguardar conclusão |
| Sem acesso à pasta | **Sem acesso** (cinza) | Desabilitado — solicitar acesso ao administrador |
| Erro de configuração | **Indisponível** (cinza) | Desabilitado — contate o administrador |

### Regras de disponibilidade

O sistema verifica as seguintes condições **nessa ordem** antes de liberar o botão Executar:

1. O agente deve ter visibilidade "Agente para usuário"
2. O agente deve ser acionado pelo portal (não por evento ou agendamento)
3. O agente deve estar com status **Ativo**
4. A execução manual deve estar habilitada no agente
5. A integração de IA vinculada deve estar **Ativa**
6. Um modelo de IA deve estar configurado (na integração ou no agente)
7. As configurações de entrada/saída devem estar corretas
8. Não pode haver uma execução em andamento para o mesmo agente

---

## 2. Tela de Gerenciar Agentes

Acessível para **Analistas** e **Administradores**. Mostra todos os agentes, independente de status ou visibilidade, com botão **Editar** em cada card e botão **Criar novo agente** no topo.

---

## 3. Formulário de Criação / Edição de Agente

O formulário é dividido em quatro seções.

---

### Seção 1 — Identidade

| Campo | Obrigatório | Descrição |
|---|---|---|
| **Nome** | Sim | Nome do agente. Aparece no card e nos processamentos. |
| **Status** | Sim | **Ativo** = aparece na tela operacional para execução. **Inativo** = oculto da operação. |
| **Modelo preferencial** | Não | Nome técnico do modelo de IA (ex: `gemini-2.5-flash`). Se preenchido, **sobrepõe** o modelo padrão da integração. Deixe em branco para usar o padrão da integração. |

> **Regra:** Um agente só pode ser ativado se a integração de IA vinculada também estiver ativa.

---

### Seção 2 — Entrada: De onde ele vai ler?

Define de onde o agente vai buscar os documentos.

#### Origem padrão

| Opção | Descrição |
|---|---|
| **Google Drive — pasta** | Lê arquivos de uma pasta configurada no Google Drive. |
| **Pasta local** | Lê arquivos de uma pasta no servidor (configurada em Integrações). |
| **Arquivo informado na execução** | O usuário faz upload do documento no momento de executar. |
| **Sem origem documental** | O agente não lê arquivos. Útil para agentes que recebem parâmetros de texto. |

#### Modo de entrada (Modo de execução dos documentos)

Define como os documentos são enviados à IA:

| Modo | Ícone | Descrição | Quando usar |
|---|---|---|---|
| **Individual** | 1:1 | Processa um arquivo por vez. Cada arquivo = uma chamada à IA = uma saída. | Quando cada documento deve ser analisado de forma independente. |
| **Grupo único** | N:1 | Todos os arquivos são enviados juntos em uma única chamada à IA. A IA recebe tudo de uma vez e produz uma resposta consolidada. | Quando a análise precisa levar em conta todos os documentos ao mesmo tempo. |
| **Lote por sub-pastas** | Pasta:1 | Cada sub-pasta vira um processamento separado. Os arquivos da sub-pasta são enviados juntos à IA. Arquivos soltos na raiz são ignorados. | Quando os documentos estão organizados por cliente, período ou categoria e você precisa de uma saída por grupo. |

#### Campos condicionais de entrada

| Campo | Aparece quando | Descrição |
|---|---|---|
| **Pasta padrão Google Drive** | Origem = Google Drive | Seleciona qual pasta do Drive será usada. |
| **Pasta local padrão** | Origem = Pasta local | Seleciona qual integração de pasta local será usada. |
| **Caminho relativo padrão** | Origem = Pasta local | Sub-caminho dentro da pasta raiz. Vazio = usa a raiz da pasta. Carrega sub-pastas automaticamente via lista. |
| **Permitir upload na execução** | Origem = Sem origem documental | Permite que o usuário anexe um arquivo manualmente no momento de executar. |

---

### Seção 3 — Saída e IA: Como o resultado será gerado?

#### Integração de IA

Seleciona qual provedor de IA (Gemini, OpenAI, Groq, etc.) vai processar os documentos. Apenas integrações com status **Ativa** aparecem na lista.

#### Formato padrão de saída

Define o formato do arquivo gerado após o processamento:

| Formato | Descrição |
|---|---|
| **Definida pela IA** | O sistema injeta uma instrução no prompt pedindo que a IA indique o melhor formato (xlsx, csv, pdf, json ou txt) com base no conteúdo gerado. A IA também explica a escolha. |
| **Definida pelo Prompt** | O sistema não interfere no formato. A saída é salva exatamente como a IA retornou. Extensão detectada automaticamente: HTML → `.html`, JSON → `.json`, texto → `.txt`. Use quando o prompt já instrui o formato. |
| **JSON** | Dados estruturados em JSON. |
| **Excel (.xlsx)** | Planilha Excel. |
| **CSV** | Valores separados por vírgula. |
| **PDF** | Documento formatado. O conteúdo HTML retornado pela IA é convertido para PDF. |
| **TXT** | Texto simples. |

> **Quando usar "Definida pelo Prompt":** Se o seu prompt diz "retorne o resultado em HTML completo", use este modo. O sistema salva o HTML gerado como `.html` sem converter.
>
> **Quando usar "Definida pela IA":** Se o prompt não especifica formato e você quer que a IA decida o melhor formato para o conteúdo gerado (tabela → Excel, relatório → PDF, etc.).

#### Modo de saída (Montagem da saída)

Define como as saídas individuais são agrupadas:

| Modo | Descrição | Compatível com |
|---|---|---|
| **Uma saída por entrada** | Cada documento de entrada gera um arquivo de saída separado. | Individual, Lote por sub-pastas |
| **Uma saída por grupo** | Cada lote/sub-pasta gera um arquivo de saída consolidado. | Grupo único, Lote por sub-pastas |
| **Uma saída final** | Todos os documentos geram um único arquivo consolidado. | Grupo único, Lote por sub-pastas |

> **Regra:** "Uma saída por entrada" é **incompatível** com "Grupo único" (pois grupo único produz apenas uma resposta).
>
> **Regra:** "Uma saída final" exige "Grupo único" ou "Lote por sub-pastas" — não funciona com "Individual".

#### Empacotamento da saída

Define como o arquivo de saída é entregue ao usuário:

| Modo | Descrição | Quando usar |
|---|---|---|
| **Arquivo único** | Entrega sempre um arquivo direto, sem compactação. | Somente quando o resultado for sempre um único arquivo. |
| **ZIP se múltiplos** | Entrega direto quando há 1 saída; ZIP quando há 2 ou mais. | Uso geral — mais inteligente. |
| **Sempre ZIP** | Compacta em ZIP independentemente da quantidade. | Quando o sistema de destino espera sempre um ZIP. |

> **Regra:** "Uma saída por entrada" com "Arquivo único" é **inválido** — use ZIP se múltiplos ou Sempre ZIP.

---

### Combinações válidas de entrada × saída

| Modo de entrada | Modo de saída | Empacotamento | Resultado |
|---|---|---|---|
| Individual | Uma por entrada | ZIP se múltiplos | Um arquivo por documento, ZIP se mais de 1 |
| Individual | Uma por entrada | Sempre ZIP | ZIP com um arquivo por documento |
| Grupo único | Uma por grupo | Arquivo único | Um arquivo consolidado de todos |
| Grupo único | Uma saída final | Arquivo único | Um arquivo final com tudo |
| Lote por pasta | Uma por grupo | ZIP se múltiplos | Um arquivo por sub-pasta |
| Lote por pasta | Uma saída final | Arquivo único | Um arquivo final consolidado |

---

### Seção 4 — Parâmetros do Prompt

Permite criar variáveis dinâmicas no prompt. O usuário define:

| Campo | Descrição |
|---|---|
| **Rótulo** | Nome amigável que aparecerá para o usuário na tela de execução (ex: "Nome da empresa") |
| **Variável** | Nome técnico gerado automaticamente usado no prompt (ex: `{{nome_empresa}}`) |

**Como usar no prompt:**

```
Analise o contrato da empresa {{nome_empresa}} com sede em {{cidade}}.
```

Na execução, o sistema substituirá `{{nome_empresa}}` e `{{cidade}}` pelos valores informados pelo usuário.

---

## 4. Regras de Negócio Consolidadas

### Sobre o Agente

| Regra | Descrição |
|---|---|
| **Ativação** | Um agente só pode ser ativado se a integração de IA vinculada estiver ativa. |
| **Visibilidade** | Apenas agentes com visibilidade "Agente para usuário" aparecem na tela operacional. |
| **Modo de acionamento** | Apenas agentes configurados para "Manual no portal" aparecem na lista. |
| **Execução paralela** | Por padrão, apenas uma execução por agente pode ocorrer ao mesmo tempo. Se uma execução estiver em andamento, o botão fica desabilitado. |
| **Modelo de IA** | Se o agente tiver um modelo preferencial configurado, ele **sobrepõe** o modelo padrão da integração. |
| **Versão do prompt** | O sistema salva automaticamente uma nova versão do prompt toda vez que ele é alterado. Versões anteriores ficam registradas. |

### Sobre a Entrada

| Regra | Descrição |
|---|---|
| **Pasta local fixa** | Se o agente usa pasta local com política fixa, apenas o proprietário da pasta ou membros autorizados podem executar o agente. |
| **Upload obrigatório** | Se o agente está configurado para "Upload na execução", o usuário precisa anexar um arquivo para executar. |
| **Pasta inativa** | Se a pasta do Google Drive ou a pasta local configurada estiver inativa, o agente não pode ser executado. |
| **Sub-pasta obrigatória** | No modo "Lote por sub-pastas", a pasta raiz precisa ter pelo menos uma sub-pasta. Caso contrário, o processamento termina com **atenção** (amarelo). |

### Sobre a Saída

| Regra | Descrição |
|---|---|
| **Incompatibilidade de combinações** | "Uma saída por entrada" + "Grupo único" é inválido. "Uma saída final" + "Individual" é inválido. |
| **Arquivo único restrito** | O empacotamento "Arquivo único" só pode ser usado com modos de saída que garantem exatamente um arquivo (Ex: Grupo único → Uma por grupo). |
| **Detecção automática** | No modo "Definida pelo Prompt", a extensão do arquivo é detectada automaticamente pelo conteúdo (HTML, JSON ou texto). |

### Sobre Erros e Atenções

| Status | Cor | Significa |
|---|---|---|
| **Concluído com sucesso** | Verde | Execução concluída, arquivo disponível para download. |
| **Concluído com atenção** | Amarelo | Situação esperada que precisa de ação do usuário (pasta vazia, sub-pasta não encontrada, etc.). |
| **Concluído com erro** | Vermelho | Falha técnica (API indisponível, timeout, credencial inválida, etc.). |

---

## 5. Fluxo Completo de Execução

```
Usuário clica "Executar"
         │
         ▼
Sistema valida disponibilidade do agente
(integração ativa? modelo configurado? sem execução em andamento?)
         │
    Bloqueado? ──► Exibe mensagem e mantém botão desabilitado
         │
         ▼
Cria registro de Processamento (status: EM FILA)
         │
         ▼
Busca documentos na origem configurada
(Google Drive / Pasta local / Arquivo enviado)
         │
    Sem documentos? ──► Conclui com ATENÇÃO (amarelo)
         │
         ▼
Envia documentos + prompt para a IA
(conforme Modo de Entrada: Individual / Grupo único / Lote por pasta)
         │
    Erro técnico? ──► Conclui com ERRO (vermelho)
         │
         ▼
Monta arquivo de saída
(JSON, Excel, PDF, TXT, HTML, etc.)
         │
         ▼
Empacota (arquivo único / ZIP)
         │
         ▼
Disponibiliza para download
(status: CONCLUÍDO COM SUCESSO)
```

---

## 6. Acesso ao Módulo de Agentes

| Perfil | Tela Agentes (Operação) | Gerenciar Agentes |
|---|---|---|
| **Operador** | ✅ Pode ver e executar | ❌ Sem acesso |
| **Analista** | ✅ Pode ver e executar | ✅ Pode criar e editar |
| **Administrador** | ✅ Pode ver e executar | ✅ Pode criar e editar |

> **Nota:** O administrador pode restringir ou ampliar o acesso individualmente em **Usuários e acessos → editar usuário → Páginas extras**.

---

## 7. Perguntas Frequentes (Base para FAQ)

**Q: Posso ter dois agentes processando ao mesmo tempo?**
R: Sim, mas não o mesmo agente. Cada agente só permite uma execução simultânea. Agentes diferentes podem rodar em paralelo.

**Q: O que acontece se eu fechar o navegador durante uma execução?**
R: O processamento continua em segundo plano. Você pode acompanhar o status na tela de Processamentos.

**Q: Por que o botão Executar está desabilitado?**
R: Passe o mouse sobre o indicador colorido ao lado do nome do agente — a mensagem explica o motivo (execução em andamento, erro de configuração, sem acesso à pasta, etc.).

**Q: Qual a diferença entre "Definida pela IA" e "Definida pelo Prompt"?**
R: "Definida pela IA" faz a IA escolher o melhor formato e explica a escolha. "Definida pelo Prompt" salva exatamente o que o prompt instruiu gerar, sem conversão.

**Q: O que é "Modelo preferencial"?**
R: É um campo opcional que substitui o modelo padrão da integração de IA. Use quando quiser que um agente específico use um modelo diferente do padrão (ex: a integração usa `gemini-2.5-flash` mas o agente usa `gemini-2.5-pro`).

**Q: O que é "Caminho relativo padrão"?**
R: Quando a pasta local tem sub-pastas, este campo define qual sub-pasta o agente lê por padrão. Vazio = raiz da pasta. O campo carrega as sub-pastas automaticamente ao selecionar a integração.

**Q: Posso usar variáveis no prompt?**
R: Sim. Adicione parâmetros na seção "Parâmetros do Prompt" e use `{{nome_variavel}}` no texto do prompt. Na execução, o usuário preenche os valores.

---

*Documento gerado em 2026-06-07. Versão do sistema: v1.4.0*
