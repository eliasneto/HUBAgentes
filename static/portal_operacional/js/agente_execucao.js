(function () {
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

      cardForm.addEventListener("submit", () => {
        if (cardFileInput && (!cardFileInput.files || !cardFileInput.files.length)) {
          return;
        }
        markCardExecuting();
      });

      if (!cardFileInput) {
        return;
      }

      cardFileInput.addEventListener("change", () => {
        const selectedFile = cardFileInput.files && cardFileInput.files[0];
        cardForm.classList.toggle("has-file", Boolean(selectedFile));
      });

      cardForm.addEventListener("submit", (event) => {
        if (cardFileInput.files && cardFileInput.files.length > 0) {
          return;
        }

        event.preventDefault();
        cardForm.classList.add("needs-file");
        cardFileInput.click();
      });

      if (submitButton) {
        submitButton.addEventListener("mouseenter", () => {
          cardForm.classList.remove("needs-file");
        });
      }
    });
  }
})();
