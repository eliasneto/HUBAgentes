# Plano de Integração — Ollama (IA Local)

## Visão geral

Integrar um modelo de linguagem rodando localmente no servidor, sem custo por token e sem dependência de provedores externos como Google Gemini ou OpenAI. O Ollama será adicionado como um novo tipo de integração de IA no sistema, funcionando em paralelo com os provedores já existentes.

---

## Configuração do servidor

| Item | Valor |
|---|---|
| CPU | 8+ cores |
| RAM | 12 GB |
| GPU | Nenhuma (inferência via CPU) |
| OS | Windows / Linux (Docker) |
| Modelo escolhido | `llama3.1:8b` (recomendado) |

### Por que o Mistral 7B com 12 GB de RAM

Com 12 GB disponíveis, a distribuição esperada de memória é:

| Processo | Uso estimado |
|---|---|
| OS + sistema base | ~2 GB |
| Docker + Django + MySQL | ~2–3 GB |
| Ollama + modelo Mistral 7B | ~4,5 GB |
| Margem de segurança | ~2 GB |

O modelo `llama3.1:8b` cabe com folga e entrega a melhor qualidade para extração de documentos em português brasileiro entre os modelos viáveis para esta configuração. O `llama3.1:8b` é a alternativa caso a velocidade seja insatisfatória nos testes.

### Velocidade esperada (CPU, 8 cores)

| Documento | Páginas | Tempo estimado |
|---|---|---|
| Curto | 1–3 págs | 20–40 seg |
| Médio | 5–15 págs | 1–3 min |
| Longo | 20–50 págs | 5–15 min |

Velocidade aceitável para uso em background (fila de processamento), não em tempo real.

---

## Arquitetura da solução

```
Portal Django
    │
    ├── Integração "Ollama Local"   (novo tipo no sistema)
    │       └── http://ollama:11434  (container Docker)
    │               └── llama3.1:8b  (modelo carregado)
    │
    └── Processamento de agente
            └── Envia PDF → Ollama → Retorna texto extraído
```

O Ollama expõe uma API compatível com OpenAI, o que significa que o adaptador existente pode ser reaproveitado com ajustes mínimos.

---

## O que precisa ser criado

### 1. Serviço Docker do Ollama

Adicionar ao `docker-compose.yml`:

```yaml
ollama:
  image: ollama/ollama
  container_name: HUB_Agentes_ollama
  ports:
    - "11434:11434"
  volumes:
    - ollama_data:/root/.ollama
  restart: unless-stopped
```

Após subir, baixar o modelo uma vez:

```bash
docker exec HUB_Agentes_ollama ollama pull llama3.1:8b
```

### 2. Modelo de integração (`AIProviderIntegration`)

Adicionar `ollama` como novo valor em `AgentProviderType`:

```python
OLLAMA = "ollama", "Ollama (local)"
```

Campos específicos para o cadastro da integração Ollama:
- URL base: `http://ollama:11434`
- Modelo padrão: `llama3.1:8b`
- Sem chave de API (campo deixado em branco)

### 3. Adaptador Ollama (`ollama_adapter.py`)

Novo arquivo em `apps/integracoes/services/ai_providers/`.

O Ollama tem API compatível com OpenAI, então o adaptador seguirá o mesmo padrão dos adaptadores existentes:

- `validate_connection()` → chama `GET /api/tags` para verificar se o modelo está disponível
- `execute(prompt, document_bytes, mime_type)` → chama `POST /api/chat` com o documento como contexto
- Tratamento de erros HTTP e de timeout (inferência CPU pode ser lenta)

**Diferença importante:** O Ollama não aceita envio de PDF diretamente como o Gemini. O documento precisa ser convertido para texto antes de enviar. Para isso, será necessário:

- Usar `pdfplumber` para extrair o texto do PDF
- Enviar o texto extraído no prompt, não o arquivo binário

### 4. Extração de texto de PDF (`pdf_extractor.py`)

Novo serviço em `apps/processamentos/services/`.

