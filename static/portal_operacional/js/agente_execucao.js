(function () {
  // NPM (OpenResty) rejeita corpos > ~8,8 KB. Usamos chunks de 7 KB (mesmo
  // limite validado para upload local) para contornar o limite do proxy.
  const EXEC_CHUNK_SIZE = 7 * 1024;
  const EXEC_PARALLEL_CHUNKS = 4;

  const form = document.querySelector("[data-execution-form]");
  setupAgentCardUploads();
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

  function setupAgentCardUploads() {
    document.querySelectorAll("[data-agent-card-form]").forEach((cardForm) => {
      const cardFileInput = cardForm.querySelector("[data-agent-card-file]");
      const submitButton = cardForm.querySelector("button[type='submit']");

      function markCardExecuting() {
        const card = cardForm.closest(".agent-card");
        if (!card) {
          return;
        }
        const availability = card.querySelector(".agent-availability");
        if (availability) {
          availability.classList.remove(
            "availability-verde",
            "availability-vermelho",
            "availability-cinza"
          );
          availability.classList.add("availability-amarelo");
          const availabilityText = availability.querySelector("span:last-child");
          if (availabilityText) {
            availabilityText.textContent = "Agente em execucao. Aguarde atualizacao.";
          }
        }
        if (submitButton) {
          submitButton.disabled = true;
          submitButton.textContent = "Executando...";
          submitButton.classList.add("disabled");
        }
      }

      if (!cardFileInput) {
        cardForm.addEventListener("submit", markCardExecuting);
        return;
      }

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
            if (submitButton) {
              submitButton.disabled = false;
              submitButton.textContent = "Executar";
              submitButton.classList.remove("disabled");
            }
            alert("Erro ao enviar arquivo: " + result.error);
            return;
          }

          const tokenInput = document.createElement("input");
          tokenInput.type = "hidden";
          tokenInput.name = "arquivo_execucao_token";
          tokenInput.value = result.token;
          cardForm.appendChild(tokenInput);

          cardFileInput.disabled = true;

          markCardExecuting();
          cardForm.submit();
        } catch (err) {
          if (submitButton) {
            submitButton.disabled = false;
            submitButton.textContent = "Executar";
            submitButton.classList.remove("disabled");
          }
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
