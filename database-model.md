# Modelagem de Dados — LeituraLicitacao

**Framework**: Django 5.2 + Django REST Framework  
**Banco padrão**: SQLite (dev) / MySQL (prod)  
**Auto field**: `BigAutoField` (PKs como `bigint`)  
**Idioma do domínio**: Português (BR)

---

## Visão Geral das Entidades

```
auth.User (Django nativo)
├── UserProfile              1-1
├── (created_by / updated_by)  FK em vários modelos
└── EventoAuditoria          FK (actor)

AIProviderIntegration
├── AgenteIA                 1-N
└── ProcessamentoExecucaoIA  1-N (snapshot)

AgenteIA
├── AgenteConfiguracaoOperacional  1-1
├── AgenteIA (self)          FK nullable (clonagem)
└── Processamento            1-N

GoogleDriveIntegration
└── GoogleDriveFolderSource  1-N
    └── GoogleDriveFolderSourceItem  1-N

LocalStorageIntegration
└── Processamento            1-N (opcional)

AgenteConfiguracaoOperacional
├── GoogleDriveFolderSource  FK (default input)
└── LocalStorageIntegration  FK (default input)

Processamento
├── DocumentoEntrada         1-N (CASCADE)
├── ProcessamentoExecucaoIA  1-N (CASCADE)
├── DocumentoSaidaProcessamento  1-N (CASCADE)
└── EventoAuditoria          1-N (SET_NULL)

DocumentoEntrada
├── ProcessamentoExecucaoIA  FK nullable (SET_NULL)
└── DocumentoSaidaProcessamento  1-N (CASCADE)

ProcessamentoExecucaoIA
└── DocumentoSaidaProcessamento  FK nullable (SET_NULL)
```

---

## Modelos Abstratos Base

### `TimestampedModel` — `apps/core/models.py`

| Campo        | Tipo                        | Descrição                    |
|--------------|-----------------------------|------------------------------|
| `created_at` | `DateTimeField(auto_now_add)` | Data/hora de criação         |
| `updated_at` | `DateTimeField(auto_now)`   | Última atualização           |

### `UserStampedModel` — estende `TimestampedModel`

| Campo        | Tipo                        | Descrição                    |
|--------------|-----------------------------|------------------------------|
| `created_by` | `FK → auth.User` (SET_NULL) | Quem criou                   |
| `updated_by` | `FK → auth.User` (SET_NULL) | Quem atualizou por último    |

---

## Módulo: `usuarios`

### `UserProfile` — `apps/usuarios/models.py`

| Campo            | Tipo                  | Descrição                        |
|------------------|-----------------------|----------------------------------|
| `user`           | `OneToOneField → User` (CASCADE) | Usuário Django          |
| `papel_principal`| `CharField(30)`       | `ADMINISTRADOR`, `ANALISTA`, `OPERADOR` |
| `observacoes`    | `TextField`           | Notas livres                     |
| `created_at`     | `DateTimeField`       | Auto                             |
| `updated_at`     | `DateTimeField`       | Auto                             |

---

## Módulo: `auditoria`

### `EventoAuditoria` — `apps/auditoria/models.py`

Estende `TimestampedModel`.

| Campo           | Tipo                      | Descrição                              |
|-----------------|---------------------------|----------------------------------------|
| `modulo`        | `CharField(40)`           | App/módulo que gerou o evento          |
| `acao`          | `CharField(60)`           | Ação executada                         |
| `actor`         | `FK → auth.User` (SET_NULL, nullable) | Usuário responsável          |
| `processamento` | `FK → Processamento` (SET_NULL, nullable) | Processamento relacionado  |
| `objeto_tipo`   | `CharField(80)`           | Tipo do objeto afetado                 |
| `objeto_id`     | `CharField(64)`           | ID do objeto afetado                   |
| `descricao`     | `TextField`               | Descrição do evento                    |
| `payload`       | `JSONField`               | Dados adicionais (diff, metadados)     |

**Índices**: `modulo`, `actor`, `processamento`, `created_at`

---

## Módulo: `integracoes`

### Enums

| Enum                     | Valores                                                   |
|--------------------------|-----------------------------------------------------------|
| `IntegrationStatus`      | `ATIVA`, `INATIVA`, `ERRO`                                |
| `AIProviderType`         | `OPENAI`, `ANTHROPIC`, `GEMINI`                           |
| `FolderItemType`         | `PASTA`, `PDF`, `OUTRO`                                   |

---

### `LocalStorageIntegration` — `apps/integracoes/models.py`

Estende `UserStampedModel`.