```python
# Responsabilidades:
# - Receber bytes de um PDF
# - Retornar o texto extraído página por página
# - Tratar PDFs escaneados (retornar aviso de limitação)
```

Biblioteca: `pdfplumber` (adicionar ao `requirements.txt`).

**Limitação:** PDFs escaneados (imagens) não têm texto embutido. O sistema deve identificar isso e informar ao usuário que o documento não é compatível com o modo local.

### 5. Ajuste no fluxo de execução (`agent_execution.py`)

Quando a integração for do tipo Ollama:

1. Extrair texto do PDF via `pdf_extractor`
2. Montar o prompt com o texto extraído
3. Enviar para o adaptador Ollama
4. Processar a resposta normalmente

Para os demais provedores (Gemini, OpenAI), o fluxo atual continua igual.

### 6. Tela de cadastro da integração

A tela já existente de integrações precisará reconhecer o tipo `ollama` e exibir:
- Campo URL base (padrão: `http://ollama:11434`)
- Campo modelo padrão
- Sem campo de chave de API
- Botão de validar conexão (verifica se o Ollama está respondendo e se o modelo está baixado)

---

## Limitações conhecidas

| Limitação | Impacto | Mitigação |
|---|---|---|
| PDFs escaneados não funcionam | Alto para documentos antigos | Informar o usuário na execução |
| Lento em documentos longos | Médio | Usar para documentos até ~20 páginas |
| Sem GPU, qualidade inferior ao Gemini | Médio | Usar para extração estruturada, não análise complexa |
| Modelo não aprende com o uso | Baixo — expectativa gerenciada | Documentar claramente |
| Timeout em documentos muito grandes | Alto | Configurar timeout maior na integração |

---

## Casos de uso ideais para o Ollama local

- Extração de campos fixos em editais digitais (CNPJ, valor, prazo, objeto)
- Processamento de alto volume sem custo de token
- Documentos internos que não podem sair do servidor
- Testes e desenvolvimento sem consumir cota do provedor externo

---

## Casos de uso que continuam no Gemini/OpenAI

- Documentos escaneados (precisam de visão computacional)
- Análise jurídica complexa (qualidade superior)
- Documentos muito longos (> 20 páginas)
- Respostas que exigem raciocínio avançado

---

## Etapas de implementação

### Etapa 1 — Infraestrutura
- [ ] Adicionar serviço Ollama ao `docker-compose.yml`
- [ ] Baixar o modelo `llama3.1:8b` no container
- [ ] Validar que o Ollama responde em `http://ollama:11434`

### Etapa 2 — Extração de PDF
- [ ] Adicionar `pdfplumber` ao `requirements.txt`
- [ ] Criar `apps/processamentos/services/pdf_extractor.py`
- [ ] Testar extração com editais reais (digitais e escaneados)

### Etapa 3 — Adaptador Ollama
- [ ] Criar `apps/integracoes/services/ai_providers/ollama_adapter.py`
- [ ] Registrar o tipo `ollama` em `AgentProviderType`
- [ ] Implementar `validate_connection()` e `execute()`
- [ ] Testar com documento real

### Etapa 4 — Integração no fluxo de execução
- [ ] Ajustar `agent_execution.py` para detectar tipo Ollama
- [ ] Usar extração de texto antes de enviar ao Ollama
- [ ] Testar processamento completo de ponta a ponta

### Etapa 5 — Portal
- [ ] Ajustar tela de integrações para o tipo Ollama
- [ ] Testar cadastro, validação e uso em agente

---

## Estimativa de esforço

| Etapa | Complexidade | Estimativa |
|---|---|---|
| Infraestrutura Docker | Baixa | 1–2 horas |
| Extração de PDF | Baixa | 2–3 horas |
| Adaptador Ollama | Média | 3–5 horas |
| Ajuste no fluxo | Média | 2–4 horas |
| Portal | Baixa | 1–2 horas |
| **Total** | | **~10–16 horas** |

---

## Dependências a adicionar

```
pdfplumber>=0.11.0
```

Sem outras dependências — o Ollama roda em container separado e se comunica via HTTP.
