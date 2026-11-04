/* Growchatbot — Stitch-derived facts-only chat UI.
 *
 * Talks to the FastAPI surface:
 *   POST /query            → answer envelope
 *   GET  /health           → index + provider status
 *   GET  /artifacts/{id}   → six stage artifacts
 *
 * Client state is intentionally in-memory only: no cookies, no localStorage,
 * no query analytics. Raw PII is refused server-side and never rendered back.
 */

(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const elements = {
    sidebar: $("#sidebar"),
    sidebarClose: $("#sidebarClose"),
    menuBtn: $("#menuBtn"),
    scrim: $("#scrim"),
    newChatBtn: $("#newChatBtn"),
    welcome: $("#welcome"),
    messages: $("#messages"),
    queryForm: $("#queryForm"),
    queryInput: $("#queryInput"),
    sendBtn: $("#sendBtn"),
    traceToggle: $("#traceToggle"),
    traceDrawer: $("#traceDrawer"),
    traceClose: $("#traceClose"),
    traceMeta: $("#traceMeta"),
    traceTabs: $("#traceTabs"),
    traceBody: $("#traceBody"),
    toast: $("#toast"),
    statusDot: $("#statusDot"),
    statusText: $("#statusText"),
    indexCount: $("#indexCount"),
    retrieverMode: $("#retrieverMode"),
    generationMode: $("#generationMode"),
    chatScroll: $("#chatScroll"),
  };

  const ARTIFACTS = [
    { file: "00_request.json", label: "00 Request", short: "Request" },
    { file: "01_guardrails.json", label: "01 Guardrails", short: "Guardrails" },
    { file: "02_retrieval.json", label: "02 Retrieval", short: "Retrieval" },
    { file: "03_prompt.txt", label: "03 Prompt", short: "Prompt" },
    { file: "04_completion.json", label: "04 Completion", short: "Completion" },
    { file: "05_response.json", label: "05 Response", short: "Response" },
  ];

  const STATUS = {
    answered: { label: "Answered", tone: "is-ok", card: "" },
    refused_pii: {
      label: "Private data removed",
      tone: "is-warn",
      card: "is-refusal",
    },
    refused_advice: {
      label: "No investment advice",
      tone: "is-warn",
      card: "is-refusal",
    },
    refused_performance: {
      label: "No performance calls",
      tone: "is-warn",
      card: "is-refusal",
    },
    insufficient_context: {
      label: "Not in the sources",
      tone: "is-warn",
      card: "is-refusal",
    },
    error: {
      label: "Couldn't validate",
      tone: "is-error",
      card: "is-error",
    },
  };

  const state = {
    busy: false,
    requestId: 0,
    latestQueryId: null,
    latestStatus: null,
    activeTraceQueryId: null,
    activeArtifact: null,
    artifacts: new Map(),
    toastTimer: null,
    lastFocused: null,
  };

  /* ── Formatting helpers ─────────────────────────────────────── */

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => {
      switch (character) {
        case "&":
          return "&amp;";
        case "<":
          return "&lt;";
        case ">":
          return "&gt;";
        case '"':
          return "&quot;";
        default:
          return "&#39;";
      }
    });
  }

  function icon(name, className = "icon") {
    return `<svg class="${className}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
  }

  function sourceTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      timeZone: "UTC",
      timeZoneName: "short",
    });
  }

  function clockTime(date = new Date()) {
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function humanize(value) {
    return String(value ?? "")
      .replace(/[_-]+/g, " ")
      .trim()
      .replace(/^\w/, (character) => character.toUpperCase());
  }

  function shortQueryId(queryId) {
    if (!queryId) return "No query yet";
    if (queryId.length <= 22) return queryId;
    return `${queryId.slice(0, 13)}…${queryId.slice(-6)}`;
  }

  function statusFor(status) {
    return (
      STATUS[status] || {
        label: humanize(status || "Unknown"),
        tone: "is-warn",
        card: "is-refusal",
      }
    );
  }

  function providerLabel(provider) {
    if (!provider) return "—";
    if (provider === "offline-extractive") return "Offline";
    if (provider === "groq") return "Groq";
    return humanize(provider);
  }

  function retrieverLabel(mode) {
    if (mode === "lexical-bm25") return "BM25";
    if (mode === "vector") return "Vector";
    return mode ? humanize(mode) : "—";
  }

  function scrollToLatest() {
    elements.chatScroll.scrollTop = elements.chatScroll.scrollHeight;
  }

  function showToast(message) {
    elements.toast.textContent = message;
    elements.toast.classList.add("is-visible");
    if (state.toastTimer) window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => {
      elements.toast.classList.remove("is-visible");
    }, 2400);
  }

  /* ── Health ─────────────────────────────────────────────────── */

  async function loadHealth() {
    try {
      const response = await fetch("/health", {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error(`Health returned ${response.status}`);
      const health = await response.json();
      const ready = health.status === "ok";

      elements.statusDot.classList.toggle("is-ok", ready);
      elements.statusDot.classList.toggle("is-error", !ready);
      elements.statusText.textContent = ready
        ? `Index ready · ${(health.index_count ?? 0).toLocaleString()} official passages`
        : "Index not ready";
      elements.indexCount.textContent = Number.isFinite(Number(health.index_count))
        ? Number(health.index_count).toLocaleString()
        : "—";
      elements.retrieverMode.textContent = retrieverLabel(health.retriever);
      elements.retrieverMode.title = health.retriever || "";
      elements.generationMode.textContent = providerLabel(health.generator_provider);
      elements.generationMode.title = health.generator_provider || "";
    } catch (error) {
      elements.statusDot.classList.remove("is-ok");
      elements.statusDot.classList.add("is-error");
      elements.statusText.textContent = "API unavailable";
      elements.indexCount.textContent = "—";
      elements.retrieverMode.textContent = "—";
      elements.generationMode.textContent = "—";
      console.warn("Health check failed", error);
    }
  }

  /* ── Conversation rendering ─────────────────────────────────── */

  function appendTurn(html) {
    elements.welcome.hidden = true;
    const wrapper = document.createElement("article");
    wrapper.innerHTML = html;
    const turn = wrapper.firstElementChild;
    elements.messages.append(turn);
    scrollToLatest();
    return turn;
  }

  function renderUserTurn(query) {
    const turn = document.createElement("article");
    turn.className = "turn turn-user";
    turn.innerHTML = `
      <div class="user-bubble"></div>
      <time class="turn-time">${escapeHtml(clockTime())}</time>
    `;
    $(".user-bubble", turn).textContent = query;
    elements.welcome.hidden = true;
    elements.messages.append(turn);
    scrollToLatest();
    return turn;
  }

  function renderPendingTurn() {
    return appendTurn(`
      <div class="turn turn-assistant">
        <header class="assistant-head">
          <span class="ai-mark" aria-hidden="true"><span class="ai-dot"></span></span>
          <span class="assistant-id">
            <strong>Growchatbot</strong>
            <span>Official sources · facts only</span>
          </span>
          <span class="status-badge" id="pendingBadge">Checking sources</span>
        </header>
        <div class="assistant-card">
          <div class="typing" role="status" aria-label="Retrieving and validating">
            <span></span><span></span><span></span>
          </div>
        </div>
      </div>
    `);
  }

  function citationHtml(citation) {
    if (!citation || !citation.url) return "";
    const title = citation.title || citation.url;
    return `
      <a class="citation-card" href="${escapeHtml(citation.url)}"
         target="_blank" rel="noopener noreferrer">
        <span class="citation-icon">${icon("external")}</span>
        <span class="citation-copy">
          <span class="citation-label">Official source</span>
          <strong>${escapeHtml(title)}</strong>
          <span class="citation-url">${escapeHtml(citation.url)}</span>
        </span>
        ${icon("external", "icon citation-arrow")}
      </a>
    `;
  }

  function metaChips(payload, status) {
    const chips = [];
    if (status === "answered" && payload.validation) {
      const count = payload.validation.sentence_count;
      if (Number.isFinite(Number(count))) {
        chips.push(`${escapeHtml(count)} sentence${Number(count) === 1 ? "" : "s"}`);
      }
      chips.push("1 citation");
      const checks = payload.validation.checks || {};
      const passed = Object.values(checks).every(Boolean);
      chips.push(passed ? "Validation passed" : "Validation partial");
    } else if (payload.refusal_reason) {
      chips.push(`Reason: ${escapeHtml(humanize(payload.refusal_reason))}`);
      chips.push("Stopped before generation");
    }
    if (payload.query_id) {
      chips.push(`ID ${escapeHtml(shortQueryId(payload.query_id))}`);
    }
    if (!chips.length) return "";
    return `
      <div class="answer-meta">
        ${chips
          .map(
            (chip, index) =>
              `<span class="meta-chip${index === 0 && status === "answered" ? " is-ok" : ""}">${chip}</span>`,
          )
          .join("")}
      </div>
    `;
  }

  function renderAnswerTurn(payload) {
    const status = statusFor(payload.status);
    const answered = payload.status === "answered";
    const lastUpdated = answered && payload.last_updated
      ? `<p class="last-updated">
           ${icon("clock")}
           <span>Last updated from sources: <time datetime="${escapeHtml(payload.last_updated)}">${escapeHtml(sourceTime(payload.last_updated))}</time></span>
         </p>`
      : "";

    return appendTurn(`
      <div class="turn turn-assistant">
        <header class="assistant-head">
          <span class="ai-mark" aria-hidden="true"><span class="ai-dot"></span></span>
          <span class="assistant-id">
            <strong>Growchatbot</strong>
            <span>Official sources · facts only</span>
          </span>
          <span class="status-badge ${status.tone}">${escapeHtml(status.label)}</span>
        </header>
        <div class="assistant-card ${status.card}">
          <p class="answer-text">${escapeHtml(payload.answer || "No answer was returned.")}</p>
          ${citationHtml(payload.citation)}
          ${lastUpdated}
          ${metaChips(payload, payload.status)}
        </div>
        <div class="turn-toolbar">
          <button class="tool-btn" type="button" data-action="copy" data-query-id="${escapeHtml(payload.query_id || "")}">
            ${icon("copy")}<span>Copy</span>
          </button>
          <button class="tool-btn" type="button" data-action="trace" data-query-id="${escapeHtml(payload.query_id || "")}">
            ${icon("trace")}<span>RAG trace</span>
          </button>
        </div>
      </div>
    `);
  }

  function renderErrorTurn(message) {
    return appendTurn(`
      <div class="turn turn-assistant">
        <header class="assistant-head">
          <span class="ai-mark" aria-hidden="true"><span class="ai-dot"></span></span>
          <span class="assistant-id">
            <strong>Growchatbot</strong>
            <span>Official sources · facts only</span>
          </span>
          <span class="status-badge is-error">Connection error</span>
        </header>
        <div class="assistant-card is-error">
          <p class="answer-text">${escapeHtml(message)}</p>
          <div class="answer-meta">
            <span class="meta-chip">No personal data was sent or stored</span>
          </div>
        </div>
        <div class="turn-toolbar">
          <button class="tool-btn" type="button" data-action="retry">
            ${icon("arrow")}<span>Try again</span>
          </button>
        </div>
      </div>
    `);
  }

  /* ── Query flow ─────────────────────────────────────────────── */

  function setBusy(busy) {
    state.busy = busy;
    elements.messages.setAttribute("aria-busy", String(busy));
    elements.queryForm.classList.toggle("is-busy", busy);
    elements.sendBtn.disabled = busy || !elements.queryInput.value.trim();
  }

  function autoGrow() {
    const input = elements.queryInput;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 156)}px`;
    elements.sendBtn.disabled = state.busy || !input.value.trim();
  }

  function errorMessage(payload, status) {
    const detail = payload && payload.detail;
    if (detail && typeof detail === "object") {
      return detail.message || detail.error || `Request failed (${status}).`;
    }
    if (typeof detail === "string" && detail.trim()) return detail;
    return `Request failed (${status}). Please try again.`;
  }

  async function submitQuery(rawQuery) {
    const query = String(rawQuery || "").trim();
    if (!query || state.busy) return;

    renderUserTurn(query);
    elements.queryInput.value = "";
    autoGrow();
    setBusy(true);

    const pending = renderPendingTurn();
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 65000);
    const requestId = ++state.requestId;

    try {
      const response = await fetch("/query", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({ query }),
        signal: controller.signal,
      });

      let payload = null;
      try {
        payload = await response.json();
      } catch (_error) {
        payload = null;
      }

      if (requestId !== state.requestId) {
        pending.remove();
        return;
      }

      if (!response.ok) {
        throw new Error(errorMessage(payload, response.status));
      }

      pending.remove();
      const turn = renderAnswerTurn(payload);

      state.latestQueryId = payload.query_id || null;
      state.latestStatus = payload.status || null;
      state.activeTraceQueryId = payload.query_id || null;
      elements.traceToggle.disabled = !state.latestQueryId;

      // Warm the artifact cache so the inspector opens instantly.
      if (state.latestQueryId) {
        void loadArtifacts(state.latestQueryId).catch(() => {});
      }

      if (payload.disclaimer) {
        turn.dataset.disclaimer = payload.disclaimer;
      }
    } catch (error) {
      pending.remove();
      if (requestId === state.requestId) {
        const message =
          error.name === "AbortError"
            ? "The request timed out after 65 seconds. The index may still be warming up — try again."
            : error.message || "The server didn't respond. Check that the API is running.";
        renderErrorTurn(message);
      }
    } finally {
      window.clearTimeout(timeout);
      if (requestId === state.requestId) {
        setBusy(false);
        elements.queryInput.focus();
      }
    }
  }

  /* ── Artifacts / RAG inspector ──────────────────────────────── */

  async function loadArtifacts(queryId) {
    if (!queryId) throw new Error("No query selected");
    if (state.artifacts.has(queryId)) return state.artifacts.get(queryId);

    const response = await fetch(`/artifacts/${encodeURIComponent(queryId)}`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Artifacts returned ${response.status}`);
    }
    const payload = await response.json();
    state.artifacts.set(queryId, payload.artifacts || {});
    return payload.artifacts || {};
  }

  function artifactChip(text, tone) {
    return `<span class="meta-chip${tone ? ` ${tone}` : ""}">${escapeHtml(text)}</span>`;
  }

  function renderMeta(queryId, status, artifacts) {
    const count = Object.keys(artifacts || {}).length;
    const chips = [
      artifactChip(shortQueryId(queryId), "is-ok"),
      artifactChip(`${count}/6 artifacts`),
    ];
    if (status) chips.push(artifactChip(statusFor(status).label));
    elements.traceMeta.innerHTML = chips.join("");
  }

  function retrievalSummary(retrieval) {
    if (!retrieval || typeof retrieval !== "object") return "";
    const results = Array.isArray(retrieval.results) ? retrieval.results : [];
    const chips = [
      artifactChip(retrieval.embedding_model || "retriever"),
      artifactChip(retrieval.collection || "collection"),
      artifactChip(`${results.length} passage${results.length === 1 ? "" : "s"}`),
      artifactChip(`top_k ${retrieval.top_k ?? "—"}`),
    ];
    if (retrieval.min_score !== undefined) {
      chips.push(artifactChip(`min ${retrieval.min_score}`));
    }

    const rows = results
      .map((result) => {
        const score = Number(result.score);
        const text = String(result.text || "").replace(/\s+/g, " ").trim();
        return `
          <div class="trace-chunk">
            <span class="trace-rank">${escapeHtml(result.rank ?? "")}</span>
            <div class="trace-chunk-copy">
              <strong>${escapeHtml(result.source_title || result.chunk_id || "Passage")}</strong>
              <p>${escapeHtml(result.section ? `${result.section} · ${text}` : text)}</p>
            </div>
            <span class="trace-score">${Number.isFinite(score) ? score.toFixed(3) : "—"}</span>
          </div>
        `;
      })
      .join("");

    return `
      <div class="trace-summary">
        <h3>Retrieval summary</h3>
        <div class="trace-summary-row">${chips.join("")}</div>
        ${rows}
      </div>
    `;
  }

  function renderArtifact(queryId, file, artifacts) {
    const value = artifacts[file];
    const artifact = ARTIFACTS.find((item) => item.file === file);
    const label = artifact ? artifact.label : file;

    if (value === undefined) {
      elements.traceBody.innerHTML = `
        <p class="trace-note">${icon("alert")}This stage did not write an artifact for ${escapeHtml(label)}.</p>
        <pre class="trace-json">Artifact not found: ${escapeHtml(file)}</pre>
      `;
      return;
    }

    const pretty =
      typeof value === "string" ? value : JSON.stringify(value, null, 2);
    const summary =
      file === "02_retrieval.json" ? retrievalSummary(value) : "";

    elements.traceBody.innerHTML = `
      ${summary}
      <p class="trace-json-label">${escapeHtml(file)}</p>
      <pre class="trace-json">${escapeHtml(pretty)}</pre>
    `;
    elements.traceBody.scrollTop = 0;
  }

  function renderTabs(queryId, artifacts) {
    elements.traceTabs.innerHTML = ARTIFACTS.map((artifact) => {
      const available = artifacts[artifact.file] !== undefined;
      return `
        <button class="trace-tab" type="button" role="tab"
                data-file="${escapeHtml(artifact.file)}"
                aria-selected="false"
                ${available ? "" : "disabled"}>
          ${escapeHtml(artifact.label)}
        </button>
      `;
    }).join("");

    const preferred = ARTIFACTS.find((artifact) => artifacts[artifact.file]);
    const file = preferred ? preferred.file : ARTIFACTS[0].file;
    selectArtifact(queryId, file, artifacts);
  }

  function selectArtifact(queryId, file, artifacts) {
    state.activeArtifact = file;
    $$(".trace-tab", elements.traceTabs).forEach((tab) => {
      const active = tab.dataset.file === file;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });
    renderArtifact(queryId, file, artifacts);
  }

  async function openTrace(queryId) {
    if (!queryId) {
      showToast("Ask a question first");
      return;
    }

    state.activeTraceQueryId = queryId;
    state.lastFocused = document.activeElement;
    elements.traceDrawer.inert = false;
    elements.traceDrawer.classList.add("is-open");
    elements.traceDrawer.setAttribute("aria-hidden", "false");
    elements.scrim.classList.add("is-open");
    elements.traceClose.focus();
    closeSidebar();

    elements.traceMeta.innerHTML = artifactChip(shortQueryId(queryId), "is-ok");
    elements.traceTabs.innerHTML = "";
    elements.traceBody.innerHTML = `
      <div class="typing" role="status" aria-label="Loading artifacts">
        <span></span><span></span><span></span>
      </div>
    `;

    try {
      const artifacts = await loadArtifacts(queryId);
      const responseArtifact = artifacts["05_response.json"];
      const status =
        responseArtifact && typeof responseArtifact === "object"
          ? responseArtifact.status
          : null;
      renderMeta(queryId, status, artifacts);
      renderTabs(queryId, artifacts);
    } catch (error) {
      elements.traceMeta.innerHTML = artifactChip(shortQueryId(queryId), "is-ok");
      elements.traceBody.innerHTML = `
        <p class="trace-note">${icon("alert")}Couldn't load the artifacts for this query.</p>
        <pre class="trace-json">${escapeHtml(error.message || "Unknown error")}</pre>
      `;
    }
  }

  function closeTrace() {
    if (!elements.traceDrawer.classList.contains("is-open")) return;
    elements.traceDrawer.classList.remove("is-open");
    elements.traceDrawer.setAttribute("aria-hidden", "true");
    elements.traceDrawer.inert = true;
    elements.scrim.classList.remove("is-open");
    if (state.lastFocused && typeof state.lastFocused.focus === "function") {
      state.lastFocused.focus();
    }
  }

  /* ── Sidebar ────────────────────────────────────────────────── */

  function openSidebar() {
    elements.sidebar.classList.add("is-open");
    elements.scrim.classList.add("is-open");
    elements.menuBtn.setAttribute("aria-expanded", "true");
  }

  function closeSidebar() {
    if (!elements.sidebar.classList.contains("is-open")) return;
    elements.sidebar.classList.remove("is-open");
    elements.menuBtn.setAttribute("aria-expanded", "false");
    if (!elements.traceDrawer.classList.contains("is-open")) {
      elements.scrim.classList.remove("is-open");
    }
  }

  function toggleSidebar() {
    if (elements.sidebar.classList.contains("is-open")) closeSidebar();
    else openSidebar();
  }

  /* ── Copy ───────────────────────────────────────────────────── */

  async function copyText(text) {
    try {
      await navigator.clipboard.writeText(text);
      showToast("Answer copied");
    } catch (_error) {
      const scratch = document.createElement("textarea");
      scratch.value = text;
      scratch.setAttribute("readonly", "");
      scratch.style.position = "fixed";
      scratch.style.opacity = "0";
      document.body.append(scratch);
      scratch.select();
      try {
        document.execCommand("copy");
        showToast("Answer copied");
      } catch (_fallbackError) {
        showToast("Copy isn't available in this browser");
      } finally {
        scratch.remove();
      }
    }
  }

  function copyTurn(turn) {
    const answer = $(".answer-text", turn);
    if (!answer) return;

    const lines = [answer.textContent.trim()];
    const citation = $(".citation-card", turn);
    if (citation) {
      const title = $(".citation-copy strong", citation);
      const url = $(".citation-url", citation);
      if (title) lines.push(`Source: ${title.textContent.trim()}`);
      if (url) lines.push(url.textContent.trim());
    }
    const updated = $(".last-updated time", turn);
    if (updated) {
      lines.push(`Last updated from sources: ${updated.textContent.trim()}`);
    }
    void copyText(lines.join("\n"));
  }

  /* ── New chat ───────────────────────────────────────────────── */

  function newChat() {
    state.requestId += 1;
    state.latestQueryId = null;
    state.latestStatus = null;
    state.activeTraceQueryId = null;
    state.activeArtifact = null;
    setBusy(false);
    elements.traceToggle.disabled = true;
    elements.messages.innerHTML = "";
    elements.welcome.hidden = false;
    elements.queryInput.value = "";
    autoGrow();
    closeTrace();
    closeSidebar();
    elements.queryInput.focus();
    scrollToLatest();
    showToast("New chat started");
  }

  /* ── Event wiring ───────────────────────────────────────────── */

  elements.menuBtn.addEventListener("click", toggleSidebar);
  elements.sidebarClose.addEventListener("click", closeSidebar);
  elements.scrim.addEventListener("click", () => {
    closeTrace();
    closeSidebar();
  });

  elements.newChatBtn.addEventListener("click", newChat);
  elements.traceToggle.addEventListener("click", () => openTrace(state.latestQueryId));
  elements.traceClose.addEventListener("click", closeTrace);

  elements.traceTabs.addEventListener("click", (event) => {
    const tab = event.target.closest(".trace-tab");
    if (!tab || tab.disabled) return;
    const queryId = state.activeTraceQueryId;
    const artifacts = state.artifacts.get(queryId);
    if (!artifacts) return;
    selectArtifact(queryId, tab.dataset.file, artifacts);
  });

  elements.queryForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void submitQuery(elements.queryInput.value);
  });

  elements.queryInput.addEventListener("input", autoGrow);
  elements.queryInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!elements.sendBtn.disabled) {
        elements.queryForm.requestSubmit();
      }
    }
  });

  elements.messages.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (!button) return;
    const request = button.closest(".turn");

    if (button.dataset.action === "copy") {
      copyTurn(request);
    } else if (button.dataset.action === "trace") {
      void openTrace(button.dataset.queryId || state.activeTraceQueryId);
    } else if (button.dataset.action === "retry") {
      const lastQuery = $$(".user-bubble", elements.messages).at(-1);
      if (lastQuery) void submitQuery(lastQuery.textContent);
    }
  });

  $$("[data-question]").forEach((button) => {
    button.addEventListener("click", () => {
      elements.queryInput.value = button.dataset.question || "";
      autoGrow();
      if (window.matchMedia("(max-width: 1080px)").matches) closeSidebar();
      void submitQuery(elements.queryInput.value);
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (elements.traceDrawer.classList.contains("is-open")) {
      closeTrace();
    } else if (elements.sidebar.classList.contains("is-open")) {
      closeSidebar();
    }
  });

  // Focus management for the drawer.
  elements.traceDrawer.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const focusable = $$(
      'button:not([disabled]), a[href], textarea, [tabindex]:not([tabindex="-1"])',
      elements.traceDrawer,
    ).filter((node) => node.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });

  autoGrow();
  elements.traceDrawer.inert = true;
  void loadHealth();
})();