| Campo                  | Tipo               | Descrição                               |
|------------------------|--------------------|-----------------------------------------|
| `nome`                 | `CharField(120, unique)` | Nome da integração                |
| `status`               | `CharField(20)`    | `IntegrationStatus`                     |
| `base_path`            | `CharField(500)`   | Caminho absoluto na máquina             |
| `allowed_extensions`   | `JSONField`        | Padrão: `["pdf"]`                       |
| `recursive_scan`       | `BooleanField`     | Varrer subpastas                        |
| `last_validated_at`    | `DateTimeField` (nullable) | Última validação              |
| `last_error`           | `TextField`        | Último erro                             |

**Validações**: somente extensões PDF; caminho absoluto obrigatório.

---

### `GoogleDriveIntegration` — `apps/integracoes/models.py`

Estende `UserStampedModel`.

| Campo                   | Tipo               | Descrição                              |
|-------------------------|--------------------|----------------------------------------|
| `nome`                  | `CharField(120, unique)` | Nome da integração               |
| `status`                | `CharField(20)`    | `IntegrationStatus`                    |
| `auth_mode`             | `CharField(30)`    | Padrão: `service_account`              |
| `drive_folder_id`       | `CharField(255)`   | ID da pasta raiz no Drive              |
| `credentials_json`      | `TextField`        | JSON da service account (sensível)     |
| `service_account_email` | `EmailField`       | E-mail da service account              |
| `allowed_extensions`    | `JSONField`        | Padrão: `["pdf"]`                      |
| `last_connection_at`    | `DateTimeField` (nullable) | Última conexão bem-sucedida    |
| `last_error`            | `TextField`        | Último erro                            |

---

### `GoogleDriveFolderSource` — `apps/integracoes/models.py`

Estende `UserStampedModel`.

| Campo                       | Tipo               | Descrição                           |
|-----------------------------|--------------------|-------------------------------------|
| `nome`                      | `CharField(120)`   | Nome da fonte                       |
| `status`                    | `CharField(20)`    | `IntegrationStatus`                 |
| `google_drive_integration`  | `FK → GoogleDriveIntegration` (PROTECT) | Integração pai     |
| `folder_url`                | `URLField`         | URL pública da pasta                |
| `folder_id`                 | `CharField(255, editable=False)` | Extraído da URL       |
| `folder_display_name`       | `CharField(255)`   | Nome amigável                       |
| `last_validated_at`         | `DateTimeField` (nullable) | Última validação          |
| `last_error`                | `TextField`        | Último erro                         |

**Constraint**: `UniqueConstraint(google_drive_integration, folder_id)`  
**Índices**: `status`, `folder_id`

---

### `GoogleDriveFolderSourceItem` — `apps/integracoes/models.py`

Estende `TimestampedModel`.

| Campo                | Tipo                 | Descrição                               |
|----------------------|----------------------|-----------------------------------------|
| `folder_source`      | `FK → GoogleDriveFolderSource` (CASCADE) | Fonte pai             |
| `drive_item_id`      | `CharField(255)`     | ID do item no Drive                     |
| `nome`               | `CharField(255)`     | Nome do arquivo/pasta                   |
| `mime_type`          | `CharField(120)`     | Tipo MIME                               |
| `item_type`          | `CharField(20)`      | `FolderItemType`                        |
| `parent_drive_id`    | `CharField(255)`     | ID do item pai no Drive                 |
| `web_view_link`      | `URLField`           | Link de visualização                    |
| `checksum`           | `CharField(128)`     | Hash de integridade                     |
| `modified_at`        | `DateTimeField` (nullable) | Última modificação no Drive     |
| `size_bytes`         | `BigIntegerField` (nullable) | Tamanho em bytes              |
| `disponivel_para_ia` | `BooleanField`       | Apto para processamento                 |
| `sincronizado_em`    | `DateTimeField`      | Quando foi sincronizado                 |

**Constraint**: `UniqueConstraint(folder_source, drive_item_id)`  
**Índices**: `folder_source`, `drive_item_id`, `folder_source+item_type`, `folder_source+disponivel_para_ia`

---

### `OpenAIIntegration` / `AIProviderIntegration` — `apps/integracoes/models.py`

Estende `UserStampedModel`. (`AIProviderIntegration` é alias de `OpenAIIntegration`)

| Campo                      | Tipo               | Descrição                              |
|----------------------------|--------------------|----------------------------------------|
| `nome`                     | `CharField(120, unique)` | Nome da integração               |
| `provider_type`            | `CharField(40)`    | `AIProviderType` (padrão: `OPENAI`)    |
| `status`                   | `CharField(20)`    | `IntegrationStatus`                    |
| `api_key`                  | `CharField(255)`   | Chave de API (criptografada)           |
| `api_base_url`             | `URLField`         | Base URL personalizada                 |
| `organization_id`          | `CharField(120)`   | Org ID (OpenAI)                        |
| `project_id`               | `CharField(120)`   | Project ID (OpenAI)                    |
| `default_model`            | `CharField(120)`   | Modelo padrão do provedor              |
| `timeout_seconds`          | `PositiveIntegerField` | Timeout de requisição (padrão: 120) |
| `last_validated_at`        | `DateTimeField` (nullable) | Última validação              |
| `last_connection_at`       | `DateTimeField` (nullable) | Última conexão               |
| `last_validation_summary`  | `TextField`        | Resumo da última validação             |
| `last_error`               | `TextField`        | Último erro                            |

