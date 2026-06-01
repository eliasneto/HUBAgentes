# Pendências pré-produção — HUB Agentes

Levantamento feito em 31/05/2026 antes do go-live da versão 1.0.0.

---

## Críticos (resolver antes de apontar usuários reais)

### 1. Migration 0015 pendente

**Arquivo:** `apps/processamentos/migrations/0015_documentoentrada_pasta_grupo.py`

O campo `pasta_grupo` já é usado ativamente em `agent_execution.py` e `document_sources.py`. Se o banco subir sem essa migration, qualquer processamento em modo **Lote por pasta** crasha com `OperationalError: no such column`.

- Via Docker: o `entrypoint.sh` já roda `migrate --noinput` automaticamente — ok.
- Via atualização manual: executar `python manage.py migrate` antes de iniciar o servidor.

**Ação:** confirmar que `migrate` é sempre executado antes de iniciar o servidor ao atualizar o código.

---

### 2. Execução de IA síncrona dentro da requisição HTTP

**Arquivo:** `apps/processamentos/services/operational_execution.py`

Todo o processamento acontece dentro do ciclo de request/response. Com 3 workers, 3 usuários simultâneos travam o servidor.

~~Curto prazo resolvido em 01/06/2026~~: timeout do Gunicorn aumentado de 180s para **600s** (10 min) + `graceful-timeout` de 60s. Workers não morrem mais em processamentos longos.

**Ação definitiva pendente:** implementar execução assíncrona com Celery + Redis para eliminar o bloqueio de workers por completo.

---

### 3. FIELD_ENCRYPTION_KEY — fallback silencioso em caso de chave errada

**Arquivo:** `apps/core/fields.py`

~~Corrigido em 01/06/2026~~: o `get_prep_value` agora tem fallback adequado — se a chave não estiver configurada, loga erro e salva sem criptografia em vez de causar 500. Um Django system check (`core.W001`) avisa no startup quando a chave está ausente.

**Ação residual:** testar explicitamente no ambiente de produção que a `FIELD_ENCRYPTION_KEY` decifra os registros já cadastrados. Nunca rotacionar a chave sem migrar os dados antes.

---

## Médios (não bloqueiam, mas resolver em breve)

### 4. CSRF e cookies inseguros se o acesso for via HTTPS

**Arquivo:** `config/settings.py` / `.env`

- `CSRF_TRUSTED_ORIGINS` usa `http://` — se o domínio de produção usar HTTPS, todos os POSTs retornam `403 CSRF verification failed`.
- `SESSION_COOKIE_SECURE = False` e `CSRF_COOKIE_SECURE = False` — cookies trafegam em HTTP mesmo com HTTPS ativo.

**Ação:** se o deploy usar HTTPS (nginx, proxy reverso, etc.):
1. Atualizar `CSRF_TRUSTED_ORIGINS` para `https://seu-dominio.com` no `.env`.
2. Definir `SESSION_COOKIE_SECURE=True` e `CSRF_COOKIE_SECURE=True` no `.env`.

---

### 5. Worker Docker sem healthcheck

**Arquivo:** `docker-compose.yml`, serviço `worker`

O worker roda `reconciliar_processamentos_orfaos` em loop de 300s. Se o processo interno travar silenciosamente, processamentos ficam presos em `EM_PROCESSAMENTO` indefinidamente e o orquestrador não sabe que o worker está com problema.

**Ação:** adicionar `healthcheck` ao serviço `worker` no `docker-compose.yml`.

---

### 6. Agentes sem AgenteConfiguracaoOperacional

**Arquivo:** `apps/agentes_ia/services.py`

Agentes criados antes do portal (via admin ou migração) podem não ter `AgenteConfiguracaoOperacional` associada. O `get_or_create` cria uma com valores default que podem não corresponder ao comportamento esperado do agente.

**Ação:** verificar no banco de produção se todos os agentes ativos têm `AgenteConfiguracaoOperacional`. Rodar uma query de conferência antes do go-live:
```sql
SELECT id, nome FROM agentes_ia_agenteia
WHERE id NOT IN (SELECT agente_id FROM agentes_ia_agenteconfiguracaooperacional)
AND deleted_at IS NULL;
```

---

### 8. `docker compose restart` não recarrega variáveis do `.env`

**Contexto:** descoberto em produção em 01/06/2026.

`docker compose restart <serviço>` reinicia o container mas mantém o ambiente da criação original — alterações no `.env` não são lidas.

**Sempre usar ao mudar o `.env`:**
```bash
docker compose up -d --force-recreate web
```

Isso recria o container lendo o `.env` atualizado.

---

### 7. Template agente_execucao.html sem uso

**Arquivo:** `templates/portal_operacional/agente_execucao.html`

O template existe no filesystem mas nunca é renderizado — a view só faz redirect. Não causa erro, mas gera confusão de manutenção.

**Ação:** remover o arquivo ou documentar que é código legado.
