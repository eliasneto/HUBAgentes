# Guia — Integração Google Drive no HUB Agentes

Este guia cobre do zero a criação da credencial no Google Cloud até o cadastro da integração no sistema.

---

## Visão Geral

O sistema acessa pastas do Google Drive usando uma **Service Account** — uma conta técnica do Google criada para aplicações, sem senha interativa. Você compartilha a pasta do Drive com o e-mail da service account e o sistema passa a ter acesso a ela.

```
Google Cloud Console
  └── Projeto
        └── API Google Drive (ativada)
              └── Service Account
                    ├── E-mail (ex: hub-agentes@meu-projeto.iam.gserviceaccount.com)
                    └── Chave JSON (credencial)
                          │
                          ▼
                    HUB Agentes
                    └── Integração Google Drive
                          └── Fontes de Documento (pastas)
```

---

## Passo 1 — Criar um projeto no Google Cloud

1. Acesse [console.cloud.google.com](https://console.cloud.google.com)
2. No topo da página, clique no seletor de projeto e depois em **Novo projeto**
3. Dê um nome ao projeto (ex: `hub-agentes`) e clique em **Criar**
4. Aguarde a criação e selecione o novo projeto no seletor

> **Dica:** Se sua organização já tem um projeto Google Cloud, você pode usá-lo. Basta selecionar o projeto correto no seletor antes de continuar.

---

## Passo 2 — Ativar a API do Google Drive

1. Com o projeto selecionado, acesse o menu **APIs e Serviços > Biblioteca**
2. Na barra de pesquisa, digite `Google Drive API`
3. Clique no resultado **Google Drive API**
4. Clique em **Ativar**

Aguarde a ativação. Quando terminar, você será redirecionado para a página da API.

---

## Passo 3 — Criar a Service Account

1. No menu lateral, acesse **APIs e Serviços > Credenciais**
2. Clique em **+ Criar credenciais** e selecione **Conta de serviço**
3. Preencha os campos:
   - **Nome da conta de serviço:** `hub-agentes` (ou outro nome descritivo)
   - **ID da conta de serviço:** gerado automaticamente
   - **Descrição:** `Conta para acesso do HUB Agentes ao Google Drive` (opcional)
4. Clique em **Criar e continuar**
5. Na etapa **Conceder acesso**, você pode pular clicando em **Continuar**
6. Na etapa **Conceder acesso de usuários**, clique em **Concluído**

A service account foi criada. Você verá o e-mail dela listado em **Credenciais > Contas de serviço** (ex: `hub-agentes@meu-projeto.iam.gserviceaccount.com`). **Guarde esse e-mail — você vai precisar dele.**

---

## Passo 4 — Gerar a chave JSON

1. Na lista de **Contas de serviço**, clique no e-mail da conta recém-criada
2. Acesse a aba **Chaves**
3. Clique em **Adicionar chave > Criar nova chave**
4. Selecione o tipo **JSON** e clique em **Criar**
5. O arquivo `.json` será baixado automaticamente para o seu computador

> **Atenção:** Este arquivo contém a credencial privada. Guarde-o em local seguro e **nunca** o publique em repositórios Git ou compartilhe por e-mail.

O conteúdo do arquivo tem esta estrutura (resumida):
```json
{
  "type": "service_account",
  "project_id": "meu-projeto",
  "private_key_id": "abc123...",
  "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...",
  "client_email": "hub-agentes@meu-projeto.iam.gserviceaccount.com",
  "client_id": "123456789",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  ...
}
```

---

## Passo 5 — Compartilhar a pasta do Drive com a Service Account

O sistema acessa apenas as pastas que você compartilhar explicitamente com o e-mail da service account.

1. Abra o **Google Drive** com sua conta pessoal ou corporativa
2. Localize (ou crie) a pasta que os agentes vão usar
3. Clique com o botão direito na pasta e selecione **Compartilhar**
4. No campo **Adicionar pessoas**, cole o e-mail da service account (ex: `hub-agentes@meu-projeto.iam.gserviceaccount.com`)
5. Defina a permissão como **Leitor** (somente leitura é suficiente para os agentes)
6. Desmarque a opção **Notificar pessoas** (a service account não recebe e-mails)
7. Clique em **Compartilhar**

> **Repita este passo para cada pasta** que você quiser adicionar como fonte de documento no sistema.

---

## Passo 6 — Pegar o ID da pasta (opcional)

O ID da pasta fica na URL quando você a abre no Drive:

```
https://drive.google.com/drive/folders/1A2B3C4D5E6F7G8H9I0J
                                        ↑ esse trecho é o ID da pasta
```

Você não precisa anotar agora — o sistema extrai o ID automaticamente ao colar a URL na tela de fontes de documento.

---

## Passo 7 — Criar a Integração no Sistema

1. No HUB Agentes, acesse **Configurações > Integrações**
2. Clique em **Nova integração**
3. No campo **Tipo de integração**, selecione **Google Drive**
4. Preencha os campos:

| Campo | O que preencher |
|---|---|
| **Nome** | Nome descritivo (ex: `Google Drive - Documentos Licitação`) |
| **Status** | `Ativa` |
| **E-mail da Service Account** | O e-mail copiado no Passo 3 (ex: `hub-agentes@meu-projeto.iam.gserviceaccount.com`) |
| **Credencial JSON** | Cole o conteúdo completo do arquivo `.json` baixado no Passo 4 |
| **Extensões permitidas** | Deixe em branco para usar o padrão (`pdf`), ou informe as extensões desejadas |

5. Clique em **Salvar**
6. O sistema validará automaticamente a conexão com o Google Drive. Se a validação falhar, verifique:
   - Se a API do Google Drive está ativada no projeto (Passo 2)
   - Se o JSON foi colado corretamente (deve ser o JSON completo, incluindo chaves `{` e `}`)
   - Se o e-mail da service account está correto

---

## Passo 8 — Adicionar Fontes de Documento

Após criar a integração, você pode adicionar as pastas do Drive como fontes:

1. Acesse **Operação > Fontes de Documentos**
2. Clique em **Nova fonte**
3. Selecione a integração Google Drive criada no Passo 7
4. Cole a **URL da pasta** do Google Drive (ex: `https://drive.google.com/drive/folders/1A2B3C4D5E6F...`)
5. O sistema extrairá o ID automaticamente
6. Dê um nome para a fonte e clique em **Salvar**

A fonte aparecerá na listagem. Você pode então associá-la a um agente na tela **Gerenciar Agentes**, campo **Origem padrão**.

---

## Verificação Rápida

| Etapa | Verificação |
|---|---|
| API ativada | Console Google Cloud > APIs e Serviços > Painel → "Google Drive API" aparece com status ativo |
| Service account criada | Credenciais > Contas de serviço → e-mail listado |
| Chave JSON baixada | Arquivo `.json` presente no seu computador |
| Pasta compartilhada | Drive > pasta > botão de compartilhamento → e-mail da service account na lista |
| Integração criada | Sistema > Integrações → integração com status "Ativa" |
| Fonte criada | Fontes de Documentos → pasta aparece na lista |

---

## Erros Comuns

| Erro | Causa provável | Solução |
|---|---|---|
| `API not enabled` | API do Drive não foi ativada | Repetir Passo 2 no projeto correto |
| `Invalid credentials` | JSON colado incompleto ou corrompido | Abrir o arquivo `.json` em um editor de texto, selecionar tudo e colar novamente |
| `File not found` / pasta vazia | Pasta não compartilhada com a service account | Repetir Passo 5 com o e-mail correto |
| Validação falha sem mensagem clara | Projeto Google Cloud sem faturamento ativo | Ativar faturamento no Console do Google (necessário mesmo para a API gratuita) |
| `403 Forbidden` ao acessar pasta | Permissão insuficiente | Verificar se a service account tem pelo menos permissão de **Leitor** na pasta |

---

## Perguntas Frequentes

**Preciso criar uma service account por pasta?**  
Não. Uma única service account pode ser compartilhada em quantas pastas quiser. Você compartilha cada pasta com o mesmo e-mail e cadastra cada uma como uma fonte de documento separada.

**A service account tem acesso a todo o meu Drive?**  
Não. Ela acessa apenas as pastas e arquivos explicitamente compartilhados com o e-mail dela. O resto do Drive permanece inacessível.

**Preciso renovar a chave JSON?**  
Não automaticamente. A chave JSON não expira, mas você pode revogá-la a qualquer momento no Google Cloud Console (aba Chaves da service account) e gerar uma nova se necessário.

**O sistema modifica ou exclui arquivos do Drive?**  
Não. O sistema usa permissão de **Leitor** — ele lê os arquivos para processamento mas nunca altera, move ou exclui nada no Drive.