**Validações**: `default_model` obrigatório se `status=ATIVA`; `api_key` obrigatório.  
**Índices**: `provider_type+status`, `status`

---

## Módulo: `agentes_ia`

### Enums

| Enum                           | Valores                                                                                  |
|--------------------------------|------------------------------------------------------------------------------------------|
| `AgentStatus`                  | `ATIVO`, `PAUSADO`, `INATIVO`                                                            |
| `AgentType`                    | `CLASSIFICADOR`, `EXTRATOR`, `VALIDADOR`, `ESTRUTURADOR`, `GENERICO`                     |
| `AgentOperationalCategory`     | `LEITURA_DOCUMENTO`, `DECISAO_DOCUMENTO`, `ACAO_SISTEMA`, `LEITURA_ARQUIVO`, `GENERICO`  |
| `AgentVisibility`              | `USUARIO`, `TECNICO`                                                                     |
| `AgentTriggerMode`             | `PORTAL`, `BOTAO_CONTEXTUAL`, `EVENTO_SISTEMA`, `AGENDADO`, `INTERNO`                   |
| `AgentInputPolicy`             | `FIXA`, `ESCOLHIDA_NA_EXECUCAO`, `UPLOAD_NA_EXECUCAO`, `SEM_ENTRADA`, `MULTIPLA`        |
| `AgentOutputPolicy`            | `FIXA`, `CONFIGURAVEL_NA_EXECUCAO`                                                       |
| `AgentDefaultInputSourceType`  | `GOOGLE_DRIVE_FOLDER`, `LOCAL_FOLDER`, `LOCAL_FILE`, `UPLOAD_AT_EXECUTION`, `NONE`       |
| `AgentDefaultOutputFormat`     | `AI_DEFINED`, `JSON`, `XLSX`, `CSV`, `PDF`, `TXT`                                        |
| `AgentOutputDestination`       | `INTERNAL_MEDIA`                                                                         |
| `AgentDocumentExecutionMode`   | `INDIVIDUAL`, `GRUPO_UNICO`, `LOTE_POR_PASTA`                                            |
| `AgentOutputAssemblyMode`      | `UMA_POR_ENTRADA`, `UMA_POR_GRUPO`, `UMA_SAIDA_FINAL`                                    |
| `AgentOutputPackagingMode`     | `ARQUIVO_UNICO`, `ZIP_SE_MULTIPLOS`, `SEMPRE_ZIP`                                        |

---

### `AgenteIA` — `apps/agentes_ia/models.py`

Estende `UserStampedModel`.

| Campo                        | Tipo               | Descrição                                   |
|------------------------------|--------------------|---------------------------------------------|
| `nome`                       | `CharField(120)`   | Nome do agente                              |
| `slug`                       | `SlugField(unique)`| Identificador URL-friendly                  |
| `tipo`                       | `CharField(30)`    | `AgentType`                                 |
| `categoria_operacional`      | `CharField(40)`    | `AgentOperationalCategory`                  |
| `visibilidade`               | `CharField(20)`    | `AgentVisibility`                           |
| `modo_acionamento`           | `CharField(40)`    | `AgentTriggerMode`                          |
| `objetivo`                   | `TextField`        | Descrição do objetivo do agente             |
| `status`                     | `CharField(20)`    | `AgentStatus` (padrão: `INATIVO`)           |
| `prompt_base`                | `TextField`        | Prompt enviado à IA                         |
| `prompt_version`             | `CharField(30)`    | Versão do prompt (padrão: `v1`)             |
| `modelo_preferencial`        | `CharField(120)`   | Modelo preferido (sobrescreve integração)   |
| `parametros_execucao`        | `JSONField`        | Parâmetros extras de execução               |
| `ai_provider_integration`    | `FK → AIProviderIntegration` (PROTECT) | Provedor de IA            |
| `permite_execucao_manual`    | `BooleanField`     | Pode ser executado manualmente              |
| `permite_clonagem`           | `BooleanField`     | Pode ser clonado                            |
| `clonado_de`                 | `FK → self` (SET_NULL, nullable) | Rastreamento de origem           |

