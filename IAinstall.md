# Guia de Instalação — app ia_local em outro sistema Django

Este guia descreve como instalar e integrar o app `ia_local` em um novo projeto Django,
incluindo o que vai e o que fica ao migrar entre sistemas.

---

## O que é o ia_local

Um app Django autocontido que integra o Ollama (IA local) em qualquer projeto Django.
Contém o adaptador de comunicação com o Ollama, o extrator de texto de PDFs e o sistema
de padrões de extração aprendidos (`PadraoExtracao`).

---

## Pré-requisitos do sistema destino

| Requisito | Mínimo | Recomendado |
|---|---|---|
| Python | 3.11+ | 3.12 |
| Django | 4.2+ | 5.x |
| RAM no servidor | 8 GB | 12 GB |
| CPU | 4 cores | 8+ cores |
| Espaço em disco | 10 GB livres | 20 GB livres |
| Docker | Sim | Sim |

Dependência Python a adicionar no `requirements.txt` do projeto destino:

```
pdfplumber>=0.11.0
```

---

## Passo 1 — Copiar o app

Copie a pasta completa `apps/ia_local/` do sistema de origem para o sistema de destino,
mantendo a mesma estrutura:

```
projeto_destino/
  apps/
    ia_local/        ← copie esta pasta inteira
      __init__.py
      apps.py
      admin.py
      models.py
      adapters/
      services/
      management/
      migrations/
      README.md
```

---

## Passo 2 — Registrar no INSTALLED_APPS

No `settings.py` do projeto destino, adicione:

```python
INSTALLED_APPS = [
    ...
    'apps.ia_local',
]
```

---

## Passo 3 — Executar as migrations

```bash
python manage.py migrate ia_local
```

Isso cria as tabelas `ia_local_ollamaconfig` e `ia_local_padraoextracao` no banco do
projeto destino.

---

## Passo 4 — Adicionar o Ollama ao Docker do projeto destino

No `docker-compose.yml` do projeto destino:

```yaml
ollama:
  image: ollama/ollama
  container_name: NOME_DO_PROJETO_ollama
  restart: unless-stopped
  ports:
    - "11434:11434"
  volumes:
    - ollama_data:/root/.ollama
```

E na seção `volumes`:

```yaml
volumes:
  ollama_data:
```

Subir os containers:

```bash
docker compose up -d
```

---

## Passo 5 — Baixar o modelo no novo servidor

```bash
docker exec NOME_DO_PROJETO_ollama ollama pull llama3.1:8b
```

O modelo tem **~4,7 GB**. Deve ser baixado uma vez por servidor — o volume `ollama_data`
preserva o modelo entre reinicializações.

---

## Passo 6 — Cadastrar a integração no sistema

No painel de administração do projeto destino, acesse **Integrações → Nova integração → Ollama**
e preencha:

| Campo | Valor |
|---|---|
| Nome | `Ollama Local` (ou o que preferir) |
| URL base | `http://ollama:11434` |
| Modelo padrão | `llama3.1:8b` |
| Chave de API | Deixar em branco |
| Ativo | Sim |

Clique em **Validar conexão** para confirmar que o Ollama está acessível.

---

## Passo 7 — Verificar funcionamento

```bash
# Verifica que o Ollama responde
docker exec NOME_DO_PROJETO_web curl -s http://ollama:11434/api/tags

# Testa o modelo diretamente
docker exec -it NOME_DO_PROJETO_ollama ollama run llama3.1:8b \
  "Responda em português: qual é a capital do Brasil?"
```

---

## O que vai para o novo sistema (portável)

### Padrões de extração aprendidos

O conhecimento acumulado pelo sistema de origem pode ser exportado e importado no sistema
destino. Os padrões descrevem como extrair campos específicos de tipos de documentos.

**No sistema de origem — exportar:**

```bash
python manage.py exportar_conhecimento --output padroes_exportados.json
```

O arquivo gerado contém todos os padrões ativos:

```json
{
  "versao": "1.0",
  "exportado_em": "2026-05-29T10:00:00",
  "total_padroes": 34,
  "padroes": [
    {
      "campo": "cnpj_contratante",
      "tipo_documento": "edital_pregao",
      "metodo": "regex",
      "padrao_regex": "\\d{2}\\.\\d{3}\\.\\d{3}/\\d{4}-\\d{2}",
      "confianca": 0.97,
      "vezes_usado": 87,
      "ativo": true
    },
    ...
  ]
}
```

**No sistema destino — importar:**

```bash
python manage.py importar_conhecimento --input padroes_exportados.json
```

