(function () {
  // NPM (OpenResty) rejeita corpos > ~8,8 KB. Usamos chunks de 7 KB (mesmo
  // limite validado para upload local) para contornar o limite do proxy.
  const EXEC_CHUNK_SIZE = 7 * 1024;
  const EXEC_PARALLEL_CHUNKS = 4;
  const POLL_INTERVAL_MS = 8000;
  const IN_PROGRESS_STATUSES = new Set(["criado", "em_fila", "em_processamento"]);

  const form = document.querySelector("[data-execution-form]");

  let _modalPendingForm = null;

  setupAgentCardUploads();
  setupExecModal();

  if (!form) {
    return;
  }

  const sourceSelect = form.querySelector("[name='input_source_type']");
  const sourceBlocks = Array.from(form.querySelectorAll("[data-source-field]"));
  const inputSourceWrapper = form.querySelector("[data-runtime-field='input-source']");
  const outputWrapper = form.querySelector("[data-runtime-field='output-options']");
  const outputHeading = form.querySelector("[data-runtime-field='output-heading']");
  const fileInput = form.querySelector("input[type='file']");
  const fileName = form.querySelector("[data-file-name]");

  function asBool(value) {
    return value === "true";
  }

  function setVisible(element, visible) {
    if (!element) {
      return;
    }
    element.hidden = !visible;
    element.classList.toggle("is-hidden", !visible);
    element.querySelectorAll("input, select, textarea").forEach((field) => {
      field.disabled = !visible;
    });
  }

  function currentSource() {
    if (!sourceSelect) {
      return "";
    }
    return sourceSelect.value;
  }

  function updateSourceBlocks() {
    const source = currentSource();
    sourceBlocks.forEach((block) => {
      const supportedSources = block.dataset.sourceField.split(" ");
      setVisible(block, supportedSources.includes(source));
    });
    if (fileInput) {
      const uploadSelected = source === "upload_at_execution";
      fileInput.required = uploadSelected;
      fileInput.disabled = !uploadSelected;
    }
  }

  function updateRuntimeFields() {
    const showInputSource = asBool(form.dataset.showInputSource);
    const showOutputFormat = asBool(form.dataset.showOutputFormat);

    setVisible(inputSourceWrapper, showInputSource);
    setVisible(outputWrapper, showOutputFormat);
    setVisible(outputHeading, showOutputFormat);
  }

  function updateFileName() {
    if (!fileInput || !fileName) {
      return;
    }
    const selectedFile = fileInput.files && fileInput.files[0];
    fileName.textContent = selectedFile ? selectedFile.name : "Nenhum arquivo selecionado";
  }

  if (sourceSelect) {
    sourceSelect.addEventListener("change", updateSourceBlocks);
  }

  if (fileInput) {
    fileInput.addEventListener("change", updateFileName);
  }

  form.addEventListener("submit", (event) => {
    if (currentSource() !== "upload_at_execution") {
      return;
    }
    if (fileInput && !fileInput.files.length) {
      event.preventDefault();
      fileInput.focus();
      alert("Escolha um arquivo antes de executar este agente.");
    }
  });

  updateRuntimeFields();
  updateSourceBlocks();
  updateFileName();

  // ─── Chunked upload helpers ──────────────────────────────────────────────

  async function _sendExecChunk(uploadUrl, csrf, file, uploadId, totalChunks, chunkIdx) {
    const start = chunkIdx * EXEC_CHUNK_SIZE;
    const chunk = file.slice(start, Math.min(start + EXEC_CHUNK_SIZE, file.size));
    const fd = new FormData();
    fd.append("file_chunk", chunk, file.name);
    fd.append("upload_id", uploadId);
    fd.append("chunk_index", chunkIdx);
    fd.append("total_chunks", totalChunks);
    fd.append("filename", file.name);
    try {
      const resp = await fetch(uploadUrl, {
        method: "POST",
        headers: { "X-CSRFToken": csrf },
        body: fd,
      });
      const data = await resp.json();
      if (data.erro) return { ok: false, error: data.erro };
      return { ok: true, token: data.token };
    } catch (err) {
      return { ok: false, error: "Erro de rede: " + err.message };
    }
  }

  async function _uploadExecFileChunked(uploadUrl, csrf, file, onProgress) {
    const uploadId = "exec_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
    const totalChunks = Math.max(1, Math.ceil(file.size / EXEC_CHUNK_SIZE));
    const nonLast = Array.from({ length: Math.max(0, totalChunks - 1) }, (_, i) => i);

    for (let i = 0; i < nonLast.length; i += EXEC_PARALLEL_CHUNKS) {
      const batch = nonLast.slice(i, i + EXEC_PARALLEL_CHUNKS);
      const results = await Promise.all(
        batch.map((idx) => _sendExecChunk(uploadUrl, csrf, file, uploadId, totalChunks, idx))
      );
      for (const r of results) {
        if (!r.ok) return r;
      }
      onProgress(Math.round(((i + batch.length) / totalChunks) * 90));
    }

    const lastResult = await _sendExecChunk(uploadUrl, csrf, file, uploadId, totalChunks, totalChunks - 1);
    if (lastResult.ok) onProgress(100);
    return lastResult;
  }

  // ─── AJAX form submission ────────────────────────────────────────────────

  async function _submitFormAsAjax(cardForm) {
    const csrfInput = cardForm.querySelector("[name='csrfmiddlewaretoken']");
    const csrf = csrfInput ? csrfInput.value : "";
    try {
      const resp = await fetch(cardForm.action, {
        method: "POST",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": csrf,
        },
        body: new FormData(cardForm),
        credentials: "same-origin",
      });
      let data;
      try {
        data = await resp.json();
      } catch (_) {
        data = { erro: "Resposta inesperada do servidor." };
      }
      if (data.erro) {
        _restoreCardButton(cardForm);
        alert("Erro ao iniciar execução: " + data.erro);
        return;
      }
      _startProgressTracking(cardForm, data.status_endpoint);
    } catch (err) {
      _restoreCardButton(cardForm);
      alert("Erro ao iniciar execução: " + err.message);
    }
  }

  function _restoreCardButton(cardForm) {
    const submitBtn = cardForm.querySelector("button[type='submit']");
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = "Executar";
      submitBtn.classList.remove("disabled");
    }
  }

  // ─── Progress panel ──────────────────────────────────────────────────────

  function _createProgressPanel() {
    const div = document.createElement("div");
    div.className = "agent-exec-progress";
    div.setAttribute("data-agent-progress-panel", "");
    div.dataset.statusCode = "em_processamento";
    div.innerHTML = `
      <div class="agent-exec-progress-row">
        <span data-progress-value class="agent-exec-progress-pct">0%</span>
        <div class="agent-exec-progress-track" aria-hidden="true">
          <span class="agent-exec-progress-fill" data-progress-fill style="width:0%"></span>
        </div>
        <span data-status-label class="agent-exec-progress-status"></span>
      </div>
      <details class="processing-error-panel" data-error-panel hidden>
        <summary>&#9888; Ver erro</summary>
        <div>
          <span>Detalhes do erro</span>
          <p data-error-message></p>
        </div>
      </details>
    `;
    return div;
  }

  function _applyProgressStatus(panel, payload) {
    panel.dataset.statusCode = payload.status_codigo || "";

    const q = (sel) => panel.querySelector(sel);

    const progressValue = q("[data-progress-value]");
    if (progressValue) progressValue.textContent = (payload.percentual || 0) + "%";

    const progressFill = q("[data-progress-fill]");
    if (progressFill) progressFill.style.width = (payload.percentual || 0) + "%";

    const statusLabel = q("[data-status-label]");
    if (statusLabel) statusLabel.textContent = payload.status || "";

    const stageLabel = q("[data-stage-label]");
    if (stageLabel) stageLabel.textContent = payload.etapa_atual || "Aguardando atualizacao";

    const currentDoc = q("[data-current-document]");
    const currentDocWrap = q("[data-current-document-wrap]");
    if (currentDoc && currentDocWrap) {
      const name = payload.documento_atual_nome || "";
      currentDoc.textContent = name;
      currentDocWrap.hidden = !name;
    }

    const livePanel = q(".processing-live-panel");
    const stallWarning = q("[data-stall-warning]");
    const stalled = Boolean(payload.possivel_travamento);
    if (livePanel) livePanel.classList.toggle("is-stalled", stalled);
    if (stallWarning) stallWarning.hidden = !stalled;

    const errorPanel = q("[data-error-panel]");
    const errorMessage = q("[data-error-message]");
    if (errorPanel && errorMessage) {
      const msg = payload.mensagem_erro || "";
      errorPanel.hidden = !msg;
      errorMessage.textContent = msg;
      const isAtencao = payload.status_codigo === "concluido_atencao";
      const summary = errorPanel.querySelector("summary");
      if (summary) summary.textContent = isAtencao ? "⚠ Ver atenção" : "⚠ Ver erro";
      const span = errorPanel.querySelector("span");
      if (span) span.textContent = isAtencao ? "Atenção" : "Detalhes do erro";
    }

    const downloadLink = panel._downloadBtn || null;
    if (downloadLink) {
      downloadLink.hidden = !payload.tem_arquivo_saida;
      if (payload.tem_arquivo_saida && payload.download_saida_url) {
        downloadLink.href = payload.download_saida_url;
      }
    }
  }

  async function _pollProgress(panel) {
    const endpoint = panel.dataset.statusEndpoint;
    if (!endpoint) return;
    try {
      const resp = await fetch(endpoint, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!resp.ok) return;
      const payload = await resp.json();
      _applyProgressStatus(panel, payload);
    } catch (_) {}
  }

  function _startProgressTracking(cardForm, statusEndpoint) {
    const card = cardForm.closest(".agent-card");
    if (!card) return;

    // Replace any existing progress panel
    const existing = card.querySelector("[data-agent-progress-panel]");
    if (existing) existing.remove();

    const panel = _createProgressPanel();
    panel.dataset.statusEndpoint = statusEndpoint;
    panel._downloadBtn = card.querySelector("[data-agent-exec-download]") || null;
    card.appendChild(panel);

    // Save original availability state to restore on finish
    const availability = card.querySelector(".agent-availability");
    const submitBtn = cardForm.querySelector("button[type='submit']");
    let origAvailClass = null;
    let origAvailText = null;

    if (availability) {
      const colorClasses = ["availability-verde", "availability-vermelho", "availability-cinza", "availability-amarelo"];
      origAvailClass = colorClasses.find((c) => availability.classList.contains(c)) || null;
      const availText = availability.querySelector("span:last-child");
      origAvailText = availText ? availText.textContent : null;
      availability.classList.remove(...colorClasses);
      availability.classList.add("availability-amarelo");
      if (availText) availText.textContent = "Executando...";
    }

    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Em execução";
      submitBtn.classList.add("disabled");
    }

    function onFinish() {
      if (availability && origAvailClass) {
        const colorClasses = ["availability-verde", "availability-vermelho", "availability-cinza", "availability-amarelo"];
        availability.classList.remove(...colorClasses);
        availability.classList.add(origAvailClass);
        const availText = availability.querySelector("span:last-child");
        if (availText && origAvailText !== null) availText.textContent = origAvailText;
      }
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "Executar";
        submitBtn.classList.remove("disabled");
      }
    }

    // Initial poll
    _pollProgress(panel);

    const intervalId = setInterval(() => {
      if (!IN_PROGRESS_STATUSES.has(panel.dataset.statusCode)) {
        clearInterval(intervalId);
        onFinish();
        return;
      }
      _pollProgress(panel);
    }, POLL_INTERVAL_MS);
  }

  // ─── Confirmation modal ──────────────────────────────────────────────────

  function _openExecModal(cardForm) {
    const modal = document.getElementById("modal-confirmar-execucao");
    if (!modal) {
      cardForm.requestSubmit();
      return;
    }
    const setText = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val || "—";
    };
    setText("modal-exec-nome-agente", cardForm.dataset.agentNome);
    setText("modal-exec-integracao-ia", cardForm.dataset.agentIntegracaoIa);
    const tipoEntrada = cardForm.dataset.agentTipoEntrada || "";
    const nomeInteg = cardForm.dataset.agentNomeIntegracao || "";
    setText("modal-exec-origem", nomeInteg ? tipoEntrada + " · " + nomeInteg : tipoEntrada);
    setText("modal-exec-formato-saida", cardForm.dataset.agentFormatoSaida);
    _modalPendingForm = cardForm;
    modal.style.display = "flex";
    const confirmBtn = document.getElementById("modal-exec-confirmar");
    if (confirmBtn) confirmBtn.focus();
  }

  function _closeExecModal() {
    const modal = document.getElementById("modal-confirmar-execucao");
    if (modal) modal.style.display = "none";
    _modalPendingForm = null;
  }

  function setupExecModal() {
    const modal = document.getElementById("modal-confirmar-execucao");
    if (!modal) return;
    const confirmBtn = document.getElementById("modal-exec-confirmar");
    const cancelBtn = document.getElementById("modal-exec-cancelar");
    if (confirmBtn) {
      confirmBtn.addEventListener("click", () => {
        const pendingForm = _modalPendingForm;
        _closeExecModal();
        if (pendingForm) pendingForm.requestSubmit();
      });
    }
    if (cancelBtn) {
      cancelBtn.addEventListener("click", _closeExecModal);
    }
    modal.addEventListener("click", (e) => {
      if (e.target === modal) _closeExecModal();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && modal.style.display !== "none") _closeExecModal();
    });
  }

  // ─── Agent card forms ────────────────────────────────────────────────────

  function setupAgentCardUploads() {
    document.querySelectorAll("[data-agent-card-form]").forEach((cardForm) => {
      const cardFileInput = cardForm.querySelector("[data-agent-card-file]");
      const submitButton = cardForm.querySelector("button[type='submit']");

      // Intercept the Executar button to open the confirmation modal
      if (submitButton) {
        submitButton.addEventListener("click", (event) => {
          event.preventDefault();
          _openExecModal(cardForm);
        });
      }

      if (!cardFileInput) {
        // Simple form: submit via AJAX on confirm
        cardForm.addEventListener("submit", async (event) => {
          event.preventDefault();
          if (submitButton) {
            submitButton.disabled = true;
            submitButton.textContent = "Iniciando...";
            submitButton.classList.add("disabled");
          }
          await _submitFormAsAjax(cardForm);
        });
        return;
      }

      // Upload form
      cardFileInput.addEventListener("change", () => {
        const selectedFile = cardFileInput.files && cardFileInput.files[0];
        cardForm.classList.toggle("has-file", Boolean(selectedFile));
      });

      cardForm.addEventListener("submit", async (event) => {
        if (!cardFileInput.files || !cardFileInput.files.length) {
          event.preventDefault();
          cardForm.classList.add("needs-file");
          cardFileInput.click();
          return;
        }

        event.preventDefault();

        const file = cardFileInput.files[0];
        const executarUrl = cardForm.action;
        const uploadUrl = executarUrl.replace(/\/executar\/$/, "/upload-execucao/");
        const csrfInput = cardForm.querySelector("[name='csrfmiddlewaretoken']");
        const csrf = csrfInput ? csrfInput.value : "";

        if (submitButton) {
          submitButton.disabled = true;
          submitButton.textContent = "Enviando...";
          submitButton.classList.add("disabled");
        }

        try {
          const result = await _uploadExecFileChunked(uploadUrl, csrf, file, (pct) => {
            if (submitButton) submitButton.textContent = "Enviando " + pct + "%";
          });

          if (!result.ok) {
            _restoreCardButton(cardForm);
            alert("Erro ao enviar arquivo: " + result.error);
            return;
          }

          const tokenInput = document.createElement("input");
          tokenInput.type = "hidden";
          tokenInput.name = "arquivo_execucao_token";
          tokenInput.value = result.token;
          cardForm.appendChild(tokenInput);

          cardFileInput.disabled = true;

          if (submitButton) {
            submitButton.textContent = "Iniciando...";
          }
          await _submitFormAsAjax(cardForm);
        } catch (err) {
          _restoreCardButton(cardForm);
          alert("Erro ao enviar arquivo: " + err.message);
        }
      });

      if (submitButton) {
        submitButton.addEventListener("mouseenter", () => {
          cardForm.classList.remove("needs-file");
        });
      }
    });
  }
})();
