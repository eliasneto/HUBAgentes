# Processo de Implementação — Ollama (IA Local)

Documento de acompanhamento da implementação do Ollama no sistema HUB Agentes.
Referência técnica completa: [IA.md](./IA.md) | Guia de instalação em outro sistema: [IAinstall.md](./IAinstall.md)

---

## Status dos processos

| # | Processo | Status |
|---|---|---|
| 1 | Infraestrutura — Ollama no Docker | 🔄 Em andamento |
| 2 | Estrutura do app ia_local | ⏳ Aguardando |
| 3 | Extração de texto de PDF | ⏳ Aguardando |
| 4 | Adaptador Ollama | ⏳ Aguardando |
| 5 | Modelo PadraoExtracao + export/import | ⏳ Aguardando |
| 6 | Integração no fluxo de execução | ⏳ Aguardando |
| 7 | Portal — tela de integrações | ⏳ Aguardando |
| 8 | Testes de ponta a ponta | ⏳ Aguardando |

---

## Processo 1 — Infraestrutura: Ollama no Docker

**Status:** 🔄 Em andamento

**Objetivo:** Subir o Ollama como serviço Docker no servidor e baixar o modelo `llama3.1:8b`.

### ✅ Passo 1.1 — Adicionar o serviço Ollama ao docker-compose.yml

Concluído. Serviço `ollama` e volume `ollama_data` adicionados ao `docker-compose.yml`.

### ✅ Passo 1.2 — Recriar os containers

Concluído. Todos os containers iniciados com sucesso:
- `HUB_Agentes_ollama` — Started
- `HUB_Agentes_mysql` — Healthy
- `HUB_Agentes_web` — Started

### Passo 1.3 — Baixar o modelo llama3.1:8b

Download de aproximadamente **4,7 GB**. Feito uma única vez, fica salvo no volume.

```bash
docker exec HUB_Agentes_ollama ollama pull llama3.1:8b
```

### Passo 1.4 — Verificar se o modelo está instalado

```bash
docker exec HUB_Agentes_ollama ollama list
```

Deve aparecer `llama3.1:8b` na lista.

### Passo 1.5 — Testar com uma pergunta simples

```bash
docker exec -it HUB_Agentes_ollama ollama run llama3.1:8b "Responda em português: qual é a capital do Brasil?"
```

Se responder corretamente, o modelo está pronto.

### Passo 1.6 — Verificar comunicação entre web e Ollama

```bash
docker exec HUB_Agentes_web curl -s http://ollama:11434/api/tags
```

Deve retornar JSON com os modelos. Confirma que o Django consegue alcançar o Ollama.

---

## Processo 2 — Estrutura do app ia_local

**Status:** ⏳ Aguardando processo 1

**Objetivo:** Criar o app Django `ia_local` com a estrutura de pastas e arquivos base,
seguindo o padrão de app copiável que pode ser reaproveitado em outros sistemas.

Será criado em `apps/ia_local/`:

```
apps/ia_local/
  __init__.py
  apps.py
  admin.py
  models.py           ← OllamaConfig + PadraoExtracao
  adapters/
    __init__.py
    base.py           ← interface abstrata
    ollama.py         ← implementação
  services/
    __init__.py
    pdf_extractor.py
    executor.py
    knowledge.py
  management/
    commands/
      exportar_conhecimento.py
      importar_conhecimento.py
  migrations/
  README.md
```

---

## Processo 3 — Extração de texto de PDF

**Status:** ⏳ Aguardando processo 2

**Objetivo:** Criar o serviço que lê um PDF e extrai o texto para enviar ao Ollama,
que não aceita arquivos binários diretamente como o Gemini.

Será criado:
- `pdfplumber` no `requirements.txt`
- `apps/ia_local/services/pdf_extractor.py`

Comportamentos esperados:
- PDF digital → extrai texto completo por página
- PDF escaneado → detecta e retorna mensagem de limitação
- PDF corrompido → retorna erro claro

---

## Processo 4 — Adaptador Ollama

**Status:** ⏳ Aguardando processo 3

**Objetivo:** Criar o adaptador que conecta o sistema ao Ollama, seguindo a interface
definida em `base.py`.

Será criado:
- `apps/ia_local/adapters/base.py` — contrato `validar_conexao()` e `executar()`
- `apps/ia_local/adapters/ollama.py` — implementação real
- Registro do tipo `OLLAMA` no sistema de provedores de IA

---

## Processo 5 — Modelo PadraoExtracao + export/import

**Status:** ⏳ Aguardando processo 4

**Objetivo:** Criar o modelo que acumula padrões de extração aprendidos e os serviços
de exportação e importação, garantindo portabilidade do conhecimento entre sistemas.

Será criado:
- Model `PadraoExtracao` com migration
- `apps/ia_local/services/knowledge.py` com `exportar_json()` e `importar_json()`
- Comando `python manage.py exportar_conhecimento --output padroes.json`
- Comando `python manage.py importar_conhecimento --input padroes.json`
- Seção no admin para visualizar e gerenciar padrões

---

## Processo 6 — Integração no fluxo de execução

**Status:** ⏳ Aguardando processo 5

**Objetivo:** Ajustar o fluxo principal de execução de agentes para detectar quando a
integração é do tipo Ollama e usar o caminho correto (extração de texto + Ollama).

Fluxo quando integração = Ollama:
1. Extrair texto do PDF via `pdf_extractor`
2. Consultar `PadraoExtracao` por padrões relevantes para o tipo de documento
3. Montar o prompt com o texto e enviar via `executor`
4. Processar resposta normalmente

---

## Processo 7 — Portal: tela de integrações

**Status:** ⏳ Aguardando processo 6

**Objetivo:** Fazer a tela de cadastro de integrações reconhecer o tipo Ollama e exibir
os campos corretos: URL base, modelo padrão, sem campo de chave de API.

---

## Processo 8 — Testes de ponta a ponta

**Status:** ⏳ Aguardando processo 7

**Objetivo:** Criar um agente real usando a integração Ollama, enviar um edital em PDF
e validar que a extração funciona corretamente do início ao fim.

Cenários a testar:
- PDF digital simples (1–3 páginas)
- PDF digital médio (10–15 páginas)
- PDF escaneado (deve retornar aviso)
- Exportar padrões aprendidos como JSON
- Importar padrões em outro sistema

---

## Legenda de status

| Ícone | Significado |
|---|---|
| ⏳ | Aguardando |
| 🔄 | Em andamento |
| ✅ | Concluído |
| ❌ | Bloqueado |
