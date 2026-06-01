# Changelog

Todas as mudanças notáveis deste projeto serão documentadas neste arquivo.  
Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/).

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
