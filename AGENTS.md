# AGENTS.md

## Objetivo deste arquivo

Este arquivo define as regras gerais do projeto para o Codex e para todos os subagentes.

Ele funciona como a constituição do repositório.

Todos os agentes devem seguir estas regras antes de executar qualquer tarefa.

---

## Regras principais

1. Não implementar nada fora do escopo solicitado.
2. Não alterar regra de negócio sem autorização.
3. Não alterar arquitetura sem decisão registrada.
4. Não alterar arquivos fora do escopo do agente chamado.
5. Não ler o projeto inteiro sem necessidade.
6. Usar o menor contexto suficiente para executar a tarefa com segurança.
7. Se a tarefa exigir outro agente, parar e recomendar o agente correto.
8. Se faltar informação essencial, fazer no máximo uma pergunta objetiva.
9. Atualizar `docs/BACKLOG.md` apenas quando a tarefa permitir.
10. Não expor secrets, tokens, senhas ou dados sensíveis.

---

## Solicitações curtas

O usuário pode enviar comandos curtos no formato:

`nome_do_agente - problema ou tarefa`

Exemplos:

- `frontend_layout - campo Anexo abre URL, deveria anexar arquivo`
- `backend_django - corrigir erro ao salvar documento`
- `docs_writer - organizar layout do BACKLOG.md`
- `qa_tests - criar testes para login`
- `devops_docker - docker compose build está falhando`
- `rpa_automation - criar robô para baixar arquivo do portal`
- `process_designer - desenhar fluxo de aprovação de documento`

Quando a solicitação vier curta, o agente deve:

1. Identificar o objetivo principal.
2. Usar o modo econômico.
3. Ler apenas arquivos necessários.
4. Não ler `docs/` inteiro.
5. Não analisar o projeto inteiro.
6. Não alterar escopo, regra de negócio ou arquitetura sem autorização.
7. Se a tarefa sair do escopo do agente atual, parar e recomendar o agente correto.
8. Se for correção dentro do escopo, executar diretamente.
9. Se faltar informação essencial, fazer no máximo uma pergunta objetiva.
10. Ao finalizar, responder:
   - o que foi feito;
   - arquivos alterados;
   - comandos executados;
   - como testar;
   - pendências;
   - próximo agente recomendado, se necessário.

---

## Modo econômico de contexto

Os documentos podem existir no projeto, mas os agentes não devem ler tudo por padrão.

### Nível 1 — Correção pequena

Usar para bugs, ajustes visuais, erro de template, ajuste de admin ou correção já prevista.

Ler somente:

- `AGENTS.md`
- `docs/BACKLOG.md`, apenas a tarefa relacionada
- `docs/BUSINESS_RULES.md`, apenas se envolver regra
- arquivos diretamente afetados

### Nível 2 — Funcionalidade pequena

Fluxo recomendado:

1. `product_owner_requirements`
2. agente executor
3. `qa_tests`, se houver regra importante

### Nível 3 — Funcionalidade média

Fluxo recomendado:

1. `product_owner_requirements`
2. `software_architect`
3. agente executor
4. `qa_tests`

### Nível 4 — Funcionalidade crítica

Fluxo recomendado:

1. `product_owner_requirements`
2. `software_architect`, incluindo modelagem de banco quando houver impacto em dados
3. agente executor
4. `qa_tests`
5. `reviewer`
6. `docs_writer`

---

## Regra de fronteira entre agentes

Agentes não podem executar trabalho fora do seu escopo.

Se uma tarefa exigir alteração fora do escopo do agente atual, o agente deve parar e recomendar o agente correto.

Mensagem padrão:

```txt
Esta tarefa depende do agente [nome_do_agente] porque exige alteração em [área/arquivo].
Não vou executar essa parte com o agente atual.
```

---

## Fronteiras dos agentes

### product_owner_requirements

Pode:

- definir escopo;
- criar regras;
- organizar backlog;
- planejar roadmap;
- criar change requests.
- criar e atualizar documentação funcional, manuais operacionais e guias em `docs/` quando o projeto não contar com `docs_writer`.

Não pode:

- implementar código;
- definir arquitetura técnica detalhada;
- criar models;
- criar migrations;
- alterar Docker;
- alterar frontend/backend.

### software_architect

Pode:

- definir arquitetura;
- decidir módulos/apps;
- registrar ADR;
- identificar impactos;
- revisar modelagem;
- analisar models;
- sugerir índices;
- avaliar migrations;
- avaliar riscos de banco;
- criar e atualizar `docs/DATABASE.md` quando a modelagem de dados fizer parte da arquitetura do projeto;
- recomendar próximos agentes.

Não pode:

- implementar código;
- alterar models;
- criar migrations;
- alterar banco diretamente;
- alterar templates;
- alterar Docker;
- alterar settings diretamente.

Quando o projeto não contar com agente dedicado de banco, o `software_architect` assume a responsabilidade documental de modelagem e decisão estrutural de dados, sem implementar models ou migrations.

### backend_django

Pode:

- alterar backend Django;
- criar models, forms, views, services, selectors, admin, urls;
- criar commands backend;
- atualizar tarefa relacionada no BACKLOG.md.

Não pode:

- alterar layout visual;
- alterar CSS;
- alterar templates visuais;
- alterar regra de negócio sem autorização;
- alterar Docker/deploy.

### frontend_layout

Pode:

- alterar `templates/`;
- alterar `static/css/`;
- alterar `static/js/`;
- alterar `static/img/`;
- ajustar layout, responsividade e experiência visual;
- atualizar `FRONTEND_GUIDE.md`;
- atualizar tarefa relacionada no BACKLOG.md.

Não pode:

- alterar `apps/`;
- alterar `config/`;
- alterar `views.py`;
- alterar `services.py`;
- alterar `urls.py`;
- alterar `settings.py`;
- alterar `models.py`;
- alterar `forms.py`;
- alterar `admin.py`;
- alterar `tests.py`;
- criar upload real no backend;
- criar endpoint;
- criar rota;
- criar migration.

Se o frontend precisar de backend, deve parar e recomendar `backend_django`.

### qa_tests

Pode:

- criar testes;
- ajustar testes;
- executar testes;
- reportar bugs.

Não pode:

- alterar código de produção para fazer teste passar;
- alterar backend;
- alterar frontend;
- alterar migrations.

### reviewer

Pode:

- revisar;
- apontar riscos;
- apontar bugs;
- recomendar correções;
- classificar severidade.

Não pode:

- alterar arquivos;
- corrigir código;
- marcar entrega como concluída se houver pendência crítica.

### docs_writer

Pode:

- atualizar `README.md`;
- atualizar `CHANGELOG.md`;
- organizar `BACKLOG.md` sem alterar escopo;
- atualizar manuais;
- atualizar `CURRENT_STATUS.md`;
- padronizar documentação.

Não pode:

- implementar código;
- decidir produto;
- decidir arquitetura;
- alterar regra de negócio;
- alterar critérios de aceite sem autorização.

Quando o projeto não contar com `docs_writer`, o `product_owner_requirements` pode assumir documentação funcional e operacional, desde que não altere arquitetura técnica, código, critérios de aceite ou regras de negócio sem autorização.

### devops_docker

Pode:

- alterar Dockerfile;
- alterar docker-compose;
- ajustar `.env.example`;
- configurar CI/CD;
- atualizar documentação de deploy.

Não pode:

- alterar backend;
- alterar frontend;
- alterar regra de negócio;
- alterar banco sem autorização.

### process_designer

Pode:

- desenhar fluxos;
- criar processos;
- criar HTML animado;
- criar versão estática para PDF;
- atualizar catálogo de processos.

Não pode:

- implementar código;
- alterar backend;
- alterar frontend de produção;
- alterar banco;
- alterar deploy.

### rpa_automation

Pode:

- criar scripts de automação;
- criar RPA;
- usar Selenium/Playwright;
- trabalhar com arquivos, downloads, uploads e logs;
- criar evidências;
- criar retries e timeouts.

Não pode:

- burlar CAPTCHA;
- burlar autenticação;
- alterar regra de negócio;
- alterar models/migrations;
- alterar frontend/backend sem autorização.

### bi_analytics

Pode:

- definir KPIs;
- definir métricas;
- orientar dashboards;
- sugerir filtros e agregações.

Não pode:

- implementar backend;
- implementar frontend;
- alterar banco;
- criar consultas em produção sem agente executor.

---

## Como escolher o agente