**Validação**: se `status=ATIVO`, `ai_provider_integration` deve estar `ATIVA`.  
**Índices**: `status+tipo`, `status+visibilidade`, `categoria_operacional`, `modo_acionamento`, `clonado_de`, `ai_provider_integration`

---

### `AgenteConfiguracaoOperacional` — `apps/agentes_ia/models.py`

Estende `UserStampedModel`. Relação 1-1 com `AgenteIA`.

| Campo                              | Tipo               | Descrição                                       |
|------------------------------------|--------------------|-------------------------------------------------|
| `agente`                           | `OneToOneField → AgenteIA` (CASCADE) | Agente dono              |
| `input_policy`                     | `CharField(40)`    | `AgentInputPolicy`                              |
| `default_input_source_type`        | `CharField(40)`    | `AgentDefaultInputSourceType`                   |
| `default_folder_source`            | `FK → GoogleDriveFolderSource` (PROTECT, nullable) | Fonte Drive padrão |
| `default_local_storage_integration`| `FK → LocalStorageIntegration` (PROTECT, nullable) | Storage local padrão |
| `default_local_relative_input_path`| `CharField(500)`   | Subcaminho relativo no storage local            |
| `allowed_input_extensions`         | `JSONField`        | Extensões permitidas (padrão: `["pdf"]`)        |
| `allow_runtime_input_choice`       | `BooleanField`     | Permite escolher entrada em tempo de execução   |
| `allow_runtime_file_upload`        | `BooleanField`     | Permite upload em tempo de execução             |
| `output_policy`                    | `CharField(40)`    | `AgentOutputPolicy`                             |
| `default_output_format`            | `CharField(20)`    | `AgentDefaultOutputFormat`                      |
| `default_output_destination`       | `CharField(40)`    | `AgentOutputDestination`                        |
| `allow_runtime_output_override`    | `BooleanField`     | Permite sobrescrever saída em tempo de execução |
| `runtime_fields_schema`            | `JSONField`        | Schema dos campos dinâmicos em runtime          |
| `builder_schema`                   | `JSONField`        | Schema de construção do agente                  |
| `document_execution_mode`          | `CharField(30)`    | `AgentDocumentExecutionMode`                    |
| `output_assembly_mode`             | `CharField(30)`    | `AgentOutputAssemblyMode`                       |
| `output_packaging_mode`            | `CharField(30)`    | `AgentOutputPackagingMode`                      |
| `prompt_parameters`                | `JSONField`        | Parâmetros injetáveis no prompt                 |
| `concurrency_policy`               | `JSONField`        | Ex: `{"block_parallel_per_agent": true}`        |

**Índices**: `input_policy`, `output_policy`, `default_input_source_type+default_output_format`

---

## Módulo: `processamentos`

### Enums

| Enum                        | Valores                                                                         |
|-----------------------------|---------------------------------------------------------------------------------|
| `ProcessingStatus`          | `CRIADO`, `EM_FILA`, `EM_PROCESSAMENTO`, `CONCLUIDO_SUCESSO`, `CONCLUIDO_ERRO`, `CANCELADO` |
| `DocumentStatus`            | `PENDENTE`, `EM_PROCESSAMENTO`, `PROCESSADO`, `ERRO`                            |
| `AIExecutionStatus`         | `SUCESSO`, `ERRO`                                                               |
| `ProcessingInputSourceType` | `GOOGLE_DRIVE_FOLDER`, `LOCAL_FOLDER`, `LOCAL_FILE`, `UPLOAD_AT_EXECUTION`, `NONE` |
| `ProcessingOutputFormat`    | `AI_DEFINED`, `JSON`, `XLSX`, `CSV`, `PDF`, `TXT`, `ZIP`                        |
| `OutputDocumentStatus`      | `GERADO`, `ERRO`                                                                |
| `ExecutionScopeType`        | `SEM_DOCUMENTO`, `INDIVIDUAL`, `GRUPO`                                          |

---

### `Processamento` — `apps/processamentos/models.py`

Estende `TimestampedModel`.