O sistema importa os padrões sem duplicar. Se um padrão para o mesmo `campo +
tipo_documento` já existir, pergunta se deve sobrescrever ou ignorar.

### Configuração de agentes

Agentes criados no sistema de origem podem ser exportados pelo portal e importados no
destino via JSON (funcionalidade separada do `ia_local`).

---

## O que NÃO vai para o novo sistema

| Dado | Motivo |
|---|---|
| Documentos processados | São dados do cliente do sistema de origem |
| Histórico de execuções | Registros operacionais, não portáveis |
| Usuários e senhas | Cada sistema tem seus próprios usuários |
| Arquivos de saída | Outputs gerados para o cliente de origem |
| Eventos de auditoria | Histórico específico de cada sistema |

---

## Banco de dados criado pela instalação

O `ia_local` cria **apenas 2 tabelas** no banco do projeto destino:

### `ia_local_ollamaconfig`

Armazena a configuração da integração com o Ollama.

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | inteiro | Chave primária |
| `nome` | varchar(100) | Nome da configuração |
| `base_url` | varchar(255) | URL do Ollama |
| `modelo` | varchar(100) | Nome do modelo |
| `timeout_segundos` | inteiro | Timeout em segundos |
| `ativo` | booleano | Se está em uso |
| `ultima_validacao_em` | datetime | Último teste |
| `ultimo_erro` | text | Último erro registrado |
| `criado_em` | datetime | Data de criação |
| `atualizado_em` | datetime | Última atualização |

### `ia_local_padraoextracao`

Armazena os padrões de extração aprendidos — esta é a tabela portável entre sistemas.

| Coluna | Tipo | Descrição |
|---|---|---|
| `id` | inteiro | Chave primária |
| `campo` | varchar(100) | Ex: `cnpj_contratante` |
| `tipo_documento` | varchar(100) | Ex: `edital_pregao` |
| `orgao` | varchar(200) | Órgão emissor (opcional) |
| `metodo` | varchar(30) | `regex`, `apos_palavra_chave`, `tabela`, `posicao` |
| `palavra_chave` | text | Texto antes do valor (opcional) |
| `padrao_regex` | text | Expressão regular (opcional) |
| `pagina` | inteiro | Página do campo (opcional) |
| `vezes_usado` | inteiro | Total de aplicações |
| `vezes_correto` | inteiro | Total de acertos |
| `confianca` | decimal(5,4) | Taxa de acerto (0.0000–1.0000) |
| `ativo` | booleano | Se está em uso |
| `criado_em` | datetime | Data de criação |
| `atualizado_em` | datetime | Última atualização |

---

## Integração mínima no sistema destino

Para usar o `ia_local` no fluxo do sistema destino, importe o executor:

```python
from apps.ia_local.services.executor import executar_extracao
from apps.ia_local.models import OllamaConfig

config = OllamaConfig.objects.get(ativo=True)
resultado = executar_extracao(
    config=config,
    prompt="Extraia o objeto, valor e prazo deste documento.",
    pdf_bytes=arquivo_bytes,
)
```

O `executor` cuida de:
1. Extrair o texto do PDF via `pdf_extractor`
2. Consultar padrões em `PadraoExtracao`
3. Enviar ao Ollama via `adapters/ollama.py`
4. Retornar o texto da resposta

---

## Modelos alternativos disponíveis

Se o `llama3.1:8b` for lento demais no servidor destino, substitua por um menor:

```bash
# Alternativa mais rápida (menos qualidade)
docker exec NOME_DO_PROJETO_ollama ollama pull mistral:7b

# Alternativa muito rápida (qualidade básica)
docker exec NOME_DO_PROJETO_ollama ollama pull llama3.2:3b
```

Depois atualize o campo `modelo` na `OllamaConfig` no admin.

---

## Checklist de instalação

- [ ] Copiar pasta `apps/ia_local/` para o projeto destino
- [ ] Adicionar `'apps.ia_local'` ao `INSTALLED_APPS`
- [ ] Adicionar `pdfplumber>=0.11.0` ao `requirements.txt`
- [ ] Executar `pip install -r requirements.txt`
- [ ] Executar `python manage.py migrate ia_local`
- [ ] Adicionar serviço Ollama ao `docker-compose.yml`
- [ ] Executar `docker compose up -d`
- [ ] Baixar o modelo: `docker exec ... ollama pull llama3.1:8b`
- [ ] Cadastrar integração Ollama no admin do sistema
- [ ] Validar conexão pelo portal
- [ ] (Opcional) Importar padrões do sistema de origem
