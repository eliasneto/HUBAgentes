document.addEventListener("DOMContentLoaded", function () {
  const cards = Array.from(document.querySelectorAll("[data-processing-card]"));
  if (!cards.length) {
    return;
  }

  const inProgressStatuses = new Set(["criado", "em_fila", "em_processamento"]);

  function textOrDefault(value, fallback) {
    if (value === null || value === undefined || value === "") {
      return fallback;
    }
    return value;
  }

  function updateText(card, selector, value) {
    const element = card.querySelector(selector);
    if (element) {
      element.textContent = value;
    }
  }

  function updateSummary(payload) {
    if (!payload.resumo) {
      return;
    }

    const fields = {
      "[data-summary-total]": payload.resumo.total,
      "[data-summary-em-andamento]": payload.resumo.em_andamento,
      "[data-summary-concluidos]": payload.resumo.concluidos,
      "[data-summary-com-erro]": payload.resumo.com_erro,
    };

    Object.entries(fields).forEach(function ([selector, value]) {
      const element = document.querySelector(selector);
      if (element && value !== undefined) {
        element.textContent = value;
      }
    });
  }

  function applyStatus(card, payload) {
    card.dataset.statusCode = payload.status_codigo || "";

    const statusLabel = card.querySelector("[data-status-label]");
    if (statusLabel) {
      statusLabel.textContent = payload.status || statusLabel.textContent;
    }

    const progressValue = card.querySelector("[data-progress-value]");
    if (progressValue) {
      progressValue.textContent = `${payload.percentual}%`;
    }

    const progressFill = card.querySelector("[data-progress-fill]");
    if (progressFill) {
      progressFill.style.width = `${payload.percentual}%`;
    }

    updateText(card, "[data-output-format]", payload.formato_saida || "");
    updateText(card, "[data-meta-origem]", payload.origem || "Nao informada");
    updateText(
      card,
      "[data-meta-documentos]",
      `${payload.total_processados} de ${payload.total_documentos}`
    );
    updateText(
      card,
      "[data-meta-tokens]",
      textOrDefault(payload.total_tokens, "Nao informado")
    );
    updateText(
      card,
      "[data-meta-duracao]",
      payload.duracao_minutos === null || payload.duracao_minutos === undefined
        ? "Nao informada"
        : `${payload.duracao_minutos} min`
    );
    updateText(
      card,
      "[data-meta-inicio]",
      textOrDefault(payload.iniciado_em, "Nao informado")
    );
    updateText(
      card,
      "[data-meta-fim]",
      textOrDefault(payload.finalizado_em, "Em aberto")
    );

    const stageLabel = card.querySelector("[data-stage-label]");
    if (stageLabel) {
      stageLabel.textContent = payload.etapa_atual || "Aguardando atualizacao";
    }

    const currentDocument = card.querySelector("[data-current-document]");
    const currentDocumentWrap = card.querySelector(
      "[data-current-document-wrap]"
    );
    if (currentDocument && currentDocumentWrap) {
      const currentName = payload.documento_atual_nome || "";
      currentDocument.textContent = currentName;
      currentDocumentWrap.hidden = !currentName;
    }

    const livePanel = card.querySelector(".processing-live-panel");
    const stallWarning = card.querySelector("[data-stall-warning]");
    const stalled = Boolean(payload.possivel_travamento);
    if (livePanel) {
      livePanel.classList.toggle("is-stalled", stalled);
    }
    if (stallWarning) {
      stallWarning.hidden = !stalled;
    }

    const downloadLink = card.querySelector("[data-output-download]");
    if (downloadLink) {
      downloadLink.hidden = !payload.tem_arquivo_saida;
      if (payload.tem_arquivo_saida && payload.download_saida_url) {
        downloadLink.href = payload.download_saida_url;
      }
    }

    const unavailableOutput = card.querySelector("[data-output-unavailable]");
    if (unavailableOutput) {
      unavailableOutput.hidden = Boolean(payload.tem_arquivo_saida);
    }

    const errorPanel = card.querySelector("[data-error-panel]");
    const errorMessage = card.querySelector("[data-error-message]");
    if (errorPanel && errorMessage) {
      const message = payload.mensagem_erro || "";
      errorPanel.hidden = !message;
      errorMessage.textContent = message;
      // Atualiza o texto do summary conforme o tipo de situação
      const isAtencao = payload.status_codigo === "concluido_atencao";
      const summary = errorPanel.querySelector("summary");
      if (summary) {
        summary.textContent = isAtencao ? "⚠ Ver atenção" : "⚠ Ver erro";
      }
      const errorSpan = errorPanel.querySelector("span");
      if (errorSpan) {
        errorSpan.textContent = isAtencao ? "Atenção" : "Detalhes do erro";
      }
    }

    updateSummary(payload);
  }

  async function refreshCard(card) {
    const endpoint = card.dataset.statusEndpoint;
    if (!endpoint) {
      return;
    }

    const response = await fetch(endpoint, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    });
    if (!response.ok) {
      throw new Error(`Falha ao consultar status ${response.status}`);
    }

    const payload = await response.json();
    applyStatus(card, payload);
  }

  async function pollCards() {
    const activeCards = cards.filter(function (card) {
      return inProgressStatuses.has(card.dataset.statusCode || "");
    });
    if (!activeCards.length) {
      return;
    }

    await Promise.all(
      activeCards.map(async function (card) {
        try {
          await refreshCard(card);
        } catch (_error) {
          return null;
        }
        return null;
      })
    );
  }

  pollCards();
  window.setInterval(pollCards, 8000);
});