| Campo                              | Tipo                 | Descrição                                      |
|------------------------------------|----------------------|------------------------------------------------|
| `codigo`                           | `CharField(40, unique)` | Código de identificação do processamento    |
| `status`                           | `CharField(30)`      | `ProcessingStatus` (padrão: `CRIADO`)          |
| `iniciado_por`                     | `FK → auth.User` (PROTECT) | Usuário que iniciou                      |
| `agente`                           | `FK → AgenteIA` (PROTECT) | Agente utilizado                          |
| `input_source_type`                | `CharField(30)`      | `ProcessingInputSourceType`                    |
| `google_drive_integration`         | `FK → GoogleDriveIntegration` (PROTECT, nullable) | Integração Drive       |
| `folder_source`                    | `FK → GoogleDriveFolderSource` (PROTECT, nullable) | Pasta Drive          |
| `local_storage_integration`        | `FK → LocalStorageIntegration` (PROTECT, nullable) | Storage local        |
| `local_relative_input_path`        | `CharField(500)`     | Subcaminho local de entrada                    |
| `arquivo_execucao_upload`          | `FileField` (nullable) | Arquivo enviado pelo usuário                 |
| `drive_folder_id_escolhida`        | `CharField(255)`     | **Snapshot**: ID da pasta selecionada          |
| `drive_folder_nome_escolhida`      | `CharField(255)`     | **Snapshot**: Nome da pasta                    |
| `drive_folder_url_escolhida`       | `URLField`           | **Snapshot**: URL da pasta                     |
| `output_format`                    | `CharField(20)`      | `ProcessingOutputFormat`                       |
| `document_execution_mode_snapshot` | `CharField(30)`      | **Snapshot**: modo de execução do agente       |
| `output_assembly_mode_snapshot`    | `CharField(30)`      | **Snapshot**: modo de montagem da saída        |
| `output_packaging_mode_snapshot`   | `CharField(30)`      | **Snapshot**: modo de empacotamento            |
| `ai_provider_integration_snapshot` | `FK → AIProviderIntegration` (PROTECT, nullable) | **Snapshot**: provedor |
| `prompt_snapshot`                  | `TextField`          | **Snapshot**: prompt exato utilizado           |
| `modelo_snapshot`                  | `CharField(120)`     | **Snapshot**: modelo exato utilizado           |
| `mensagem_erro`                    | `TextField`          | Erro amigável para o usuário                   |
| `mensagem_erro_tecnico`            | `TextField`          | Erro técnico/stack trace                       |
| `total_documentos`                 | `PositiveIntegerField` | Total de documentos na entrada               |
| `total_processados`                | `PositiveIntegerField` | Total processados com sucesso                |
| `arquivo_saida`                    | `FileField` (nullable) | Arquivo de saída final                       |
| `arquivo_saida_nome`               | `CharField(255)`     | Nome do arquivo de saída                       |
| `arquivo_saida_formato`            | `CharField(20)`      | Formato do arquivo de saída                    |
| `arquivo_saida_liberado_em`        | `DateTimeField` (nullable) | Quando o arquivo ficou disponível        |
| `iniciado_em`                      | `DateTimeField`      | Início do processamento (padrão: now)          |
| `finalizado_em`                    | `DateTimeField` (nullable) | Fim do processamento                     |
| `execucao_iniciada_em`             | `DateTimeField` (nullable) | Início da execução IA                    |
| `execucao_finalizada_em`           | `DateTimeField` (nullable) | Fim da execução IA                       |
| `etapa_atual`                      | `CharField(120)`     | Etapa atual do processamento                   |
| `documento_atual_nome`             | `CharField(255)`     | Documento sendo processado no momento          |
| `ultima_atividade_em`              | `DateTimeField` (nullable) | Última atividade registrada              |
| `duracao_processamento_ms`         | `PositiveIntegerField` (nullable) | Duração total em ms                |
| `input_tokens`                     | `PositiveIntegerField` (nullable) | Tokens de entrada (total)          |
| `processing_tokens`                | `PositiveIntegerField` (nullable) | Tokens de reasoning (total)        |
| `output_tokens`                    | `PositiveIntegerField` (nullable) | Tokens de saída (total)            |
| `total_tokens`                     | `PositiveIntegerField` (nullable) | Total de tokens consumidos         |

**Índices**: `status`, `iniciado_por`, `agente`, `input_source_type`, `google_drive_integration`, `local_storage_integration`, `iniciado_em`

---

### `DocumentoEntrada` — `apps/processamentos/models.py`

Estende `TimestampedModel`. Ordenação padrão: `created_at`.

| Campo               | Tipo                | Descrição                                    |
|---------------------|---------------------|----------------------------------------------|
| `processamento`     | `FK → Processamento` (CASCADE) | Processamento pai              |
| `nome_arquivo`      | `CharField(255)`    | Nome do arquivo de entrada                   |
| `drive_file_id`     | `CharField(255)` (nullable) | ID do arquivo no Drive             |
| `drive_path`        | `CharField(500)` (nullable) | Caminho no Drive                   |
| `source_type`       | `CharField(30)`     | `ProcessingInputSourceType`                  |
| `source_reference`  | `CharField(500)`    | Referência de caminho local                  |
| `uploaded_file`     | `FileField` (nullable) | Arquivo enviado pelo usuário              |
| `mime_type`         | `CharField(120)`    | Tipo MIME                                    |
| `checksum`          | `CharField(128)`    | Hash de integridade                          |
| `status`            | `CharField(20)`     | `DocumentStatus` (padrão: `PENDENTE`)        |
| `mensagem_erro`     | `TextField`         | Erro de processamento                        |
| `processado_em`     | `DateTimeField` (nullable) | Quando foi processado                 |

