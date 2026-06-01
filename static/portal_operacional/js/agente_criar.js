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
  initCombinationHint(form);
  updateSourceBlocks();
});

var COMBINATION_HINTS = {
  "individual|uma_por_entrada|zip_se_multiplos": {
    titulo: "Um arquivo de entrada, um arquivo de saida",
    descricao: "Cada arquivo e processado separadamente pela IA e gera uma saida propria. Quando mais de um arquivo for enviado, as saidas sao compactadas em ZIP automaticamente.",
    obs: "",
  },
  "individual|uma_por_entrada|sempre_zip": {
    titulo: "Um arquivo de entrada, um arquivo de saida (sempre ZIP)",
    descricao: "Cada arquivo e processado separadamente pela IA e gera uma saida propria. As saidas sao sempre entregues dentro de um ZIP, mesmo quando ha apenas um arquivo.",
    obs: "",
  },
  "grupo_unico|uma_saida_final|arquivo_unico": {
    titulo: "Varios arquivos de entrada, uma saida consolidada",
    descricao: "Todos os arquivos sao enviados juntos para a IA em uma unica chamada. A IA recebe tudo de uma vez e gera um unico arquivo de saida.",
    obs: "A juncao das informacoes e responsabilidade do prompt de IA.",
  },
  "grupo_unico|uma_saida_final|sempre_zip": {
    titulo: "Varios arquivos de entrada, uma saida consolidada em ZIP",
    descricao: "Todos os arquivos sao enviados juntos para a IA em uma unica chamada. A IA recebe tudo de uma vez e gera um unico arquivo de saida entregue dentro de um ZIP.",
    obs: "A juncao das informacoes e responsabilidade do prompt de IA.",
  },
  "lote_por_pasta|uma_por_entrada|zip_se_multiplos": {
    titulo: "Lote por pasta, uma saida por arquivo",
    descricao: "Os arquivos sao processados pasta por pasta. Cada arquivo gera uma saida separada. Quando ha mais de um arquivo na pasta, as saidas sao compactadas em ZIP.",
    obs: "",
  },
  "lote_por_pasta|uma_por_entrada|sempre_zip": {
    titulo: "Lote por pasta, uma saida por arquivo (sempre ZIP)",
    descricao: "Os arquivos sao processados pasta por pasta. Cada arquivo gera uma saida separada, sempre entregue dentro de um ZIP.",
    obs: "",
  },
  "lote_por_pasta|uma_saida_final|arquivo_unico": {
    titulo: "Lote por pasta, uma saida consolidada por lote",
    descricao: "Os arquivos sao processados pasta por pasta. Todos os arquivos de cada pasta sao enviados juntos para a IA em uma unica chamada, que gera uma saida unica por lote.",
    obs: "A juncao das informacoes e responsabilidade do prompt de IA.",
  },
  "lote_por_pasta|uma_saida_final|sempre_zip": {
    titulo: "Lote por pasta, uma saida consolidada por lote em ZIP",
    descricao: "Os arquivos sao processados pasta por pasta. Todos os arquivos de cada pasta sao enviados juntos para a IA, que gera uma saida unica por lote entregue em ZIP.",
    obs: "A juncao das informacoes e responsabilidade do prompt de IA.",
  },
  "lote_por_pasta|uma_por_grupo|arquivo_unico": {
    titulo: "Lote por pasta, uma saida por grupo (arquivo unico)",
    descricao: "Os arquivos de cada pasta sao enviados juntos para a IA em uma unica chamada, que gera uma saida consolidada por grupo. Cada grupo gera seu proprio arquivo de saida.",
    obs: "A juncao das informacoes dentro do grupo e responsabilidade do prompt de IA.",
  },
  "lote_por_pasta|uma_por_grupo|zip_se_multiplos": {
    titulo: "Lote por pasta, uma saida por grupo",
    descricao: "Os arquivos de cada pasta sao enviados juntos para a IA em uma unica chamada, que gera uma saida consolidada por grupo. Quando ha mais de um grupo, as saidas sao compactadas em ZIP.",
    obs: "A juncao das informacoes dentro do grupo e responsabilidade do prompt de IA.",
  },
  "lote_por_pasta|uma_por_grupo|sempre_zip": {
    titulo: "Lote por pasta, uma saida por grupo (sempre ZIP)",
    descricao: "Os arquivos de cada pasta sao enviados juntos para a IA em uma unica chamada, que gera uma saida consolidada por grupo. As saidas sao sempre entregues dentro de um ZIP, mesmo com apenas um grupo.",
    obs: "A juncao das informacoes dentro do grupo e responsabilidade do prompt de IA.",
  },
};

function initCombinationHint(form) {
  var hintBox = form.querySelector("[data-combination-hint]");
  if (!hintBox) {
    return;
  }

  var execSelect = form.querySelector('[name="document_execution_mode"]');
  var assemblySelect = form.querySelector('[name="output_assembly_mode"]');
  var packagingSelect = form.querySelector('[name="output_packaging_mode"]');

  if (!execSelect || !assemblySelect || !packagingSelect) {
    return;
  }

  var titleEl = hintBox.querySelector("[data-combination-hint-title]");
  var descEl = hintBox.querySelector("[data-combination-hint-desc]");
  var obsEl = hintBox.querySelector("[data-combination-hint-obs]");

  function updateHint() {
    var key = execSelect.value + "|" + assemblySelect.value + "|" + packagingSelect.value;
    var hint = COMBINATION_HINTS[key];

    if (!hint) {
      hintBox.hidden = true;
      return;
    }

    titleEl.textContent = hint.titulo;
    descEl.textContent = hint.descricao;
    obsEl.textContent = hint.obs ? "Observacao: " + hint.obs : "";
    obsEl.hidden = !hint.obs;
    hintBox.hidden = false;
  }

  execSelect.addEventListener("change", updateHint);
  assemblySelect.addEventListener("change", updateHint);
  packagingSelect.addEventListener("change", updateHint);
  updateHint();
}

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