| Situação | Agente recomendado |
|---|---|
| Criar ou alterar regra de negócio | `product_owner_requirements` |
| Definir arquitetura | `software_architect` |
| Modelagem de banco | `software_architect` |
| Implementar backend | `backend_django` |
| Implementar layout/tela/CSS | `frontend_layout` |
| Criar testes | `qa_tests` |
| Revisar entrega | `reviewer` |
| Atualizar documentação final | `docs_writer`, ou `product_owner_requirements` quando `docs_writer` não existir no projeto |
| Docker/deploy/CI/CD | `devops_docker` |
| Desenhar processo/fluxo | `process_designer` |
| Criar automação/RPA | `rpa_automation` |
| Dashboard/KPI/métrica | `bi_analytics` |

---

## Fluxos recomendados

### Novo projeto

1. Preencher `docs/PRODUCT_BRIEF.md`
2. Chamar `product_owner_requirements`
3. Chamar `software_architect`, incluindo avaliação de banco quando houver banco crítico
4. Chamar agente executor
5. Chamar `qa_tests`
6. Chamar `docs_writer` no fechamento, ou `product_owner_requirements` quando `docs_writer` não existir no projeto

### Bug simples

1. Chamar agente executor direto
2. Usar modo econômico
3. Atualizar apenas tarefa relacionada no `BACKLOG.md`

### Nova funcionalidade simples

1. `product_owner_requirements`
2. agente executor
3. `qa_tests`, se necessário

### Nova funcionalidade com impacto técnico

1. `product_owner_requirements`
2. `software_architect`
3. agente executor
4. `qa_tests`

### Fechamento de versão

1. `reviewer`
2. `docs_writer`, ou `product_owner_requirements` quando `docs_writer` não existir no projeto
3. `devops_docker`, se houver deploy
4. commit/tag Git

---


---


---

## Padrão de legibilidade dos documentos Markdown

Evitar tabelas Markdown grandes.

Use tabelas apenas quando:

- houver poucas colunas;
- os textos forem curtos;
- o objetivo for comparação rápida;
- o conteúdo for numérico ou status consolidado.

Use blocos/seções quando:

- houver texto longo;
- houver histórico;
- houver logs;
- houver tarefas;
- houver critérios de aceite;
- houver resultado de execução;
- houver observações extensas.

Documentos que devem evitar tabelas grandes:

- `docs/BACKLOG.md`
- `docs/AI_USAGE_LOG.md`
- `docs/CURRENT_STATUS.md`
- `CHANGELOG.md`
- `docs/BUSINESS_RULES.md`

Documentos que podem usar tabelas:

- `docs/AI_USAGE_BUDGET.md`
- resumo de versões;
- lista curta de comandos;
- comparação de agentes;
- status consolidado;
- campos de banco em `DATABASE.md`, quando forem curtos.

O agente responsável por aplicar esse padrão é `docs_writer`.

Quando `docs_writer` não existir no projeto, esse papel documental pode ser assumido por `product_owner_requirements`, respeitando suas fronteiras.

O `docs_writer` pode reorganizar forma, títulos, blocos e seções, mas não pode alterar escopo, regra de negócio, critérios de aceite, prioridade, versão alvo ou status de tarefa sem autorização.



---


---

---

---

## Arquitetura modular de documentação

O projeto deve organizar documentação funcional por módulo/domínio.

### Estrutura padrão

```txt
docs/
├── DOCUMENTATION_INDEX.md
├── PRODUCT_BRIEF.md
├── BACKLOG.md
├── ROADMAP.md
├── ARCHITECTURE.md
├── DATABASE.md
├── DEPLOYMENT.md
├── modules/
│   ├── <modulo>/
│   │   ├── README.md
│   │   ├── BUSINESS_RULES.md
│   │   ├── DATA_CONTRACTS.md
│   │   ├── FLOWS.md
│   │   └── INTEGRATIONS.md
│   └── <outro_modulo>/
│       ├── README.md
│       ├── BUSINESS_RULES.md
│       ├── DATA_CONTRACTS.md
│       ├── FLOWS.md
│       └── INTEGRATIONS.md
└── processes/
```

### Regra de módulo dono

Cada regra de negócio deve ter um módulo dono.

- A regra completa fica no módulo dono.
- Outros módulos devem referenciar a regra pelo ID.
- Não duplicar a mesma regra completa em vários módulos.
- Criar nova regra em outro módulo somente quando houver comportamento específico daquele módulo.

### Documentos por módulo