**Validações**: somente PDF; validações por tipo de fonte.  
**Índices**: `processamento`, `drive_file_id`, `processamento+status`, `processamento+source_type`

---

### `ProcessamentoExecucaoIA` — `apps/processamentos/models.py`

Estende `TimestampedModel`. Ordenação padrão: `-tentativa_numero, -created_at`.

| Campo                    | Tipo                | Descrição                                     |
|--------------------------|---------------------|-----------------------------------------------|
| `processamento`          | `FK → Processamento` (CASCADE) | Processamento pai               |
| `documento`              | `FK → DocumentoEntrada` (SET_NULL, nullable) | Documento processado  |
| `ai_provider_integration`| `FK → AIProviderIntegration` (SET_NULL, nullable) | Provedor utilizado |
| `tentativa_numero`       | `PositiveIntegerField` | Número da tentativa (retry)                 |
| `status`                 | `CharField(20)`     | `AIExecutionStatus`                           |
| `modelo_utilizado`       | `CharField(120)`    | Modelo de IA utilizado                        |
| `execucao_iniciada_em`   | `DateTimeField` (nullable) | Início da chamada IA                   |
| `execucao_finalizada_em` | `DateTimeField` (nullable) | Fim da chamada IA                      |
| `duracao_ms`             | `PositiveIntegerField` (nullable) | Duração em ms                    |
| `input_tokens`           | `PositiveIntegerField` (nullable) | Tokens de entrada                |
| `processing_tokens`      | `PositiveIntegerField` (nullable) | Tokens de reasoning              |
| `output_tokens`          | `PositiveIntegerField` (nullable) | Tokens de saída                  |
| `total_tokens`           | `PositiveIntegerField` (nullable) | Total de tokens                  |
| `usage_metadata`         | `JSONField`         | Metadados completos de uso da API             |
| `response_summary`       | `TextField`         | Resumo do resultado                           |
| `error_message`          | `TextField`         | Detalhe do erro                               |
| `scope_type`             | `CharField(20)`     | `ExecutionScopeType`                          |
| `documentos_referencia`  | `JSONField`         | IDs de documentos referenciados nesta execução|

**Índices**: `processamento+tentativa_numero`, `processamento+status`, `execucao_iniciada_em`

---

### `DocumentoSaidaProcessamento` — `apps/processamentos/models.py`

Estende `TimestampedModel`. Ordenação padrão: `-created_at`.

| Campo                  | Tipo                | Descrição                                     |
|------------------------|---------------------|-----------------------------------------------|
| `processamento`        | `FK → Processamento` (CASCADE) | Processamento pai               |
| `documento`            | `FK → DocumentoEntrada` (CASCADE, nullable) | Documento de entrada   |
| `execucao_ia`          | `FK → ProcessamentoExecucaoIA` (SET_NULL, nullable) | Execução IA    |
| `formato`              | `CharField(20)`     | `ProcessingOutputFormat`                      |
| `status`               | `CharField(20)`     | `OutputDocumentStatus`                        |
| `arquivo`              | `FileField` (nullable) | Arquivo de saída                           |
| `arquivo_nome`         | `CharField(255)`    | Nome do arquivo de saída (auto-populado)      |
| `mensagem_erro`        | `TextField`         | Erro de geração                               |
| `liberado_em`          | `DateTimeField` (nullable) | Quando ficou disponível (auto-populado) |
| `scope_type`           | `CharField(20)`     | `ExecutionScopeType`                          |
| `documentos_referencia`| `JSONField`         | Documentos referenciados nesta saída          |

**Índices**: `processamento`, `documento`, `processamento+status`, `processamento+formato`

---

## Caminhos de Armazenamento (Media)

| Destino                   | Caminho                                           |
|---------------------------|---------------------------------------------------|
| Arquivo de saída do processamento | `processamentos/{codigo}/{filename}`      |
| Upload de entrada (execução) | `processamentos/{codigo}/uploads/{filename}`   |
| Documento de entrada (upload) | `processamentos/{codigo}/entradas/{filename}` |
| Documento de saída        | `processamentos/{codigo}/saidas/{filename}`       |

**Media root**: `BASE_DIR/media/`

---

## Módulo: `doc_system` (Reservado)

Estrutura criada com modelos abstratos placeholder. Nenhuma tabela real por enquanto.

Subapps reservados: `agentes`, `processamentos`, `integracoes`, `gerenciar_agentes`, `fontes_documentos`, `usuarios_acessos`, `painel_inicial`.

---

## Diagrama de Relacionamentos (Simplificado)

