# Plano de Integração — Ollama (IA Local)

## Visão geral

Integrar um modelo de linguagem rodando localmente no servidor, sem custo por token e sem
dependência de provedores externos como Google Gemini ou OpenAI. O Ollama será adicionado
como um app Django copiável e autocontido (`ia_local`), funcionando em paralelo com os
provedores já existentes e podendo ser reaproveitado em outros sistemas.

---

## Decisões de arquitetura

### Padrão adotado: App copiável

O código será organizado em um app Django chamado `ia_local` que pode ser copiado para
qualquer outro projeto Django. Para usar em outro sistema, basta copiar a pasta e registrar
no `INSTALLED_APPS`. Não requer publicação em pacote.

### Portabilidade do conhecimento acumulado

O sistema armazena padrões de extração aprendidos em uma tabela própria (`PadraoExtracao`).
Esses padrões podem ser exportados como JSON e importados em outro sistema, carregando o
conhecimento acumulado sem precisar mover o banco inteiro.

O que vai e o que fica ao migrar para outro sistema:

| Dado | Fica no sistema | Vai para outro sistema |
|---|---|---|
| Documentos processados | ✅ | ❌ |
| Histórico de execuções | ✅ | ❌ |
| Usuários e acessos | ✅ | ❌ |
| Configuração do agente | ✅ | ✅ Export JSON |
| Padrões aprendidos | ✅ | ✅ Export JSON |
| Configuração Ollama | ✅ | ✅ Só URL e modelo |

---

## Configuração do servidor

| Item | Valor |
|---|---|
| CPU | 8+ cores |
| RAM | 12 GB |
| GPU | Nenhuma (inferência via CPU) |
| OS | Windows / Linux (Docker) |
| Modelo escolhido | `llama3.1:8b` (recomendado) |

### Por que o llama3.1:8b com 12 GB de RAM

Com 12 GB disponíveis, a distribuição esperada de memória é:

| Processo | Uso estimado |
|---|---|
| OS + sistema base | ~2 GB |
| Docker + Django + MySQL | ~2–3 GB |
| Ollama + modelo llama3.1:8b | ~5 GB |
| Margem de segurança | ~2 GB |

O `llama3.1:8b` foi treinado com foco em múltiplos idiomas incluindo português brasileiro,
entrega a melhor qualidade de extração entre os modelos viáveis para esta configuração.
Alternativa: `mistral:7b` (~4,5 GB) se a velocidade for insatisfatória nos testes.

### Velocidade esperada (CPU, 8 cores)

| Documento | Páginas | Tempo estimado |
|---|---|---|
| Curto | 1–3 págs | 20–40 seg |
| Médio | 5–15 págs | 1–3 min |
| Longo | 20–50 págs | 5–15 min |

Velocidade aceitável para uso em background, não em tempo real.

---

## Estrutura do app ia_local

```
apps/
  ia_local/
    __init__.py
    apps.py
    admin.py
    models.py              ← OllamaConfig + PadraoExtracao
    adapters/
      __init__.py
      base.py              ← interface abstrata (contrato)
      ollama.py            ← implementação Ollama
    services/
      __init__.py
      pdf_extractor.py     ← extração de texto de PDFs
      executor.py          ← executa prompt + documento
      knowledge.py         ← exportar e importar PadraoExtracao
    management/
      commands/
        exportar_conhecimento.py
        importar_conhecimento.py
    migrations/
    README.md              ← instruções de instalação em outro sistema
```

Tudo que o app precisa para funcionar está dentro desta pasta.
O sistema hospedeiro só precisa chamá-lo através da interface em `adapters/base.py`.

---

## Modelos de dados

### OllamaConfig
Configuração da integração Ollama para o sistema.

| Campo | Tipo | Descrição |
|---|---|---|
| `nome` | texto | Nome da configuração |
| `base_url` | texto | URL do Ollama (ex: `http://ollama:11434`) |
| `modelo` | texto | Nome do modelo (ex: `llama3.1:8b`) |
| `timeout_segundos` | inteiro | Tempo máximo de espera por resposta |
| `ativo` | booleano | Se está disponível para uso |
| `ultima_validacao_em` | data/hora | Último teste de conexão |
| `ultimo_erro` | texto | Último erro registrado |

### PadraoExtracao
Padrão aprendido pelo sistema para extrair um campo específico de documentos.
Este é o modelo central de portabilidade de conhecimento.

| Campo | Tipo | Descrição |
|---|---|---|
| `campo` | texto | Nome do campo extraído (ex: `cnpj_contratante`) |
| `tipo_documento` | texto | Tipo do documento (ex: `edital_pregao`) |
| `orgao` | texto | Órgão emissor, quando específico (opcional) |
| `metodo` | choice | `regex`, `apos_palavra_chave`, `tabela`, `posicao` |
| `palavra_chave` | texto | Texto que precede o valor (opcional) |
| `padrao_regex` | texto | Expressão regular para captura (opcional) |
| `pagina` | inteiro | Página onde o campo aparece (opcional) |
| `vezes_usado` | inteiro | Quantas vezes este padrão foi aplicado |
| `vezes_correto` | inteiro | Quantas vezes retornou resultado correto |
| `confianca` | decimal | Percentual de acerto (0.0 a 1.0) |
| `ativo` | booleano | Se o padrão está em uso |
| `criado_em` | data/hora | Data de criação |
| `atualizado_em` | data/hora | Última atualização |

