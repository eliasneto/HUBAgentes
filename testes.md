# Testes Funcionais — HUB Agentes

**Executados em:** 2026-06-05  
**Versão testada:** 1.4.0  
**Ambiente:** Local (Docker) — http://localhost:8010  
**Total de testes:** 40  
**Resultado geral:** ✅ 40 PASSOU / 0 FALHOU

---

## 🔴 URGENTE — Autenticação e Segurança

| # | Teste | Esperado | Resultado | Status |
|---|-------|----------|-----------|--------|
| 1 | GET `/` sem sessão | Retorna página de login | 200 — página de login exibida | ✅ PASSOU |
| 2 | POST `/` com admin/admin | Redireciona para `/painel/` | 200 — painel carregado | ✅ PASSOU |
| 3 | GET `/sair/` (método errado) | 405 Method Not Allowed | 405 — logout exige POST | ✅ PASSOU |
| 4 | POST `/sair/` (logout) | Sessão encerrada | 200 — sessão destruída corretamente | ✅ PASSOU |
| 5 | Acesso a `/configuracoes-gerais/` sem admin | Redirecionar / bloquear | 302 para login | ✅ PASSOU |

**Nenhuma falha encontrada.**

---

## 🟠 ALTO — Fluxo principal de processamento

| # | Teste | Esperado | Resultado | Status |
|---|-------|----------|-----------|--------|
| 6 | GET `/processamentos/` | 200 — lista carregada | 200 — lista com paginação | ✅ PASSOU |
| 7 | GET `/agentes-de-leitura/` | 200 — lista de agentes | 200 — agentes visíveis | ✅ PASSOU |
| 8 | POST `/agentes/novo/` com campos vazios | Reexibe form com erros de validação | 200 — "Este campo é obrigatório" exibido em todos os campos obrigatórios | ✅ PASSOU |
| 9 | GET `/processamentos/PROC-INVALIDO/verificar-saida/` | 404 | 404 — não encontrado | ✅ PASSOU |
| 10 | GET `/processamentos/PROC-20260603173511-5B4C/verificar-saida/` | 200 + JSON `{disponivel: true}` | 200 — arquivo existe, JSON correto | ✅ PASSOU |
| 11 | Cálculo de custo `gemini-2.0-flash` | USD e BRL calculados como Decimal | `USD: 0.003052`, `BRL: 0.0177` — tipos corretos | ✅ PASSOU |
| 12 | Cálculo de custo modelo inexistente | Retorna `(None, None)` sem erro | `None, None` — fallback silencioso | ✅ PASSOU |
| 13 | Dashboard `_obter_dados_dashboard()` | 4 datasets retornados | 7 agentes, 4 integrações — dados reais | ✅ PASSOU |

**Nenhuma falha encontrada.**

---

## 🟡 MÉDIO — Funcionalidades administrativas

| # | Teste | Esperado | Resultado | Status |
|---|-------|----------|-----------|--------|
| 14 | GET `/integracoes/` | 200 — lista de integrações | 200 — conteúdo correto | ✅ PASSOU |
| 15 | GET `/configuracao-custos/` | 200 — precificações paginadas | 200 — página com paginação | ✅ PASSOU |
| 16 | GET `/configuracao-tela-login/` | 200 — seletor de telas | 200 — 3 cards de tela | ✅ PASSOU |
| 17 | GET `/configuracoes-gerais/` | 200 — toggle e configurações | 200 — toggle liga/desliga e data próxima | ✅ PASSOU |
| 18 | Singleton `ConfiguracaoGeral.obter()` | Mesmo PK em chamadas repetidas | `pk=1` em ambas as chamadas | ✅ PASSOU |
| 19 | `_proxima_data_limpeza(30)` | Data futura no dia 30 | `2026-06-30` — futuro, dia correto | ✅ PASSOU |
| 20 | Comando `limpar_arquivos_saida --dry-run --force` | Executa sem deletar, sem erro | 0 candidatos encontrados — executou limpo | ✅ PASSOU |
| 21 | GET `/historico-e-auditoria/` | 200 — lista de eventos | 200 — paginação e filtros | ✅ PASSOU |
| 22 | GET `/usuarios-e-acessos/` | 200 — lista de usuários | 200 — usuários listados | ✅ PASSOU |
| 23 | GET `/admini/` | 200 — Django admin | 200 — interface admin carregada | ✅ PASSOU |
| 24 | GET `/fontes-de-documentos/` | 200 — lista de fontes | 200 — fontes listadas | ✅ PASSOU |
| 25 | GET `/agentes/` | 200 — gerenciar agentes | 200 — agentes listados | ✅ PASSOU |

