# Processo de Implementação — Ollama (IA Local)

Documento de acompanhamento da implementação do Ollama no sistema HUB Agentes.
Referência técnica completa: [IA.md](./IA.md)

---

## Status dos processos

| # | Processo | Status |
|---|---|---|
| 1 | Infraestrutura — Ollama no Docker | 🔄 Em andamento |
| 2 | Extração de texto de PDF | ⏳ Aguardando |
| 3 | Adaptador Ollama | ⏳ Aguardando |
| 4 | Integração no fluxo de execução | ⏳ Aguardando |
| 5 | Portal — tela de integrações | ⏳ Aguardando |
| 6 | Testes de ponta a ponta | ⏳ Aguardando |

---

## Processo 1 — Infraestrutura: Ollama no Docker

**Status:** 🔄 Em andamento

**Objetivo:** Subir o Ollama como serviço Docker no servidor e baixar o modelo `llama3.1:8b`.

### Passo 1.1 — Adicionar o serviço Ollama ao docker-compose.yml

Adicionar o bloco abaixo no `docker-compose.yml`, junto com os serviços `db` e `web`, e incluir o volume `ollama_data` na seção `volumes`.

```yaml
ollama:
  image: ollama/ollama
  container_name: HUB_Agentes_ollama
  restart: unless-stopped
  ports:
    - "11434:11434"
  volumes:
    - ollama_data:/root/.ollama
```

### Passo 1.2 — Recriar os containers

```bash
docker compose down
docker compose up -d
```

### Passo 1.3 — Baixar o modelo llama3.1:8b

Este comando baixa o modelo dentro do container. O download é feito uma única vez e fica salvo no volume `ollama_data`.

```bash
docker exec HUB_Agentes_ollama ollama pull llama3.1:8b
```

O download tem aproximadamente **4,7 GB**. Aguardar a conclusão.

### Passo 1.4 — Verificar se o Ollama está funcionando

```bash
docker exec HUB_Agentes_ollama ollama list
```

Deve aparecer `llama3.1:8b` na lista.

### Passo 1.5 — Testar com uma pergunta simples

```bash
docker exec -it HUB_Agentes_ollama ollama run llama3.1:8b "Responda em português: qual é a capital do Brasil?"
```

Se responder corretamente, o modelo está pronto para uso.

### Passo 1.6 — Verificar que o serviço web consegue acessar o Ollama

```bash
docker exec HUB_Agentes_web curl -s http://ollama:11434/api/tags
```

Deve retornar um JSON com os modelos instalados. Isso confirma que o Django consegue se comunicar com o Ollama pela rede interna do Docker.

---

## Processo 2 — Extração de texto de PDF

**Status:** ⏳ Aguardando processo 1

**Objetivo:** Criar o serviço que lê um PDF e extrai o texto para enviar ao Ollama (que não aceita PDF diretamente como o Gemini).

Será criado:
- `pdfplumber` no `requirements.txt`
- `apps/processamentos/services/pdf_extractor.py`

---

## Processo 3 — Adaptador Ollama

**Status:** ⏳ Aguardando processo 2

**Objetivo:** Criar o adaptador que conecta o sistema ao Ollama, seguindo o mesmo padrão dos adaptadores existentes (Gemini, OpenAI).

Será criado:
- `apps/integracoes/services/ai_providers/ollama_adapter.py`
- Novo tipo `OLLAMA` em `AgentProviderType`

---

## Processo 4 — Integração no fluxo de execução

**Status:** ⏳ Aguardando processo 3

**Objetivo:** Ajustar o `agent_execution.py` para que, quando a integração for do tipo Ollama, o sistema extraia o texto do PDF antes de enviar ao modelo.

---

## Processo 5 — Portal: tela de integrações

**Status:** ⏳ Aguardando processo 4

**Objetivo:** Fazer a tela de cadastro de integrações reconhecer o tipo Ollama e exibir os campos corretos (URL base, modelo, sem chave de API).

---

## Processo 6 — Testes de ponta a ponta

**Status:** ⏳ Aguardando processo 5

**Objetivo:** Criar um agente real usando a integração Ollama, enviar um edital em PDF e validar que a extração funciona corretamente.

---

## Legenda de status

| Ícone | Significado |
|---|---|
| ⏳ | Aguardando |
| 🔄 | Em andamento |
| ✅ | Concluído |
| ❌ | Bloqueado |