---

## Interface base (contrato)

Qualquer sistema que importe o `ia_local` interagirá apenas por esta interface:

```python
class BaseLocalAIAdapter:
    def validar_conexao(self) -> bool:
        """Verifica se o Ollama está rodando e o modelo disponível."""
        ...

    def executar(self, prompt: str, texto_documento: str) -> str:
        """Envia o prompt + texto do documento e retorna a resposta."""
        ...
```

---

## Arquitetura da solução completa

```
Sistema Django
    │
    ├── apps/ia_local/               ← app copiável
    │       ├── OllamaConfig         ← configuração no banco
    │       ├── PadraoExtracao       ← conhecimento acumulado
    │       ├── adapters/ollama.py   ← comunicação com Ollama
    │       └── services/
    │               ├── pdf_extractor.py   ← lê PDF → texto
    │               ├── executor.py        ← orquestra a extração
    │               └── knowledge.py       ← export/import JSON
    │
    └── Docker
            └── ollama (container)
                    └── llama3.1:8b (modelo)
```

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

Volume na seção `volumes`:
```yaml
volumes:
  ollama_data:
```

Após subir, baixar o modelo uma vez:

```bash
docker exec HUB_Agentes_ollama ollama pull llama3.1:8b
```

### 2. App ia_local

Criar a estrutura completa de pastas e arquivos conforme descrito acima.

### 3. Extração de PDF

Adicionar `pdfplumber` ao `requirements.txt`.

Criar `apps/ia_local/services/pdf_extractor.py`:
- Recebe bytes de um PDF
- Retorna o texto extraído página por página
- Detecta PDFs escaneados e retorna aviso de limitação

### 4. Adaptador Ollama

Criar `apps/ia_local/adapters/ollama.py`:
- `validar_conexao()` → `GET /api/tags` para verificar modelo disponível
- `executar(prompt, texto)` → `POST /api/chat` com texto do documento
- Tratamento de timeout (inferência CPU pode ser lenta)

### 5. Integração no fluxo do sistema principal

Registrar o tipo `ollama` como provedor de IA.

Quando a integração for do tipo Ollama:
1. Extrair texto do PDF via `pdf_extractor`
2. Aplicar padrões de `PadraoExtracao` se existirem para o tipo de documento
3. Montar o prompt e enviar ao Ollama via `executor`
4. Processar a resposta normalmente

### 6. Export e import de conhecimento

Criar `apps/ia_local/services/knowledge.py`:
- `exportar_json()` → serializa todos os `PadraoExtracao` ativos em JSON
- `importar_json(dados)` → importa padrões, evitando duplicatas por campo+tipo_documento

Criar comandos Django:
```bash
python manage.py exportar_conhecimento --output padroes.json
python manage.py importar_conhecimento --input padroes.json
```

### 7. Portal — tela de integrações

A tela de cadastro de integrações reconhecerá o tipo `ollama` e exibirá:
- Campo URL base (padrão: `http://ollama:11434`)
- Campo modelo padrão
- Sem campo de chave de API
- Botão de validar conexão

---

## Limitações conhecidas

| Limitação | Impacto | Mitigação |
|---|---|---|
| PDFs escaneados não funcionam | Alto | Informar o usuário na execução |
| Lento em documentos longos | Médio | Usar para documentos até ~20 páginas |
| Sem GPU, qualidade inferior ao Gemini | Médio | Usar para extração estruturada |
| Modelo não aprende automaticamente | Baixo | `PadraoExtracao` acumula padrões validados |
| Timeout em documentos grandes | Alto | Configurar timeout maior por integração |

---

## Quando usar Ollama vs Gemini/OpenAI

**Use Ollama quando:**
- Extração de campos fixos em editais digitais (CNPJ, valor, prazo, objeto)
- Alto volume de documentos sem custo de token
- Documentos que não podem sair do servidor (dados sensíveis)
- Desenvolvimento e testes

**Continue com Gemini/OpenAI quando:**
- PDFs escaneados (precisam de visão computacional)
- Análise jurídica complexa (qualidade superior)
- Documentos com mais de 20 páginas
- Raciocínio avançado necessário

---

## Estimativa de esforço

| Etapa | Complexidade | Estimativa |
|---|---|---|
| Infraestrutura Docker | Baixa | 1–2 horas |
| Estrutura do app ia_local | Baixa | 1–2 horas |
| Extração de PDF | Baixa | 2–3 horas |
| Adaptador Ollama | Média | 3–5 horas |
| PadraoExtracao + knowledge.py | Média | 3–4 horas |
| Ajuste no fluxo principal | Média | 2–4 horas |
| Portal | Baixa | 1–2 horas |
| **Total** | | **~13–22 horas** |

---

## Dependências a adicionar

```
pdfplumber>=0.11.0
```

O Ollama roda em container separado — sem outras dependências Python.