```
                    ┌──────────────┐
                    │  auth.User   │
                    └──────┬───────┘
          ┌────────────────┼──────────────────────┐
          │                │                      │
    ┌─────▼──────┐  ┌──────▼──────────┐    ┌─────▼──────────┐
    │UserProfile │  │ EventoAuditoria │    │ Processamento  │
    │  (1-1)     │  │                 │    │                │
    └────────────┘  └─────────────────┘    └────┬──┬────────┘
                                                │  │
              ┌─────────────────────────────────┘  │
              │                                     │
   ┌──────────▼──────────────────┐   ┌─────────────▼───────────┐
   │ DocumentoEntrada            │   │ ProcessamentoExecucaoIA  │
   └──────────┬──────────────────┘   └─────────────┬───────────┘
              │                                     │
              └──────────────┬──────────────────────┘
                             │
               ┌─────────────▼──────────────┐
               │ DocumentoSaidaProcessamento │
               └────────────────────────────┘

┌───────────────────────┐      ┌──────────────────────┐
│ AIProviderIntegration │──────│ AgenteIA             │
│ (OpenAIIntegration)   │      │                      │
└───────────────────────┘      └──────────┬───────────┘
                                          │ 1-1
                              ┌───────────▼───────────────────┐
                              │ AgenteConfiguracaoOperacional │
                              └───────────────────────────────┘

┌──────────────────────┐      ┌───────────────────────────────┐
│ GoogleDriveIntegration│─────│ GoogleDriveFolderSource       │
└──────────────────────┘      └───────────┬───────────────────┘
                                          │ 1-N
                              ┌───────────▼───────────────────┐
                              │ GoogleDriveFolderSourceItem   │
                              └───────────────────────────────┘
```

---

---

# Análise de Melhorias

## URGENTE — Risco Operacional / Segurança

### U1 — `credentials_json` armazenado em texto puro no banco
**Modelo**: `GoogleDriveIntegration.credentials_json` (TextField)  
**Risco**: Credenciais da service account do Google ficam em texto puro no banco. Qualquer dump de banco ou query expõe todas as credenciais.  
**Correção**: Usar `django-encrypted-model-fields` ou armazenar o JSON criptografado com chave gerenciada por variável de ambiente, similar ao que já é feito para `api_key` da `AIProviderIntegration`.

### U2 — `api_key` sem criptografia verificável
**Modelo**: `AIProviderIntegration.api_key` (CharField(255))  
**Risco**: O código menciona "criptografada" nos comentários, mas o campo é um `CharField` simples — sem evidência de criptografia real no ORM. Se não houver criptografia transparente configurada, chaves de API ficam em texto puro.  
**Correção**: Verificar e garantir uso efetivo de campo criptografado (ex: `EncryptedCharField`).

### U3 — Sem limite ou expiração em `ProcessamentoExecucaoIA` por processamento
**Risco**: Um processamento travado ou malicioso pode gerar execuções indefinidamente, consumindo tokens e custos sem controle.  
**Correção**: Adicionar campo `max_tentativas` em `AgenteConfiguracaoOperacional` ou `Processamento` e aplicar constraint no worker que cria `ProcessamentoExecucaoIA`.

---

## ALTA — Integridade de Dados / Operação

### A1 — Campos de snapshot duplicam dados sem garantia de consistência
**Modelos**: `Processamento` (campos `*_snapshot`)  
**Problema**: Os snapshots são populados via `save()` customizado, mas não há constraint de banco garantindo que foram copiados corretamente. Uma migração de código pode quebrar silenciosamente a sincronização.  
**Melhoria**: Adicionar testes de integração que validem os snapshots após criação, ou mover a lógica de snapshot para o serializer/service layer com cobertura de testes.

### A2 — Contadores `total_documentos` e `total_processados` podem dessincronizar
**Modelo**: `Processamento.total_documentos`, `total_processados`  
**Problema**: São `PositiveIntegerField` atualizados manualmente. Em cenários de concorrência ou erro, podem ficar inconsistentes com o número real de `DocumentoEntrada`.  
**Melhoria**: Substituir por propriedades calculadas via `Count` de queryset, ou usar `F()` expressions com `select_for_update` nas atualizações.

### A3 — `DocumentoSaidaProcessamento.documento` é CASCADE mas pode ser NULL
**Modelo**: `DocumentoSaidaProcessamento.documento` (CASCADE, nullable)  
**Problema**: A combinação CASCADE + nullable cria ambiguidade: o documento pode ser deletado e o saída-doc fica sem pai, ou o saída é deletado junto com o documento quando talvez não devesse ser.  
**Melhoria**: Revisar a intenção — se o saída-doc pode existir sem entrada, use `SET_NULL`; se não pode, remova o `nullable`.