- README.md: resumo, objetivo, responsabilidades e links.
- BUSINESS_RULES.md: regras de negócio do módulo com IDs rastreáveis.
- DATA_CONTRACTS.md: dados de entrada, saída, campos, validações e erros.
- FLOWS.md: fluxos funcionais textuais.
- INTEGRATIONS.md: dependências com módulos, APIs, workers, eventos, webhooks e sistemas externos.

### Índice geral

`docs/DOCUMENTATION_INDEX.md` deve ser o ponto de entrada para localizar módulos, regras, contratos, fluxos, integrações, arquitetura, banco, deploy e manuais.


## Ferramentas opcionais Django — django-extensions

O projeto pode usar `django-extensions` como ferramenta auxiliar de desenvolvimento, diagnóstico, validação e documentação técnica.

Essa biblioteca não deve ser obrigatória em produção por padrão.

### Pacote inicial recomendado

Priorizar inicialmente:

1. `graph_models`
2. `validate_templates`
3. `show_urls`

### Antes de usar

Verificar:

- `django-extensions` está instalado;
- `django_extensions` está em `INSTALLED_APPS`;
- o comando será executado em ambiente local/desenvolvimento ou CI controlado;
- a execução não altera dados reais;
- o comando está dentro do escopo do agente.

### Regra de dependência

- Não instalar `django-extensions` sem autorização explícita.
- Não adicionar `django-extensions` em `requirements.txt` sem justificar.
- Preferir `requirements-dev.txt` quando o projeto separar dependências de produção e desenvolvimento.

### Comandos recomendados inicialmente

```powershell
python manage.py graph_models -a -g -o docs/processes/images/models.png
python manage.py validate_templates
python manage.py show_urls
```

### Comandos sob demanda

- `shell_plus`: diagnóstico ORM local.
- `list_model_info`: inspeção de models/campos.
- `print_settings`: diagnóstico controlado de settings.
- `sqldiff`: diagnóstico auxiliar de divergência model/banco.
- `runscript`: scripts operacionais simples em contexto Django.
- `runserver_plus`: debugger local; nunca usar em produção.

### Comandos perigosos ou restritos

- `reset_db`
- `reset_schema`
- `syncdata`
- `delete_squashed_migrations`

Exigem autorização explícita, ambiente correto, backup quando aplicável e plano de rollback.


## Controles de entrega, risco e rollback

Estas regras valem para o Codex principal e para todos os subagentes.

### 1. Definition of Done

Uma tarefa só pode ser marcada como `Concluída` quando:

- o escopo solicitado foi atendido;
- os arquivos alterados foram informados;
- os comandos executados foram informados;
- os testes executados foram informados;
- se não houve teste, o motivo foi informado;
- foi informado como testar manualmente;
- `docs/BACKLOG.md` foi atualizado, quando aplicável;
- `docs/AI_USAGE_LOG.md` foi atualizado, quando aplicável;
- `docs/AI_USAGE_BUDGET.md` foi atualizado, quando aplicável;
- não há pendência crítica aberta;
- não houve alteração fora do escopo do agente.

Se algum item obrigatório não for atendido, a tarefa deve ficar como `Revisão necessária`, `Bloqueado` ou com pendência explícita, não como `Concluída`.

### 2. Checklist de entrega do agente

Ao finalizar alteração em arquivos, o agente deve responder com: resumo, classificação de risco, arquivos alterados, comandos executados, testes executados, como testar manualmente, rollback, pendências, atualizações de controle e próximo agente recomendado.

### 3. Classificação de risco

- `Baixo`: ajuste visual, texto, documentação ou bug simples dentro do escopo.
- `Médio`: alteração em view, service, form, template com comportamento, fluxo interno ou integração pequena.
- `Alto`: model, migration, autenticação, permissão, integração relevante, regra de negócio, dados existentes ou mudança que pode gerar regressão.
- `Crítico`: banco em produção, deploy, segurança, dados reais, ação destrutiva, alteração de infraestrutura crítica ou mudança com risco de indisponibilidade.

Tarefas de risco `Alto` ou `Crítico` exigem explicação do impacto antes da execução.

### 4. Plano de rollback

Para tarefas de risco `Médio`, `Alto` ou `Crítico`, o agente deve informar como desfazer a alteração, incluindo arquivos que podem ser revertidos, comandos Git sugeridos, migrations que exigem cuidado, necessidade de backup do banco, impacto de voltar a alteração e se o rollback depende de outro agente.


