document.addEventListener("DOMContentLoaded", function () {
  const form = document.querySelector("[data-agent-builder-form]");
  if (!form) {
    return;
  }

  const sourceSelect = form.querySelector('[name="default_input_source_type"]');
  const sourceBlocks = Array.from(form.querySelectorAll("[data-builder-source]"));
  const docConfigBlocks = Array.from(
    form.querySelectorAll("[data-builder-doc-config]")
  );
  const uploadToggle = form.querySelector(
    '[name="permitir_upload_na_execucao"]'
  );

  function setVisible(element, visible, preserveSubmission) {
    element.hidden = !visible;
    element.querySelectorAll("input, select, textarea").forEach(function (field) {
      if (field.type === "checkbox") {
        if (!visible) {
          field.checked = false;
        }
        field.disabled = false;
        return;
      }
      field.disabled = !visible && !preserveSubmission;
    });
  }

  function updateSourceBlocks() {
    const selectedSource = sourceSelect ? sourceSelect.value : "";
    sourceBlocks.forEach(function (block) {
      const supportedSources = block.dataset.builderSource.split(" ");
      setVisible(block, supportedSources.includes(selectedSource));
    });

    const hasDocumentFlow =
      selectedSource !== "none" || Boolean(uploadToggle && uploadToggle.checked);
    docConfigBlocks.forEach(function (block) {
      setVisible(block, hasDocumentFlow, true);
    });
  }

  if (sourceSelect) {
    sourceSelect.addEventListener("change", updateSourceBlocks);
  }

  if (uploadToggle) {
    uploadToggle.addEventListener("change", updateSourceBlocks);
  }

  initPromptParameters(form);
  updateSourceBlocks();
});

function initPromptParameters(form) {
  const panel = form.querySelector("[data-prompt-parameters]");
  if (!panel) {
    return;
  }

  const hiddenInput = panel.querySelector('[name="prompt_parameters"]');
  const list = panel.querySelector("[data-prompt-parameters-list]");
  const emptyState = panel.querySelector("[data-prompt-parameters-empty]");
  const addButton = panel.querySelector("[data-prompt-parameter-add]");
  if (!hiddenInput || !list || !addButton) {
    return;
  }

  function parseInitialParameters() {
    try {
      const parsedValue = JSON.parse(hiddenInput.value || "[]");
      return Array.isArray(parsedValue) ? parsedValue : [];
    } catch (error) {
      return [];
    }
  }

  function buildVariableName(value, currentRow) {
    const baseName =
      (value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "_")
        .replace(/^_+|_+$/g, "") || "parametro";

    const usedNames = Array.from(
      list.querySelectorAll("[data-prompt-parameter-variable]")
    )
      .filter(function (input) {
        return !currentRow || !currentRow.contains(input);
      })
      .map(function (input) {
        return input.value;
      });

    let variableName = baseName;
    let counter = 2;
    while (usedNames.includes(variableName)) {
      variableName = baseName + "_" + counter;
      counter += 1;
    }
    return variableName;
  }

  function collectRows() {
    return Array.from(list.querySelectorAll("[data-prompt-parameter-row]"))
      .map(function (row) {
        return {
          campo: row.querySelector("[data-prompt-parameter-campo]").value.trim(),
          rotulo: row.querySelector("[data-prompt-parameter-rotulo]").value.trim(),
          variavel: row
            .querySelector("[data-prompt-parameter-variable]")
            .value.trim(),
        };
      })
      .filter(function (parameter) {
        return parameter.campo || parameter.rotulo;
      });
  }

  function syncHiddenInput() {
    hiddenInput.value = JSON.stringify(collectRows());
    if (emptyState) {
      emptyState.hidden = list.children.length > 0;
    }
  }

  function refreshVariableNames() {
    Array.from(list.querySelectorAll("[data-prompt-parameter-row]")).forEach(
      function (row) {
        const fieldInput = row.querySelector("[data-prompt-parameter-campo]");
        const labelInput = row.querySelector("[data-prompt-parameter-rotulo]");
        const variableInput = row.querySelector("[data-prompt-parameter-variable]");
        variableInput.value = buildVariableName(
          fieldInput.value || labelInput.value,
          row
        );
      }
    );
    syncHiddenInput();
  }

  function createRow(parameter) {
    const row = document.createElement("div");
    row.className = "prompt-parameter-row";
    row.dataset.promptParameterRow = "true";

    const fieldLabel = document.createElement("label");
    fieldLabel.textContent = "Campo";
    const fieldInput = document.createElement("input");
    fieldInput.type = "text";
    fieldInput.value = parameter.campo || "";
    fieldInput.placeholder = "Ex.: pergunta sobre habilitacao";
    fieldInput.dataset.promptParameterCampo = "true";
    fieldLabel.appendChild(fieldInput);

    const visibleLabel = document.createElement("label");
    visibleLabel.textContent = "Rotulo";
    const visibleInput = document.createElement("input");
    visibleInput.type = "text";
    visibleInput.value = parameter.rotulo || "";
    visibleInput.placeholder = "Ex.: Pergunta de habilitacao";
    visibleInput.dataset.promptParameterRotulo = "true";
    visibleLabel.appendChild(visibleInput);

    const variableLabel = document.createElement("label");
    variableLabel.textContent = "Variavel";
    const variableInput = document.createElement("input");
    variableInput.type = "text";
    variableInput.value = parameter.variavel || "";
    variableInput.readOnly = true;
    variableInput.dataset.promptParameterVariable = "true";
    variableLabel.appendChild(variableInput);

    const removeButton = document.createElement("button");
    removeButton.className = "prompt-parameter-remove";
    removeButton.type = "button";
    removeButton.setAttribute("aria-label", "Excluir parametro");
    removeButton.innerHTML =
      '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
      '<path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm-2 6h10l-.8 12H7.8L7 9Zm3 2v8h2v-8h-2Zm4 0v8h2v-8h-2Z"></path>' +
      "</svg>";

    [fieldInput, visibleInput].forEach(function (input) {
      input.addEventListener("input", refreshVariableNames);
    });

    removeButton.addEventListener("click", function () {
      row.remove();
      refreshVariableNames();
    });

    row.appendChild(fieldLabel);
    row.appendChild(visibleLabel);
    row.appendChild(variableLabel);
    row.appendChild(removeButton);
    list.appendChild(row);
    refreshVariableNames();
  }

  parseInitialParameters().forEach(createRow);
  addButton.addEventListener("click", function () {
    createRow({});
  });
  syncHiddenInput();
}