### A4 — `OpenAIIntegration` tem alias `AIProviderIntegration` no código
**Problema**: `AIProviderIntegration = OpenAIIntegration` é um alias de código Python, não uma tabela separada. Isso funciona hoje mas é frágil para futuras migrações ou introspecção do admin Django.  
**Melhoria**: Criar um proxy model Django formal (`class AIProviderIntegration(OpenAIIntegration): class Meta: proxy = True`) ou renomear o modelo principal para `AIProviderIntegration`.

---

## MÉDIA — Qualidade e Manutenibilidade

### M1 — `documentos_referencia` em JSON sem referência de integridade
**Modelos**: `ProcessamentoExecucaoIA.documentos_referencia`, `DocumentoSaidaProcessamento.documentos_referencia`  
**Problema**: São listas de IDs de `DocumentoEntrada` em JSON. Se um documento é deletado, não há cascade nem validação — o JSON fica com IDs "mortos".  
**Melhoria**: Criar tabela intermediária `ExecucaoDocumentoReferencia` com FK real, ou usar M2M explícito.

### M2 — `UserProfile.papel_principal` não representa permissões no Django
**Problema**: O campo existe mas as permissões reais provavelmente são gerenciadas via `auth.Permission` ou `groups`. Há risco de divergência entre o papel declarado e as permissões efetivas.  
**Melhoria**: Mapear `papel_principal` para grupos Django automaticamente via `post_save` signal, garantindo coerência.

### M3 — Ausência de soft delete
**Problema**: Modelos críticos como `AgenteIA`, `Processamento` e `GoogleDriveIntegration` usam hard delete. Exclusão acidental é irreversível.  
**Melhoria**: Implementar soft delete com campo `deleted_at` e um manager customizado (`SoftDeleteManager`), especialmente para `AgenteIA` e `Processamento`.

### M4 — `concurrency_policy` em JSON sem schema formal
**Modelo**: `AgenteConfiguracaoOperacional.concurrency_policy`  
**Problema**: JSON livre sem validação de schema. Mudanças no formato do JSON não são detectáveis por migrações.  
**Melhoria**: Adicionar validação via `JSONSchemaValidator` no campo ou mover para campos tipados (`block_parallel_per_agent = BooleanField`).

### M5 — `runtime_fields_schema` e `builder_schema` sem documentação de contrato
**Modelo**: `AgenteConfiguracaoOperacional`  
**Problema**: Dois JSONFields que definem contratos de UI/runtime sem schema formal documentado no modelo.  
**Melhoria**: Adicionar validators JSON Schema e documentar o contrato esperado.

---

## BAIXA — Melhorias Futuras / Evolução

### B1 — Módulo `doc_system` é só placeholder
**Situação**: Oito subapps criados com modelos abstratos vazios. Isso não causa problema agora mas adiciona ruído ao projeto.  
**Sugestão**: Remover os subapps até que sejam necessários, ou documentar explicitamente que são reservados para versão futura.

### B2 — Sem modelo de Notificação ou Webhook
**Situação**: Não há como o sistema notificar sistemas externos (ou o próprio usuário) quando um processamento termina.  
**Sugestão**: Adicionar `NotificacaoProcessamento` ou configuração de webhook por agente como evolução natural.

### B3 — Rastreamento de custos por provedor
**Situação**: Os tokens são registrados mas não há modelo de `CustoExecucao` com valor monetário.  
**Sugestão**: Adicionar tabela de preços por modelo/provedor e calcular custo estimado por `ProcessamentoExecucaoIA`.

### B4 — Versionamento de prompt sem histórico
**Modelo**: `AgenteIA.prompt_version` (CharField)  
**Situação**: O campo é uma string livre. Não há histórico de versões anteriores do prompt.  
**Sugestão**: Criar modelo `PromptVersion` com histórico e timestamp, vinculado a `AgenteIA`.

### B5 — Migração de SQLite para MySQL não documentada
**Situação**: O projeto suporta ambos os bancos, mas não há script ou documentação de migração de dados entre eles.  
**Sugestão**: Documentar o processo ou adicionar comando de management Django para a migração.

---

## Resumo por Prioridade

| Nível     | Quantidade | Itens                                      |
|-----------|------------|--------------------------------------------|
| URGENTE   | 3          | U1, U2, U3                                 |
| ALTA      | 4          | A1, A2, A3, A4                             |
| MÉDIA     | 5          | M1, M2, M3, M4, M5                         |
| BAIXA     | 5          | B1, B2, B3, B4, B5                         |

**O que atacar primeiro**: U1 e U2 são riscos de segurança ativos — credenciais em texto puro no banco é o maior risco do sistema hoje. U3 é operacional mas pode gerar custos inesperados altos com provedores de IA.