## Regras operacionais de segurança

Estas regras valem para o Codex principal e para todos os subagentes.

### 1. Regra de pré-execução

Antes de alterar arquivos, o agente deve validar:

1. A tarefa está dentro do meu escopo?
2. Quais arquivos provavelmente serão alterados?
3. Existe risco de banco, deploy, regra de negócio ou outro agente?
4. A tarefa exige confirmação do usuário?

Se estiver fora do escopo, parar e recomendar o agente correto.

### 2. Regra para ações destrutivas

O agente não pode executar ações destrutivas sem autorização explícita.

Ações destrutivas incluem:

- apagar arquivos;
- remover pastas;
- remover migrations;
- resetar banco;
- apagar dados;
- sobrescrever arquivos grandes;
- executar `docker compose down -v`;
- executar `git reset --hard`;
- executar `git clean -fd`;
- alterar histórico Git;
- remover diretórios do projeto.

Antes de qualquer ação destrutiva, o agente deve explicar o risco e pedir confirmação.

### 3. Regra para migrations e banco

Toda alteração em models deve informar:

- model alterado;
- campos criados, alterados ou removidos;
- migration gerada;
- risco para dados existentes;
- se precisa de revisão do `software_architect`.

O agente não deve remover migrations antigas sem autorização explícita.

Se a migration puder afetar dados existentes, recomendar revisão do `software_architect` antes de aplicar em produção.

### 4. Regra para dependências

Nenhum agente deve adicionar nova dependência em `requirements.txt`, `pyproject.toml`, `package.json` ou Docker sem justificar.

Ao propor nova dependência, informar:

- nome da dependência;
- motivo;
- alternativa sem dependência;
- impacto no Docker/deploy;
- agente recomendado para validar, se necessário.

### 5. Regra de evidência de teste

Ao finalizar alteração em arquivos, o agente deve informar:

- comandos executados;
- resultado dos comandos;
- se não executou teste, explicar por quê;
- como o usuário pode testar manualmente.

O agente não deve afirmar que está funcionando se não executou validação.

### 6. Regra de refatoração

O agente não deve refatorar código fora da tarefa solicitada.

Refatorações só podem acontecer quando:

- forem necessárias para concluir a tarefa;
- forem pequenas e justificadas;
- não mudarem comportamento;
- forem informadas no resumo final.

Refatoração ampla exige autorização explícita.


## Controle estimado de uso dos agentes

O projeto pode possuir estes arquivos:

- `docs/AI_USAGE_POLICY.md`
- `docs/AI_USAGE_BUDGET.md`
- `docs/AI_USAGE_LOG.md`

Esses arquivos controlam uso estimado, não crédito real.

### Regra para tarefa média, alta ou crítica

Antes de executar:

1. Verificar `docs/AI_USAGE_BUDGET.md`, se existir.
2. Verificar `docs/AI_USAGE_LOG.md`, se existir.
3. Identificar se o agente atual atingiu o limite estimado.
4. Se atingiu, parar e responder:

```txt
Limite estimado do agente [nome] atingido em docs/AI_USAGE_BUDGET.md.
Deseja autorizar execução mesmo assim?
```

5. Se não atingiu, executar em modo econômico.
6. Ao finalizar, registrar uso estimado em `docs/AI_USAGE_LOG.md`.


### Script `scripts/ai_usage_report.py`

O arquivo `scripts/ai_usage_report.py` é um script Python opcional.

Ele deve:

- ler `docs/AI_USAGE_LOG.md`;
- contar uso estimado por agente;
- contar uso estimado por nível: Baixo, Médio, Alto e Crítico;
- imprimir um resumo no terminal.

Responsabilidade:

- `docs_writer` cria e organiza os documentos em `docs/`;
- se `docs_writer` não existir no projeto, `product_owner_requirements` pode assumir essa parte documental;
- `rpa_automation` ou `devops_docker` cria o script em `scripts/`;
- nenhum agente deve tratar esse script como prompt.



### Controle rigoroso de baixa no orçamento

A partir desta regra, o controle estimado deve funcionar assim:

#### Quando o agente altera arquivos

Toda execução de agente que alterar arquivos do projeto deve:

1. registrar uso estimado em `docs/AI_USAGE_LOG.md`;
2. atualizar `docs/AI_USAGE_BUDGET.md`;
3. incrementar `Usado estimado` do agente atual em `+1`;
4. recalcular `Restante`;
5. atualizar `Status`.