**Nenhuma falha encontrada.**

---

## 🟢 BAIXO — APIs, integrações e utilitários

| # | Teste | Esperado | Resultado | Status |
|---|-------|----------|-----------|--------|
| 26 | GET `/agentes/api/subpastas-local/1/` | JSON com subpastas | 200 — `{"subpastas":[], "base_path":"..."}` | ✅ PASSOU |
| 27 | Registro Groq em `AIProviderType.choices` | `groq` nas choices | Presente — `groq: Groq` | ✅ PASSOU |
| 28 | Instanciação de `GroqProviderAdapter` | Sem erro | `GroqProviderAdapter` instanciado corretamente | ✅ PASSOU |
| 29 | MIME type `pdf` | `application/pdf` | `application/pdf` ✓ | ✅ PASSOU |
| 30 | MIME type `csv` | `text/csv` | `text/csv` ✓ | ✅ PASSOU |
| 31 | MIME type `png` | `image/png` | `image/png` ✓ | ✅ PASSOU |
| 32 | MIME type `xlsx` | `application/vnd.openxmlformats-...` | Correto ✓ | ✅ PASSOU |
| 33 | MIME type `txt` | `text/plain` | `text/plain` ✓ | ✅ PASSOU |
| 34 | MIME type `jpg` | `image/jpeg` | `image/jpeg` ✓ | ✅ PASSOU |
| 35 | GET `/login-preview/principal/` | 200 — tela 1 | 200 ✓ | ✅ PASSOU |
| 36 | GET `/login-preview/v2/` | 200 — tela 2 | 200 ✓ | ✅ PASSOU |
| 37 | GET `/login-preview/v3/` | 200 — tela 3 | 200 ✓ | ✅ PASSOU |
| 38 | Estado das migrations (`core`) | Todas as 9 aplicadas | `[X]` 0001–0009 — nenhuma pendente | ✅ PASSOU |
| 39 | Documentação `/doc-system/configuracoes-gerais/` | 200 — nova página | 200 — conteúdo correto (11 KB) | ✅ PASSOU |
| 40 | Documentação `/doc-system/painel-inicial/` | 200 — dashboards documentados | 200 — seções atualizadas (10 KB) | ✅ PASSOU |

**Nenhuma falha encontrada.**

---

## Resumo por criticidade

| Criticidade | Total | Passou | Falhou |
|-------------|-------|--------|--------|
| 🔴 Urgente  | 5     | 5      | 0      |
| 🟠 Alto     | 8     | 8      | 0      |
| 🟡 Médio    | 12    | 12     | 0      |
| 🟢 Baixo    | 15    | 15     | 0      |
| **Total**   | **40**| **40** | **0**  |

---

## Observações gerais

- Nenhuma falha encontrada em todos os 40 testes funcionais executados.
- O sistema responde corretamente a requisições autenticadas e não autenticadas.
- A lógica de negócio (cálculo de custo, singleton, próxima data de limpeza) funciona conforme especificado.
- Os adapters de IA (incluindo o novo Groq) estão registrados e instanciam sem erro.
- As migrations estão 100% aplicadas sem pendências.
- A detecção de MIME type para todos os 6 formatos suportados está correta.
- O comando de limpeza executa sem erros e respeita a flag `--dry-run`.

---

*Próxima execução recomendada: após cada deploy para produção.*