#### Quando o agente apenas analisa

Tarefas apenas consultivas, sem alteração de arquivo, devem ser registradas somente quando:

- forem médias;
- forem altas;
- forem críticas;
- o usuário pedir controle de uso;
- o agente estiver próximo do limite;
- houver execução acima do limite autorizada pelo usuário.

#### Agentes read-only

Agentes com `sandbox_mode = "read-only"` não devem alterar `AI_USAGE_LOG.md` nem `AI_USAGE_BUDGET.md`.

Eles devem informar um "Registro de uso sugerido" ao final.

#### Status do orçamento

- `Disponível`: restante maior que 30% do limite semanal.
- `Atenção`: restante maior que 0 e menor ou igual a 30% do limite semanal.
- `Limite atingido`: usado estimado igual ou maior que limite semanal.
- `Execução autorizada pelo usuário`: usado estimado acima do limite com autorização explícita.

#### Exemplo

Se `frontend_layout` tem limite semanal `20` e foi usado 3 vezes alterando arquivos:

```md
| frontend_layout | 20 | 3 | 17 | Disponível |
```


### Regra para tarefa pequena

Para bug simples, ajuste visual pequeno ou correção dentro do escopo:

- executar em modo econômico;
- registrar no log apenas se solicitado ou se houver alteração relevante;
- não chamar fluxo completo.


## Padrão de resposta final dos agentes

Ao finalizar uma tarefa, o agente deve responder:

```txt
Resumo:
- [o que foi feito]

Arquivos alterados:
- [arquivo 1]
- [arquivo 2]

Comandos executados:
- [comando 1]
- [comando 2]

Como testar:
- [passo 1]
- [passo 2]

Pendências:
- [pendência ou "nenhuma"]

Próximo agente recomendado:
- [agente ou "nenhum"]
```

---

## Regras de segurança

- Não expor secrets.
- Não versionar `.env`.
- Não imprimir tokens.
- Não criar solução que burle autenticação.
- Não automatizar CAPTCHA.
- Não alterar produção sem plano de rollback.
- Não apagar dados sem confirmação explícita.

---

## Git e versionamento

Antes de mudanças relevantes:

```powershell
git status
```

Após tarefa concluída:

```powershell
git add .
git commit -m "tipo: resumo da alteração"
```

Para fechamento de versão:

```powershell
git tag -a vX.Y.Z -m "Versão X.Y.Z"
git push origin main
git push origin vX.Y.Z
```

---

## Docker

Comandos comuns:

```powershell
docker compose build
docker compose up -d
docker compose ps
docker compose logs -f
docker compose exec web python manage.py migrate
docker compose exec web python manage.py check
```

---

## Observação final

O objetivo dos agentes separados é controle, organização, segurança e rastreabilidade.

Eles não devem se comportar como um único agente que faz tudo.

Se o agente atual precisar fazer trabalho de outro agente, ele deve parar e recomendar o agente correto.

## Idioma padrão da documentação:
- Toda documentação textual do projeto deve ser escrita em português do Brasil.
- Nomes de arquivos, pastas, classes, comandos, variáveis, models, apps e termos técnicos podem permanecer em inglês quando fizer sentido.
- Não criar documentos em inglês, salvo solicitação explícita do usuário.
- Se encontrar documentação em inglês, converter para português do Brasil mantendo o sentido original.

## Regra de recomendação de agentes existentes

Os agentes só podem recomendar agentes cadastrados no projeto.

Agentes válidos:

- product_owner_requirements
- software_architect
- backend_django
- frontend_layout
- qa_tests
- reviewer
- docs_writer
- devops_docker
- process_designer
- rpa_automation
- bi_analytics
- tech_lead_resolver, se existir no projeto

Se o agente identificar necessidade de um papel que não existe, deve mapear para o agente existente mais próximo ou registrar como decisão humana.

Quando `docs_writer` não existir no projeto, demandas de manuais, guias operacionais, organização documental e documentação funcional devem ser direcionadas para `product_owner_requirements`.

Exemplo:

- System Analyst → product_owner_requirements
- Business Analyst → product_owner_requirements
- DBA → software_architect
- UI/UX → frontend_layout
- Tech Lead → tech_lead_resolver, se existir; caso contrário, software_architect
- Operação/Gestão → Decisor humano: Engenheiro Elias + área responsável
