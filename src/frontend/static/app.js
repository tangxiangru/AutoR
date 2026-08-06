const PAGE_IDS = ["overview", "review", "history", "notebook"];
// Legacy hash values that used to map to dedicated pages. Both are now folded
// into the Notebook view, so we redirect them on boot to avoid dead links.
const LEGACY_PAGE_REDIRECTS = { files: "notebook", paper: "notebook" };

// Lazy-load the session viewer ES module from src/frontend/ via the /studio/ext route.
let _sessionViewer = null;
async function loadSessionViewer() {
  if (_sessionViewer) return _sessionViewer;
  try {
    _sessionViewer = await import("/studio/ext/session_viewer.js");
  } catch (err) {
    console.warn("Session viewer module failed to load", err);
    _sessionViewer = { renderSession: () => {} };
  }
  return _sessionViewer;
}

const state = {
  page: readHashPage(),
  projects: [],
  runIds: [],
  selectedProjectId: null,
  selectedRunId: null,
  selectedStageSlug: null,
  selectedFilePath: null,
  selectedVersionId: null,
  runSummary: null,
  artifactIndex: null,
  fileTree: null,
  stageDocument: "",
  filePreview: null,
  paperPreview: null,
  history: null,
  iterationPlan: null,
};

const appShell = document.querySelector(".app-shell");
function setView(view) {
  if (appShell) appShell.dataset.view = view;
}
if (typeof window !== "undefined") {
  const _params = new URLSearchParams(window.location.search);
  if (_params.get("view") === "workspace") setView("workspace");
  const _pid = _params.get("project");
  if (_pid) state.selectedProjectId = _pid;
  const _rid = _params.get("run");
  if (_rid) state.selectedRunId = _rid;
}

const elements = {
  connectionStatus: document.getElementById("connection-status"),
  reloadButton: document.getElementById("reload-button"),
  backToHub: document.getElementById("back-to-hub"),
  approveStageButton: document.getElementById("approve-stage-button"),
  sendFeedbackButton: document.getElementById("send-feedback-button"),
  liveIndicator: document.getElementById("live-indicator"),
  liveStageTitle: document.getElementById("live-stage-title"),
  liveStatusChip: document.getElementById("live-status-chip"),
  liveProgressText: document.getElementById("live-progress-text"),
  liveAttemptText: document.getElementById("live-attempt-text"),
  liveProgressFill: document.getElementById("live-progress-fill"),
  liveApprove: document.getElementById("live-approve"),
  liveFeedback: document.getElementById("live-feedback-quick"),
  liveLastEvent: document.getElementById("live-last-event"),
  liveTicker: document.getElementById("live-ticker"),
  stageStrip: document.getElementById("stage-strip"),
  reviewStageStrip: document.getElementById("review-stage-strip"),
  reviewPreviousList: document.getElementById("review-previous-list"),
  reviewPreviousCount: document.getElementById("review-previous-count"),
  reviewProgressSummary: document.getElementById("review-progress-summary"),
  reviewProgressText: document.getElementById("review-progress-text"),
  reviewHero: document.getElementById("review-hero"),
  reviewHeroTitle: document.getElementById("review-hero-title"),
  reviewHeroSub: document.getElementById("review-hero-sub"),
  reviewHeroChip: document.getElementById("review-hero-chip"),
  reviewHeroTldr: document.getElementById("review-hero-tldr"),
  reviewHeroFiles: document.getElementById("review-hero-files"),
  reviewNext: document.getElementById("review-next"),
  activityFeed: document.getElementById("activity-feed"),
  activityCount: document.getElementById("activity-count"),
  stageSessionView: document.getElementById("stage-session-view"),
  sessionEventCount: document.getElementById("session-event-count"),
  pageButtons: [...document.querySelectorAll(".page-link")],
  pages: Object.fromEntries(PAGE_IDS.map((page) => [page, document.getElementById(`page-${page}`)])),
  projectCount: document.getElementById("project-count"),
  runCount: document.getElementById("run-count"),
  projectForm: document.getElementById("project-form"),
  projectTitle: document.getElementById("project-title"),
  projectThesis: document.getElementById("project-thesis"),
  projectsList: document.getElementById("projects-list"),
  runsList: document.getElementById("runs-list"),
  attachRunButton: document.getElementById("attach-run-button"),
  activeProjectLabel: document.getElementById("active-project-label"),
  runTitle: document.getElementById("run-title"),
  runGoal: document.getElementById("run-goal"),
  runStatus: document.getElementById("run-status"),
  projectMeta: document.getElementById("project-meta"),
  projectBrief: document.getElementById("project-brief"),
  stageCount: document.getElementById("stage-count"),
  stageRail: document.getElementById("stage-rail"),
  overviewStageTitle: document.getElementById("overview-stage-title"),
  overviewStageMeta: document.getElementById("overview-stage-meta"),
  overviewStageSummary: document.getElementById("overview-stage-summary"),
  runSummary: document.getElementById("run-summary"),
  artifactTotal: document.getElementById("artifact-total"),
  artifactSummary: document.getElementById("artifact-summary"),
  reviewStageLabel: document.getElementById("review-stage-label"),
  documentTitle: document.getElementById("document-title"),
  documentMeta: document.getElementById("document-meta"),
  stageDocument: document.getElementById("stage-document"),
  iterationForm: document.getElementById("iteration-form"),
  iterationMode: document.getElementById("iteration-mode"),
  iterationStage: document.getElementById("iteration-stage"),
  iterationScopeType: document.getElementById("iteration-scope-type"),
  iterationScopeValue: document.getElementById("iteration-scope-value"),
  iterationFeedback: document.getElementById("iteration-feedback"),
  iterationPlan: document.getElementById("iteration-plan"),
  fileTree: document.getElementById("file-tree"),
  filePreviewTitle: document.getElementById("file-preview-title"),
  filePreviewMeta: document.getElementById("file-preview-meta"),
  filePreview: document.getElementById("file-preview"),
  paperStatus: document.getElementById("paper-status"),
  paperFrameContainer: document.getElementById("paper-frame-container"),
  paperMeta: document.getElementById("paper-meta"),
  paperSummary: document.getElementById("paper-summary"),
  paperSections: document.getElementById("paper-sections"),
  paperTexPreview: document.getElementById("paper-tex-preview"),
  paperBuildLog: document.getElementById("paper-build-log"),
  versionCount: document.getElementById("version-count"),
  versionList: document.getElementById("version-list"),
  historyTitle: document.getElementById("history-title"),
  historyMeta: document.getElementById("history-meta"),
  historySummary: document.getElementById("history-summary"),
  historyArtifacts: document.getElementById("history-artifacts"),
  historyStagePreview: document.getElementById("history-stage-preview"),
  traceCount: document.getElementById("trace-count"),
  traceTimeline: document.getElementById("trace-timeline"),
};

elements.reloadButton.addEventListener("click", () => {
  void safeAction(bootstrap());
});

elements.projectForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void safeAction(createProject());
});

if (elements.attachRunButton) {
  elements.attachRunButton.addEventListener("click", () => {
    void safeAction(attachSelectedRun());
  });
}

elements.iterationForm.addEventListener("submit", (event) => {
  event.preventDefault();
  void safeAction(planIteration());
});

for (const button of elements.pageButtons) {
  button.addEventListener("click", () => {
    const page = button.dataset.page;
    setPage(page);
    // Trigger a full load for the tab being navigated to, so the user sees
    // fresh data for review/history without the poll loop having to fetch
    // those heavy endpoints continuously.
    if (state.selectedRunId) {
      void safeAction(loadRunFull(state.selectedRunId));
    }
    if (page === "review") {
      const reviewing = state.runSummary?.stages?.find((s) => s.status === "human_review");
      if (reviewing && reviewing.slug !== state.selectedStageSlug) {
        void safeAction(loadStageDocument(reviewing.slug));
      }
    }
    if (page === "notebook" && state.selectedRunId) {
      void loadNotebookView().then((mod) => mod?.openNotebook?.({ runId: state.selectedRunId, summary: state.runSummary, fileTree: state.fileTree, paperPreview: state.paperPreview, projectBrief: getSelectedProject() }));
    }
  });
}

// Lazy-load the Notebook view module so the existing pages keep their
// bootstrap path unchanged even if notebook.js fails to load.
let _notebookMod = null;
async function loadNotebookView() {
  if (_notebookMod) return _notebookMod;
  try {
    _notebookMod = await import("/studio/notebook.js");
  } catch (err) {
    console.warn("Notebook module failed to load", err);
    _notebookMod = null;
  }
  return _notebookMod;
}

if (elements.backToHub) {
  elements.backToHub.addEventListener("click", () => {
    setView("hub");
    stopPolling();
  });
}
if (elements.approveStageButton) {
  elements.approveStageButton.addEventListener("click", () => {
    void safeAction(approveCurrentStage());
  });
}
if (elements.sendFeedbackButton) {
  elements.sendFeedbackButton.addEventListener("click", () => {
    void safeAction(sendStageFeedback());
  });
}
if (elements.liveApprove) {
  elements.liveApprove.addEventListener("click", () => {
    void safeAction(approveCurrentStage());
  });
}
if (elements.liveFeedback) {
  elements.liveFeedback.addEventListener("click", () => {
    setPage("review");
    const quick = document.getElementById("iteration-feedback-quick");
    if (quick) quick.focus();
    else if (elements.iterationFeedback) elements.iterationFeedback.focus();
  });
}

window.addEventListener("hashchange", () => {
  const page = readHashPage();
  if (page !== state.page) {
    state.page = page;
    renderPageNav();
  }
});

renderPageNav();
void safeAction(bootstrap());

async function bootstrap() {
  setConnection("Loading");
  const [projectsPayload, runsPayload] = await Promise.all([
    api("/api/projects/overview"),
    api("/api/runs"),
  ]);
  state.projects = projectsPayload.projects || [];
  state.runIds = runsPayload.run_ids || [];

  if (!state.selectedProjectId && state.projects.length) {
    // Prefer a project with a live run (awaiting review or actively running)
    // over one with a failed/stale run so the user lands on the active loop.
    const living = state.projects.find((p) =>
      ["human_review", "running"].includes(p.latest_run_status)
    );
    state.selectedProjectId = (living || state.projects[0]).project_id;
  }
  if (state.selectedProjectId && !state.projects.some((project) => project.project_id === state.selectedProjectId)) {
    state.selectedProjectId = state.projects[0]?.project_id || null;
  }

  const preferredRunId =
    state.projects.find((project) => project.project_id === state.selectedProjectId)?.active_run_id ||
    state.selectedRunId ||
    state.runIds.at(-1) ||
    null;

  renderProjects();
  renderRuns();

  if (preferredRunId) {
    try {
      await loadRun(preferredRunId);
      startPolling();
    } catch (err) {
      console.warn("[bootstrap] Failed to load run", preferredRunId, "error:", err && (err.message || err));
      // Don't wipe state — the user may have just created this run and a
      // background renderer race lost. Keep the run ID so polling can retry.
      state.selectedRunId = preferredRunId;
      renderWorkspaceSkeleton("Latest run could not be loaded yet. Retrying…");
      startPolling();
    }
  } else {
    clearRunState();
    renderWorkspaceSkeleton("No runs found under the configured runs directory.");
  }

  setConnection("Connected");

  // If we booted into the notebook hash, open it.
  if (state.page === "notebook" && state.selectedRunId) {
    void loadNotebookView().then((mod) =>
      mod?.openNotebook?.({
        runId: state.selectedRunId,
        summary: state.runSummary,
        fileTree: state.fileTree,
        paperPreview: state.paperPreview,
        projectBrief: getSelectedProject(),
      })
    );
  }
}

async function createProject() {
  const payload = {
    title: elements.projectTitle.value.trim(),
    thesis: elements.projectThesis.value.trim(),
  };
  if (!payload.title || !payload.thesis) {
    return;
  }
  // Stop any stale polling from a previously loaded run so its 5 in-flight
  // fetches don't race with the fresh createProject flow and cause the new
  // run's loadRun to fail with "Failed to fetch".
  stopPolling();
  const created = await api("/api/projects", { method: "POST", body: payload });
  state.selectedProjectId = created.project_id;
  elements.projectForm.reset();
  // Immediately spin up a run for the new project so the loop starts.
  const started = await api(`/api/projects/${created.project_id}/runs/start`, {
    method: "POST",
    body: { goal: payload.thesis },
  });
  state.selectedRunId = started.run_id;
  setView("workspace");
  // Skip a second bootstrap here — just directly load the new run and start
  // polling. bootstrap() re-fetches overview and can land us on a different
  // project's active run if the project list changed under us.
  try {
    await loadRun(started.run_id);
  } catch (err) {
    console.warn("[create] initial loadRun failed; polling will retry", err);
  }
  startPolling();
  // Refresh the projects list in the background so the hub stays current
  // next time the user navigates back.
  void safeAction(
    (async () => {
      const overview = await api("/api/projects/overview");
      state.projects = overview.projects || [];
      renderProjects();
    })()
  );
}

// A stage is "actionable" (the human can approve, send feedback, or resume)
// when it is:
//   - human_review: normal review gate
//   - failed: validator or execution failure — user can override or retry
//   - running: possibly an orphaned worker from a server crash — the backend
//     lazy-resumes on any action so it's safe to offer the buttons
function findActionableStage() {
  const stages = state.runSummary?.stages || [];
  return (
    stages.find((s) => s.status === "human_review") ||
    stages.find((s) => s.status === "failed") ||
    stages.find((s) => s.status === "running") ||
    null
  );
}

async function approveCurrentStage() {
  if (!state.selectedRunId) return;
  const reviewing = findActionableStage();
  if (!reviewing) {
    showToast("Nothing is awaiting review right now.", "warn");
    return;
  }
  // If the user is currently viewing a different stage, JUMP to the awaiting
  // one instead of silently approving something they can't see. This matches
  // the "↗ Jump to …" button label.
  if (state.selectedStageSlug && state.selectedStageSlug !== reviewing.slug) {
    await loadStageDocument(reviewing.slug);
    showToast(`Now showing ${shortStageTitle(reviewing.title)}. Click Approve again to confirm.`, "info");
    return;
  }
  const focus = reviewing.slug;
  setButtonLoading(elements.approveStageButton, "Approving…");
  setButtonLoading(elements.liveApprove, "Approving…");
  let succeeded = false;
  try {
    await api(`/api/runs/${state.selectedRunId}/stages/${focus}/approve`, {
      method: "POST",
      body: {},
    });
    succeeded = true;
    showToast(`✅ Approved ${shortStageTitle(reviewing.title)}`, "success");
    await loadRun(state.selectedRunId);
    startPolling();
  } catch (err) {
    showToast(`Approve failed: ${err.message || err}`, "error");
    throw err;
  } finally {
    // On success the renderer above already set the new label; clear the
    // loading state without touching the text. On failure, restore.
    clearButtonLoading(elements.approveStageButton, { restoreLabel: !succeeded });
    clearButtonLoading(elements.liveApprove, { restoreLabel: !succeeded });
  }
}

async function sendStageFeedback() {
  if (!state.selectedRunId) return;
  const reviewing = findActionableStage();
  if (!reviewing) {
    showToast("Nothing is awaiting review right now.", "warn");
    return;
  }
  const focus = reviewing.slug;
  state.selectedStageSlug = focus;
  const quick = document.getElementById("iteration-feedback-quick");
  const feedback = (quick && quick.value.trim()) || (elements.iterationFeedback && elements.iterationFeedback.value.trim());
  if (!feedback) {
    showToast("Write some feedback before sending it.", "warn");
    if (quick) quick.focus();
    return;
  }
  setButtonLoading(elements.sendFeedbackButton, "Sending…");
  let succeeded = false;
  try {
    await api(`/api/runs/${state.selectedRunId}/stages/${focus}/feedback`, {
      method: "POST",
      body: { feedback },
    });
    succeeded = true;
    showToast(`📝 Feedback sent. Re-running ${shortStageTitle(reviewing.title)}…`, "success");
    if (elements.iterationFeedback) elements.iterationFeedback.value = "";
    if (quick) quick.value = "";
    await loadRun(state.selectedRunId);
    startPolling();
  } catch (err) {
    showToast(`Feedback failed: ${err.message || err}`, "error");
    throw err;
  } finally {
    clearButtonLoading(elements.sendFeedbackButton, { restoreLabel: !succeeded });
  }
}

// ---------- Live polling ----------
let pollHandle = null;
function startPolling() {
  stopPolling();
  pollHandle = setInterval(() => {
    // Pause when the browser tab is hidden — no point fetching if the user
    // isn't looking, and it prevents background tabs from accumulating
    // memory pressure.
    if (document.hidden) return;
    if (!state.selectedRunId) return;
    const status = state.runSummary?.run_status;
    if (status === "completed" || status === "failed") {
      stopPolling();
      return;
    }
    // LIGHT poll: only fetch the run summary (1 request). The heavy
    // endpoints (file tree, paper, history, stage doc, session) are fetched
    // only on explicit user actions (page tab click, approve, feedback).
    void pollRunLight(state.selectedRunId).catch((err) => console.warn("[poll] light poll failed", err));
  }, 3000);
}
// Pause polling entirely when the browser tab is hidden. Resume (with a
// full load to catch up on state) when the user comes back.
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopPolling();
  } else if (state.selectedRunId) {
    const status = state.runSummary?.run_status;
    if (status !== "completed" && status !== "failed") {
      // Full load once to catch up, then resume light polling.
      void loadRunFull(state.selectedRunId).then(startPolling).catch(() => startPolling());
    }
  }
});

// Expose a tiny debug surface so the drive harness can introspect.
if (typeof window !== "undefined") {
  window.__autor = {
    get state() { return state; },
    get pollHandle() { return pollHandle; },
    loadRun: (id) => loadRun(id),
  };
}
function stopPolling() {
  if (pollHandle) {
    clearInterval(pollHandle);
    pollHandle = null;
  }
}

async function attachSelectedRun() {
  if (!state.selectedProjectId || !state.selectedRunId) {
    renderIterationPlaceholder("Select both a project and a run before attaching.");
    return;
  }
  await api(`/api/projects/${state.selectedProjectId}/runs`, {
    method: "POST",
    body: { run_id: state.selectedRunId, make_active: true },
  });
  await bootstrap();
}

// ---------- Run loading: light vs full ----------
//
// CRITICAL MEMORY SAFETY: on an 8 GB Mac the previous design fetched 7
// endpoints in parallel every poll tick (summary + artifacts + file tree +
// paper + history + stage doc + session). The file-tree endpoint does a
// recursive directory walk; the session endpoint parses a growing JSONL.
// Together with Cursor + Chrome + Claude CLI, this caused a kernel panic
// (watchdog timeout from 103% compressed pages).
//
// New design:
//   - pollRunLight() — ONLY fetches /api/runs/{id} (the summary). Called
//     every poll tick. Updates the stage strip, live panel, header, and
//     activity feed — everything the user needs to see while waiting.
//   - loadRunFull() — fetches ALL 7 endpoints. Called ONCE on initial load,
//     on explicit user navigation (page tab click, project card click,
//     approve/feedback), and NEVER from the poll loop.

async function pollRunLight(runId) {
  state.selectedRunId = runId;
  const summary = await api(`/api/runs/${runId}`);
  state.runSummary = summary;

  const matchingProject = state.projects.find(
    (p) => p.project_id === state.selectedProjectId || p.run_ids.includes(runId)
  );
  if (matchingProject) state.selectedProjectId = matchingProject.project_id;

  if (!state.selectedStageSlug || !summary.stages.some((s) => s.slug === state.selectedStageSlug)) {
    const reviewing = summary.stages.find((s) => s.status === "human_review");
    const lastApproved = [...summary.stages].reverse().find((s) => s.settled);
    const running = summary.stages.find((s) => s.status === "running");
    state.selectedStageSlug =
      reviewing?.slug || lastApproved?.slug || running?.slug ||
      summary.current_stage_slug || summary.stages.at(-1)?.slug || null;
  }

  // Only render the cheap panels that depend on the summary.
  renderHeader();
  renderStages();
  renderLivePanel();
  renderActivityFeed();
  renderReviewProgressSummary();
  renderStagePanels();
  if (state.page === "notebook" && _notebookMod?.refreshSources) {
    _notebookMod.refreshSources({ summary: state.runSummary });
  }
}

async function loadRunFull(runId) {
  const runChanged = runId !== state.selectedRunId;
  state.selectedRunId = runId;
  if (runChanged) {
    state.selectedFilePath = null;
    state.filePreview = null;
    state.iterationPlan = null;
    state.selectedVersionId = null;
  }

  const [summary, artifacts, fileTree, paperPreview, history] = await Promise.all([
    api(`/api/runs/${runId}`),
    api(`/api/runs/${runId}/artifacts`),
    api(`/api/runs/${runId}/files/tree?root=workspace&depth=4`),
    api(`/api/runs/${runId}/paper`),
    api(`/api/runs/${runId}/history`),
  ]);
  state.runSummary = summary;
  state.artifactIndex = artifacts;
  state.fileTree = fileTree;
  state.paperPreview = paperPreview;
  state.history = history;
  state.selectedVersionId = state.selectedVersionId || history.current_version_id || history.versions.at(-1)?.version_id || null;

  const matchingProject = state.projects.find(
    (p) => p.project_id === state.selectedProjectId || p.run_ids.includes(runId)
  );
  if (matchingProject) state.selectedProjectId = matchingProject.project_id;

  if (!state.selectedStageSlug || !summary.stages.some((s) => s.slug === state.selectedStageSlug)) {
    const reviewing = summary.stages.find((s) => s.status === "human_review");
    const lastApproved = [...summary.stages].reverse().find((s) => s.settled);
    const running = summary.stages.find((s) => s.status === "running");
    state.selectedStageSlug =
      reviewing?.slug || lastApproved?.slug || running?.slug ||
      summary.current_stage_slug || summary.stages.at(-1)?.slug || null;
  }

  renderProjects();
  renderRuns();
  renderHeader();
  renderProjectBrief();
  renderSummary();
  renderArtifacts();
  renderStages();
  renderLivePanel();
  renderActivityFeed();
  renderPreviousStages();
  renderReviewProgressSummary();
  renderFileTree();
  renderPaperPreview();
  renderHistory();
  renderIterationForm();

  if (state.selectedStageSlug) {
    try {
      await loadStageDocument(state.selectedStageSlug);
    } catch (err) {
      console.warn("[loadRunFull] stage doc fetch failed", err);
      state.stageDocument = "";
      renderStagePanels();
    }
  } else {
    renderStagePanels();
  }
}

// Backwards-compatible alias — callers that need the full load use this.
const loadRun = loadRunFull;

async function loadStageDocument(stageSlug) {
  if (!state.selectedRunId) {
    return;
  }
  state.selectedStageSlug = stageSlug;
  const payload = await api(`/api/runs/${state.selectedRunId}/stages/${stageSlug}`);
  state.stageDocument = payload.markdown || "";
  renderStages();
  renderStagePanels();
  renderHistory();
  renderIterationForm();
  void loadStageSession(stageSlug);
}

// Track the signature of the last rendered session per (run, stage) so we
// only re-render the session trace when it actually changed. Re-rendering on
// every poll tick wipes innerHTML and with it the user's scroll position.
const _sessionRenderedKey = { ref: "" };
// Cache of the latest session event per stage, used to enrich the live-event
// line on the Overview ("🔄 Stage 05: read_file {path: workspace/...}").
const _latestSessionEventCache = {};
// Track the last (run, pdf_available) we mounted in the paper iframe so
// polling doesn't tear it down and re-download the PDF every tick.
const _paperRenderedKey = { ref: "" };

async function loadStageSession(stageSlug) {
  if (!state.selectedRunId || !stageSlug) return;
  try {
    const payload = await api(`/api/runs/${state.selectedRunId}/stages/${stageSlug}/session`);
    const events = payload.events || [];
    if (elements.sessionEventCount) {
      elements.sessionEventCount.textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;
    }
    // Only rebuild the DOM if the (run, stage, count) tuple changed.
    // Otherwise keep the existing DOM — this preserves the user's scroll
    // position in the session panel during polling.
    const key = `${state.selectedRunId}|${stageSlug}|${events.length}`;
    if (key !== _sessionRenderedKey.ref) {
      const container = elements.stageSessionView;
      const listEl = container ? container.querySelector(".session-event-list") : null;
      const prevScroll = listEl ? listEl.scrollTop : 0;
      // "Follow tail" mode: if we were already at the bottom (or this is a
      // fresh render of a new stage), auto-scroll to the newest event so
      // live runner activity is always visible.
      const wasAtBottom = listEl
        ? listEl.scrollTop + listEl.clientHeight >= listEl.scrollHeight - 20
        : true;
      const isStageChange = !_sessionRenderedKey.ref.startsWith(`${state.selectedRunId}|${stageSlug}|`);
      const viewer = await loadSessionViewer();
      viewer.renderSession(container, events);
      const newList = container ? container.querySelector(".session-event-list") : null;
      if (newList) {
        if (wasAtBottom || isStageChange) newList.scrollTop = newList.scrollHeight;
        else newList.scrollTop = prevScroll;
      }
      _sessionRenderedKey.ref = key;
    }
    // Also mirror the most recent events into the Overview live ticker and
    // cache the latest event so the live-event line can enrich itself.
    renderLiveTicker(events);
    if (events.length) {
      _latestSessionEventCache[stageSlug] = events[events.length - 1];
      // Re-render the live panel with the new enriched event line.
      renderLivePanel();
    }
  } catch (err) {
    console.warn("session fetch failed", err);
    if (elements.stageSessionView) {
      elements.stageSessionView.innerHTML = `<div class="session-empty">Session trace not available for this stage.</div>`;
    }
  }
}

function renderLiveTicker(events) {
  if (!elements.liveTicker) return;
  elements.liveTicker.innerHTML = "";
  const recent = events.slice(-4).reverse(); // newest first, max 4
  for (const ev of recent) {
    const li = document.createElement("li");
    li.className = `live-ticker-item event-${ev.kind || "other"}`;
    const icon =
      ev.kind === "tool_use" ? "⚡" :
      ev.kind === "tool_result" ? "↩" :
      ev.kind === "assistant" ? "◆" :
      ev.kind === "system" ? "⚙" :
      ev.kind === "stage_start" ? "▶" :
      ev.kind === "stage_end" ? "■" :
      ev.kind === "approval" ? "✅" :
      ev.kind === "feedback" ? "✍︎" : "·";
    let body = "";
    if (ev.kind === "tool_use" && ev.tool) {
      body = `<code>${escapeHtml(ev.tool.name || "")}</code> ${escapeHtml(JSON.stringify(ev.tool.input || {}).slice(0, 80))}`;
    } else if (ev.kind === "tool_result" && ev.output) {
      body = escapeHtml(String(ev.output).slice(0, 120));
    } else if (ev.content) {
      body = escapeHtml(ev.content.slice(0, 140));
    }
    li.innerHTML = `
      <span class="live-ticker-icon">${icon}</span>
      <span class="live-ticker-body">${body}</span>
      <span class="live-ticker-time">${escapeHtml(formatShortTime(ev.ts))}</span>
    `;
    elements.liveTicker.appendChild(li);
  }
}

async function loadFileContent(relativePath) {
  if (!state.selectedRunId) {
    return;
  }
  state.selectedFilePath = relativePath;
  state.filePreview = await api(
    `/api/runs/${state.selectedRunId}/files/content?path=${encodeURIComponent(relativePath)}`
  );
  renderFileTree();
  renderFilePreview();
  setPage("files");
}

async function planIteration() {
  if (!state.selectedRunId) {
    renderIterationPlaceholder("Select a run before generating an execution brief.");
    return;
  }
  const payload = {
    base_stage_slug: elements.iterationStage.value,
    scope_type: elements.iterationScopeType.value,
    scope_value: elements.iterationScopeValue.value.trim() || elements.iterationStage.value,
    mode: elements.iterationMode.value,
    user_feedback: elements.iterationFeedback.value.trim(),
  };
  state.iterationPlan = await api(`/api/runs/${state.selectedRunId}/iterations/plan`, {
    method: "POST",
    body: payload,
  });
  renderIterationPlan();
  setPage("review");
}

const STATUS_LABELS = {
  running: "Running",
  human_review: "Awaiting Review",
  pending: "Queued",
  approved: "Approved",
  skipped: "Skipped",
  completed: "Completed",
  failed: "Failed",
  stale: "Stale",
};

function humanStatus(status) {
  if (!status) return "No run";
  return STATUS_LABELS[status] || status.replace(/_/g, " ");
}

// Stage titles from the manifest already look like "Stage 01: Literature Survey"
// in most code paths. Strip any duplicate "Stage NN:" prefix so callers can
// freely re-prefix without producing "Stage 01: Stage 01: …".
function shortStageTitle(title) {
  if (!title) return "";
  return title.replace(/^stage\s*\d{1,2}\s*[:·-]\s*/i, "").trim();
}
function fullStageTitle(number, title) {
  const short = shortStageTitle(title);
  return `Stage ${String(number).padStart(2, "0")}: ${short || title}`;
}

function renderHeader() {
  const project = getSelectedProject();
  const summary = state.runSummary;

  elements.activeProjectLabel.textContent = project ? project.title : "No project selected";
  elements.runTitle.textContent = summary ? summary.run_id : "No run selected";
  elements.runGoal.textContent = summary?.goal || "Select a run to inspect stage output, files, and manuscript artifacts.";
  const status = summary?.run_status || "";
  elements.runStatus.textContent = humanStatus(status);
  elements.runStatus.className = `badge badge-status status-${status || "idle"}`;
}

function renderLivePanel() {
  const summary = state.runSummary;
  const stages = summary?.stages || [];
  const settled = stages.filter((s) => s.settled).length;
  const total = stages.length;
  const pct = total > 0 ? Math.round((settled / total) * 100) : 0;

  // Horizontal stage strip — 8 pills at a glance
  renderStageStrip(stages);

  // Progress bar
  elements.liveProgressFill.style.width = `${pct}%`;
  elements.liveProgressText.textContent = total
    ? `${approved} / ${total} stages approved · ${pct}%`
    : "No run loaded";

  // If the run is settled (completed/failed), skip the per-stage focus and
  // show the run-level status. Otherwise pick the working/awaiting stage.
  const runSettled = summary && (summary.run_status === "completed" || summary.run_status === "failed");
  const focus = runSettled
    ? null
    : (
        stages.find((s) => s.status === "running") ||
        stages.find((s) => s.status === "human_review") ||
        stages.find((s) => !s.settled) ||
        null
      );

  if (!summary || !focus) {
    elements.liveStageTitle.textContent = summary ? "Run complete" : "No run selected";
    elements.liveStatusChip.textContent = humanStatus(summary?.run_status);
    elements.liveStatusChip.className = `status-chip status-${summary?.run_status || "idle"}`;
    elements.liveAttemptText.textContent = "";
    elements.liveLastEvent.textContent = summary
      ? `All stages complete. Final status: ${humanStatus(summary.run_status)}.`
      : "Pick a project from Projects to open its run.";
    elements.liveIndicator.className = `live-dot ${
      summary?.run_status === "completed" ? "is-done" : summary?.run_status === "failed" ? "is-failed" : ""
    }`;
    setLiveButtonsEnabled(false);
    return;
  }

  elements.liveStageTitle.textContent = fullStageTitle(focus.number, focus.title);
  elements.liveStatusChip.textContent = humanStatus(focus.status);
  elements.liveStatusChip.className = `status-chip status-${focus.status}`;

  // Attempts
  elements.liveAttemptText.textContent =
    focus.attempt_count > 1 ? `attempt ${focus.attempt_count}` : focus.attempt_count === 1 ? "attempt 1" : "";

  // Live dot animation
  if (focus.status === "running") {
    elements.liveIndicator.className = "live-dot is-live";
  } else if (focus.status === "human_review") {
    elements.liveIndicator.className = "live-dot is-review";
  } else if (summary.run_status === "completed") {
    elements.liveIndicator.className = "live-dot is-done";
  } else if (summary.run_status === "failed") {
    elements.liveIndicator.className = "live-dot is-failed";
  } else {
    elements.liveIndicator.className = "live-dot";
  }

  // Last-event line
  const eventText = describeLastEvent(summary, focus);
  elements.liveLastEvent.textContent = eventText;

  // Buttons enabled only while awaiting review. Update labels too so the
  // user can see at a glance whether the action is live or the runner is
  // still busy. This is what fixes the "approve button stays green after
  // I clicked it" feel.
  let canAct = focus.status === "human_review";
  if (canAct) {
    elements.liveApprove.textContent = "✅ Approve";
    elements.liveFeedback.textContent = "✍︎ Review";
  } else if (focus.status === "running") {
    // If the stage is "running" it might be an orphan from a crashed server.
    // Show resume controls so the user can kick it back into action.
    elements.liveApprove.textContent = `🔄 Resume ${shortStageTitle(focus.title)}`;
    elements.liveFeedback.textContent = "🔁 Restart";
    canAct = true;  // Enable the buttons for orphan recovery
  } else {
    elements.liveApprove.textContent = "✅ Approve";
    elements.liveFeedback.textContent = "✍︎ Review";
  }
  setLiveButtonsEnabled(canAct);
  elements.liveApprove.dataset.stageSlug = focus.slug;
  elements.liveFeedback.dataset.stageSlug = focus.slug;
}

function setLiveButtonsEnabled(on) {
  elements.liveApprove.disabled = !on;
  elements.liveFeedback.disabled = !on;
}

function describeLastEvent(summary, focus) {
  const when = focus.updated_at ? ` · ${focus.updated_at}` : "";
  const name = fullStageTitle(focus.number, focus.title);
  // For running stages, try to enrich with the most recent session tool_use
  // so the user sees "reading workspace/X.json" instead of a generic message.
  const latest = _latestSessionEventCache[focus.slug];
  if (focus.status === "running" && latest) {
    if (latest.kind === "tool_use" && latest.tool) {
      const input = latest.tool.input ? JSON.stringify(latest.tool.input).slice(0, 80) : "";
      return `🔄 ${name}: ${latest.tool.name}(${input})`;
    }
    if (latest.kind === "assistant" && latest.content) {
      return `🔄 ${name}: ${latest.content.slice(0, 120)}`;
    }
  }
  switch (focus.status) {
    case "running":
      return `🔄 Runner is drafting ${name}${when}`;
    case "human_review":
      return `👀 Waiting for your review on ${name}${when}. Approve to advance, or send feedback to re-run.`;
    case "approved":
      return `✅ ${name} approved${when}`;
    case "skipped":
      return `⏭️ ${name} was skipped${when} — its work was never done`;
    case "failed":
      return `❌ ${name} failed${when}`;
    default:
      return `${name}: ${humanStatus(focus.status)}${when}`;
  }
}

function renderActivityFeed() {
  const stages = state.runSummary?.stages || [];
  elements.activityFeed.innerHTML = "";

  // Derive a simple activity feed from the stage manifest entries, newest first.
  const events = [];
  for (const s of stages) {
    if (s.status === "pending" && !s.approved_at) continue;
    events.push({
      slug: s.slug,
      title: s.title,
      number: s.number,
      status: s.status,
      approved: s.approved,
      skipped: s.skipped,
      time: s.approved_at || s.updated_at || "",
      attempt: s.attempt_count || 0,
    });
  }
  events.sort((a, b) => (b.time || "").localeCompare(a.time || ""));

  elements.activityCount.textContent = `${events.length} event${events.length === 1 ? "" : "s"}`;

  if (events.length === 0) {
    const li = document.createElement("li");
    li.className = "is-pending";
    li.innerHTML = `<span class="activity-dot"></span><div class="activity-main"><div class="activity-detail">No activity yet. The runner will start momentarily…</div></div><span class="activity-time"></span>`;
    elements.activityFeed.appendChild(li);
    return;
  }

  for (const ev of events) {
    const li = document.createElement("li");
    const klass =
      ev.status === "running"
        ? "is-running"
        : ev.status === "human_review"
        ? "is-review"
        : ev.approved
        ? "is-approved"
        : ev.status === "failed"
        ? "is-failed"
        : "is-pending";
    li.className = klass;
    const verb = ev.approved
      ? "approved"
      : ev.status === "running"
      ? "is drafting"
      : ev.status === "human_review"
      ? "awaiting review"
      : ev.status === "failed"
      ? "failed"
      : ev.status;
    const attemptNote = ev.attempt > 1 ? ` · attempt ${ev.attempt}` : "";
    const shortTitle = shortStageTitle(ev.title);
    li.innerHTML = `
      <span class="activity-dot"></span>
      <div class="activity-main">
        <div class="activity-title">Stage ${String(ev.number).padStart(2, "0")} · ${escapeHtml(shortTitle)}</div>
        <div class="activity-detail">${escapeHtml(verb)}${escapeHtml(attemptNote)}</div>
      </div>
      <span class="activity-time">${escapeHtml(formatShortTime(ev.time))}</span>
    `;
    elements.activityFeed.appendChild(li);
  }
}

function formatShortTime(iso) {
  if (!iso) return "";
  const t = iso.split("T")[1];
  return t ? t.slice(0, 8) : iso;
}

function formatRelativeTime(iso) {
  if (!iso) return "—";
  const t = Date.parse(iso);
  if (isNaN(t)) return iso;
  const diff = Date.now() - t;
  if (diff < 0) return "just now";
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  const mo = Math.floor(d / 30);
  if (mo < 12) return `${mo}mo ago`;
  return `${Math.floor(mo / 12)}y ago`;
}

function renderProjects() {
  elements.projectCount.textContent = String(state.projects.length);
  elements.projectsList.innerHTML = "";

  // Sort newest-first so the latest project is always on top. Fall back to
  // created_at, then project_id, so the order is stable if timestamps are missing.
  const sorted = [...state.projects].sort((a, b) => {
    const ta = a.updated_at || a.created_at || "";
    const tb = b.updated_at || b.created_at || "";
    if (ta !== tb) return tb.localeCompare(ta);
    return (b.project_id || "").localeCompare(a.project_id || "");
  });

  if (sorted.length === 0) {
    const empty = document.createElement("div");
    empty.className = "projects-empty";
    empty.innerHTML = `
      <p class="eyebrow">No projects yet</p>
      <p>Fill in the <b>New Project</b> form above and the runner will start immediately.</p>
    `;
    elements.projectsList.appendChild(empty);
    return;
  }

  for (const project of sorted) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `project-card${project.project_id === state.selectedProjectId ? " is-active" : ""}`;

    // Compute a simple progress signal from latest_completed_stage_slug.
    // Slugs look like "05_experimentation"; parse the number.
    const stageMatch = (project.latest_completed_stage_slug || "").match(/^(\d{1,2})/);
    const approvedCount = stageMatch ? parseInt(stageMatch[1], 10) : 0;
    const pct = Math.round((approvedCount / 8) * 100);
    const statusKey = project.latest_run_status || "unknown";
    const statusLabel = humanStatus(statusKey);
    const statusClass = `status-${statusKey}`;

    // Mini progress ring via inline SVG (no deps)
    const ringR = 18, ringCirc = 2 * Math.PI * ringR;
    const ringOffset = ringCirc * (1 - pct / 100);

    card.innerHTML = `
      <div class="project-card-header">
        <span class="project-card-title">${escapeHtml(project.title)}</span>
        <span class="status-chip ${statusClass}">${escapeHtml(statusLabel)}</span>
      </div>
      <div class="project-card-thesis">${escapeHtml(project.thesis)}</div>
      <div class="project-card-footer">
        <div class="project-progress">
          <svg viewBox="0 0 44 44" width="44" height="44" class="progress-ring">
            <circle cx="22" cy="22" r="${ringR}" class="ring-bg"></circle>
            <circle cx="22" cy="22" r="${ringR}"
                    class="ring-fill"
                    stroke-dasharray="${ringCirc.toFixed(2)}"
                    stroke-dashoffset="${ringOffset.toFixed(2)}"></circle>
            <text x="22" y="26" text-anchor="middle" class="ring-label">${approvedCount}/8</text>
          </svg>
          <div class="project-progress-label">
            <div class="project-progress-pct">${pct}%</div>
            <div class="project-progress-sub">${approvedCount === 0 ? "not started" : approvedCount === 8 ? "done" : "in progress"}</div>
          </div>
        </div>
        <div class="project-card-time" title="${escapeHtml(project.updated_at || project.created_at || "")}">${escapeHtml(formatRelativeTime(project.updated_at || project.created_at))}</div>
      </div>
    `;
    card.addEventListener("click", () => {
      stopPolling();
      state.selectedProjectId = project.project_id;
      renderProjects();
      renderProjectBrief();
      renderHeader();
      setView("workspace");
      const nextRunId = project.active_run_id || project.run_ids.at(-1) || null;
      if (nextRunId) {
        state.selectedRunId = nextRunId;
        void safeAction(loadRun(nextRunId).then(startPolling));
      }
    });
    elements.projectsList.appendChild(card);
  }
}

function renderRuns() {
  // The "Unattached Runs" panel was removed from the hub; this function is
  // kept as a no-op so existing callers don't need to change.
  if (!elements.runsList) return;
  elements.runCount && (elements.runCount.textContent = String(state.runIds.length));
  elements.runsList.innerHTML = "";
  for (const runId of state.runIds) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = `run-card${runId === state.selectedRunId ? " is-active" : ""}`;
    const linkedProject = state.projects.find((project) => project.run_ids.includes(runId));
    card.innerHTML = `
      <div class="run-card-title">${escapeHtml(runId)}</div>
      <div class="run-card-meta">${escapeHtml(linkedProject?.title || "Unassigned project")}</div>
    `;
    card.addEventListener("click", () => {
      void safeAction(loadRun(runId));
    });
    elements.runsList.appendChild(card);
  }
}

function renderProjectBrief() {
  const project = getSelectedProject();
  if (!project) {
    elements.projectMeta.textContent = "No project";
    renderEmpty(elements.projectBrief, "Project context appears here after you select a project.");
    return;
  }
  elements.projectMeta.textContent = `human-in-loop · ${project.run_ids.length} run(s)`;
  elements.projectBrief.classList.remove("empty-state");
  elements.projectBrief.innerHTML = `
    <p><strong>Thesis.</strong> ${escapeHtml(project.thesis)}</p>
    <p><strong>Collaboration.</strong> Human review remains in the loop for every project and every run.</p>
    <p><strong>Active run.</strong> ${escapeHtml(project.active_run_id || "None attached yet.")}</p>
    <p><strong>Latest checkpoint.</strong> ${escapeHtml(project.latest_completed_stage_slug || "No approved stages yet.")}</p>
  `;
}

function renderSummary() {
  const summary = state.runSummary;
  elements.runSummary.innerHTML = "";
  if (!summary) {
    return;
  }
  renderDefinitionList(elements.runSummary, [
    ["Model", summary.model],
    ["Venue", summary.venue],
    ["Status", summary.run_status],
    ["Updated", summary.updated_at],
    ["Current", summary.current_stage_slug || "none"],
  ]);
}

function renderArtifacts() {
  const counts = state.artifactIndex?.counts_by_category || {};
  const total = state.artifactIndex?.artifact_count || 0;
  elements.artifactTotal.textContent = `${total} artifacts`;
  elements.artifactSummary.innerHTML = "";

  const entries = Object.entries(counts);
  if (!entries.length) {
    const item = document.createElement("li");
    item.textContent = "No indexed artifacts yet.";
    elements.artifactSummary.appendChild(item);
    return;
  }

  for (const [label, count] of entries) {
    const item = document.createElement("li");
    item.textContent = `${label}: ${count}`;
    elements.artifactSummary.appendChild(item);
  }
}

function renderStages() {
  const stages = state.runSummary?.stages || [];
  elements.stageCount.textContent = String(stages.length);
  elements.stageRail.innerHTML = "";
  const currentSlug = state.runSummary?.current_stage_slug;
  for (const stage of stages) {
    const item = document.createElement("button");
    item.type = "button";
    const stateClass =
      stage.status === "running"
        ? "is-running"
        : stage.status === "human_review"
        ? "is-review"
        : stage.approved
        ? "is-approved"
        : stage.status === "failed"
        ? "is-failed"
        : "";
    const isCurrent = stage.slug === currentSlug ? " is-current" : "";
    const isSelected = stage.slug === state.selectedStageSlug ? " is-active" : "";
    item.className = `stage-item ${stateClass}${isCurrent}${isSelected}`.trim();
    const num = String(stage.number).padStart(2, "0");
    const short = shortStageTitle(stage.title);
    const attempts = stage.attempt_count > 1 ? ` · attempt ${stage.attempt_count}` : "";
    item.innerHTML = `
      <span class="stage-number">${num}</span>
      <div class="stage-body">
        <div class="stage-title">${escapeHtml(short)}</div>
        <div class="stage-meta">${escapeHtml(humanStatus(stage.status))}${escapeHtml(attempts)}</div>
      </div>
      <span class="status-chip status-${escapeHtml(stage.status)}">${escapeHtml(humanStatus(stage.status))}</span>
    `;
    item.addEventListener("click", () => {
      void safeAction(loadStageDocument(stage.slug));
    });
    elements.stageRail.appendChild(item);
  }
}

function renderStagePanels() {
  const stage = getSelectedStage();
  // No stage at all → fully empty state.
  if (!stage) {
    elements.overviewStageTitle.textContent = "Stage snapshot";
    elements.overviewStageMeta.textContent = "";
    renderEmpty(elements.overviewStageSummary, "Select a stage to inspect the current summary.");
    elements.reviewStageLabel.textContent = "Human Review";
    elements.documentTitle.textContent = "Stage document";
    elements.documentMeta.textContent = "";
    renderEmpty(elements.stageDocument, "Select a stage to inspect the human-readable summary.");
    renderReviewActions(null);
    renderReviewHero(null);
    return;
  }

  // Stage exists. The markdown may or may not exist yet (running stages
  // produce a draft we'll see when get_stage_document falls back to .tmp.md;
  // pending stages produce nothing). Always populate the hero + button labels
  // so the user can act on the stage even when its document isn't ready.
  const fullTitle = fullStageTitle(stage.number, stage.title);
  elements.overviewStageTitle.textContent = fullTitle;
  elements.overviewStageMeta.textContent = `${humanStatus(stage.status)} · attempts ${stage.attempt_count || 0}`;
  if (state.stageDocument) {
    renderMarkdown(elements.overviewStageSummary, markdownExcerpt(state.stageDocument, 22));
  } else {
    renderEmpty(elements.overviewStageSummary, statusEmptyText(stage));
  }

  elements.reviewStageLabel.textContent = `Human Review · ${stage.slug}`;
  elements.documentTitle.textContent = fullTitle;
  elements.documentMeta.textContent = `${humanStatus(stage.status)} · attempts ${stage.attempt_count || 0}`;
  if (state.stageDocument) {
    renderMarkdown(elements.stageDocument, state.stageDocument);
  } else {
    renderEmpty(elements.stageDocument, statusEmptyText(stage));
  }
  renderReviewActions(stage);
  renderReviewHero(stage);
}

function statusEmptyText(stage) {
  switch (stage.status) {
    case "running":
      return "🔄 The runner is currently drafting this stage. Output will appear here as it's written.";
    case "pending":
      return "⏳ This stage hasn't started yet. It will run after the previous stage is approved.";
    case "failed":
      return "❌ This stage failed. Check the logs.";
    default:
      return "Stage output not available yet.";
  }
}

function renderStageStrip(stages) {
  // Render the same strip into both the Overview and Review pages so the
  // pipeline state is always visible regardless of which tab you're on.
  renderStageStripInto(elements.stageStrip, stages);
  renderStageStripInto(elements.reviewStageStrip, stages);
}

function renderStageStripInto(container, stages) {
  if (!container) return;
  container.innerHTML = "";
  const selectedSlug = state.selectedStageSlug;
  for (const stage of stages) {
    const state_ =
      stage.approved ? "done" :
      stage.status === "running" ? "running" :
      stage.status === "human_review" ? "review" :
      stage.status === "failed" ? "failed" : "pending";
    const li = document.createElement("li");
    const isSelected = stage.slug === selectedSlug ? " is-selected" : "";
    li.className = `stage-strip-pill state-${state_}${isSelected}`;
    li.title = `${fullStageTitle(stage.number, stage.title)} — ${humanStatus(stage.status)}`;
    li.innerHTML = `
      <span class="stage-strip-num">${String(stage.number).padStart(2, "0")}</span>
      <span class="stage-strip-label">${escapeHtml(shortStageTitle(stage.title))}</span>
    `;
    li.addEventListener("click", () => {
      void safeAction(loadStageDocument(stage.slug));
      setPage("review");
    });
    container.appendChild(li);
  }
}

function renderPreviousStages() {
  if (!elements.reviewPreviousList) return;
  const stages = state.runSummary?.stages || [];
  const approved = stages.filter((s) => s.approved);
  elements.reviewPreviousCount.textContent = `${approved.length} approved`;
  elements.reviewPreviousList.innerHTML = "";
  if (approved.length === 0) {
    const empty = document.createElement("div");
    empty.className = "session-empty";
    empty.textContent = "No stages approved yet. They'll show up here as you approve them.";
    elements.reviewPreviousList.appendChild(empty);
    return;
  }
  for (const s of approved) {
    const details = document.createElement("details");
    details.className = "previous-stage-item";
    const num = String(s.number).padStart(2, "0");
    const when = s.approved_at || s.updated_at || "";
    details.innerHTML = `
      <summary>
        <span class="prev-num">${num}</span>
        <span class="prev-title">${escapeHtml(shortStageTitle(s.title))}</span>
        <span class="prev-meta">approved ${escapeHtml(formatShortTime(when))}${s.attempt_count > 1 ? ` · attempt ${s.attempt_count}` : ""}</span>
      </summary>
      <div class="prev-body" data-stage-slug="${escapeHtml(s.slug)}">
        <button class="button button-secondary prev-load-btn" type="button">Load full markdown</button>
      </div>
    `;
    const btn = details.querySelector(".prev-load-btn");
    btn.addEventListener("click", () => {
      void safeAction(loadStageDocument(s.slug).then(() => setPage("review")));
    });
    elements.reviewPreviousList.appendChild(details);
  }
}

function renderReviewProgressSummary() {
  if (!elements.reviewProgressSummary) return;
  const summary = state.runSummary;
  const stages = summary?.stages || [];
  const focus =
    stages.find((s) => s.status === "running") ||
    stages.find((s) => s.status === "human_review") ||
    null;
  const dot = elements.reviewProgressSummary.querySelector(".live-dot");
  if (!summary) {
    elements.reviewProgressText.textContent = "No run loaded";
    if (dot) dot.className = "live-dot";
    return;
  }
  if (summary.run_status === "completed") {
    elements.reviewProgressText.textContent = "✅ Run complete — all stages approved";
    if (dot) dot.className = "live-dot is-done";
    return;
  }
  if (summary.run_status === "failed") {
    elements.reviewProgressText.textContent = `❌ Run failed: ${summary.last_error || "unknown error"}`;
    if (dot) dot.className = "live-dot is-failed";
    return;
  }
  if (focus) {
    const latest = _latestSessionEventCache[focus.slug];
    const name = shortStageTitle(focus.title);
    if (focus.status === "running") {
      if (latest && latest.kind === "tool_use" && latest.tool) {
        const input = latest.tool.input ? JSON.stringify(latest.tool.input).slice(0, 80) : "";
        elements.reviewProgressText.textContent = `🔄 ${name}: ${latest.tool.name}(${input})`;
      } else {
        elements.reviewProgressText.textContent = `🔄 Drafting ${name}…`;
      }
      if (dot) dot.className = "live-dot is-live";
    } else {
      elements.reviewProgressText.textContent = `👀 Awaiting your review on ${name}`;
      if (dot) dot.className = "live-dot is-review";
    }
  } else {
    elements.reviewProgressText.textContent = "Waiting for activity…";
    if (dot) dot.className = "live-dot";
  }
}

function renderReviewHero(stage) {
  if (!elements.reviewHero) return;
  if (!stage) {
    elements.reviewHeroTitle.textContent = "No stage selected";
    elements.reviewHeroSub.textContent = "Pick a run to inspect a stage.";
    elements.reviewHeroChip.textContent = "idle";
    elements.reviewHeroChip.className = "status-chip status-idle";
    elements.reviewHeroTldr.innerHTML = "";
    elements.reviewHeroFiles.innerHTML = "";
    if (elements.reviewNext) elements.reviewNext.textContent = "";
    return;
  }
  const stages = state.runSummary?.stages || [];
  const reviewing = stages.find((s) => s.status === "human_review");
  const isCurrent = reviewing && reviewing.slug === stage.slug;
  const short = shortStageTitle(stage.title);
  const num = String(stage.number).padStart(2, "0");

  elements.reviewHeroTitle.textContent = `Stage ${num} · ${short}`;
  const attemptText = stage.attempt_count > 1 ? ` · attempt ${stage.attempt_count}` : "";
  elements.reviewHeroSub.textContent = isCurrent
    ? `${humanStatus(stage.status)}${attemptText}`
    : stage.approved
    ? `Approved on attempt ${stage.attempt_count}`
    : `${humanStatus(stage.status)}${attemptText}`;

  elements.reviewHeroChip.textContent = humanStatus(stage.status);
  elements.reviewHeroChip.className = `status-chip status-${stage.status}`;

  // TL;DR: first paragraph of "Key Results" or "What I Did" extracted from the markdown.
  const tldr = extractTldr(state.stageDocument);
  elements.reviewHeroTldr.textContent = tldr || "Review the full stage document below before approving.";

  // Files produced list — from manifest's artifact_paths
  elements.reviewHeroFiles.innerHTML = "";
  const files = stage.artifact_paths || [];
  if (files.length) {
    for (const f of files.slice(0, 6)) {
      const li = document.createElement("li");
      li.innerHTML = `<span class="file-icon">📄</span><code>${escapeHtml(f)}</code>`;
      elements.reviewHeroFiles.appendChild(li);
    }
  }

  // Next-step hint
  if (elements.reviewNext) {
    if (isCurrent) {
      const nextIdx = stages.findIndex((s) => s.slug === stage.slug) + 1;
      const next = stages[nextIdx];
      elements.reviewNext.textContent = next
        ? `→ Approving advances the runner to Stage ${String(next.number).padStart(2, "0")}: ${shortStageTitle(next.title)}.`
        : `→ Approving marks the entire run as completed.`;
    } else {
      elements.reviewNext.textContent = reviewing
        ? `ⓘ This stage is already ${humanStatus(stage.status).toLowerCase()}. The runner is currently awaiting review on Stage ${String(reviewing.number).padStart(2, "0")}: ${shortStageTitle(reviewing.title)}.`
        : "";
    }
  }
}

// Extract a short TL;DR from the stage markdown — the first ~2 sentences of
// the "What I Did" or "Key Results" section, or the first paragraph if those
// are missing.
function extractTldr(md) {
  if (!md) return "";
  const sections = md.split(/^##\s+/m);
  for (const prefer of ["Key Results", "What I Did"]) {
    const match = sections.find((s) => s.trimStart().startsWith(prefer));
    if (match) {
      const body = match.replace(prefer, "").trim();
      const paragraphs = body.split(/\n\s*\n/).filter((p) => p.trim() && !p.trim().startsWith("#"));
      if (paragraphs.length) {
        const clean = paragraphs[0]
          .replace(/[-*]\s*/g, "")
          .replace(/\s+/g, " ")
          .trim();
        return clean.length > 260 ? clean.slice(0, 260) + "…" : clean;
      }
    }
  }
  const first = md.split(/\n\s*\n/).find((p) => p.trim() && !p.trim().startsWith("#"));
  return first ? first.replace(/\s+/g, " ").trim().slice(0, 260) : "";
}

function renderReviewActions(stage) {
  // Make the Review-page Approve/Feedback buttons name the stage they act
  // on and disable them only when no stage is actionable (a stage is
  // "actionable" if it's awaiting review OR has failed validation/execution
  // — both have a draft on disk the human can act on).
  if (!elements.approveStageButton) return;
  const actionable = findActionableStage();
  const targetsThisStage = actionable && stage && actionable.slug === stage.slug;
  const atReview = !!actionable;
  const short = stage ? shortStageTitle(stage.title) : "";
  const isFailedAction = actionable && actionable.status === "failed";
  const isRunningOrphan = actionable && actionable.status === "running";

  if (isRunningOrphan && targetsThisStage) {
    // Stage is "running" but the worker may be dead (server crashed).
    // Offer Resume (which triggers lazy-resume on the backend) and
    // Feedback (which restarts the stage with instructions).
    elements.approveStageButton.textContent = `🔄 Resume ${short}`;
    elements.approveStageButton.disabled = false;
    elements.approveStageButton.title = "The runner may have crashed. Click to resume from where it left off.";
    elements.sendFeedbackButton.textContent = `🔁 Restart ${short} with feedback`;
    elements.sendFeedbackButton.disabled = false;
    elements.sendFeedbackButton.title = "";
  } else if (atReview && targetsThisStage) {
    const stages = state.runSummary?.stages || [];
    const idx = stages.findIndex((s) => s.slug === stage.slug);
    const next = stages[idx + 1];
    const nextShort = next ? shortStageTitle(next.title) : "finish";
    elements.approveStageButton.textContent = isFailedAction
      ? `⚠️ Approve anyway → Advance to ${nextShort}`
      : (next
          ? `✅ Approve → Advance to ${nextShort}`
          : `✅ Approve → Finish run`);
    elements.approveStageButton.disabled = false;
    elements.approveStageButton.title = isFailedAction
      ? "This stage failed validation or execution. Approving will promote the existing draft and advance anyway."
      : "";
    elements.sendFeedbackButton.textContent = isFailedAction
      ? `🔁 Retry ${short} with feedback`
      : `✍︎ Re-run ${short} with feedback`;
    elements.sendFeedbackButton.disabled = false;
    elements.sendFeedbackButton.title = "";
  } else if (atReview && !targetsThisStage) {
    // User is viewing a different stage than the one awaiting review. Let
    // approve jump focus; feedback still applies to the actionable stage so
    // keep it enabled.
    const reviewingShort = shortStageTitle(actionable.title);
    elements.approveStageButton.textContent = `↗ Jump to ${reviewingShort}`;
    elements.approveStageButton.disabled = false;
    elements.approveStageButton.title = `${isFailedAction ? "Failed" : "Currently awaiting review"} on ${reviewingShort}. Click to focus that stage.`;
    elements.sendFeedbackButton.textContent = `✍︎ Send Feedback to ${reviewingShort}`;
    elements.sendFeedbackButton.disabled = false;
    elements.sendFeedbackButton.title = `Feedback will re-run ${reviewingShort}, not the stage you're currently viewing.`;
  } else {
    // Nothing is awaiting review. Two sub-cases worth distinguishing:
    //   (a) the run is still running on a stage that hasn't reached
    //       human_review yet — show "Runner busy on …" so the user knows
    //       to wait, not to think their last approve didn't register.
    //   (b) the run is fully completed/failed.
    const stages = state.runSummary?.stages || [];
    const busy = stages.find((s) => s.status === "running");
    const runStatus = state.runSummary?.run_status;
    if (busy) {
      const busyShort = shortStageTitle(busy.title);
      elements.approveStageButton.textContent = `⏳ Runner busy on ${busyShort}`;
      elements.approveStageButton.title = `Wait for ${busyShort} to reach human review.`;
    } else if (runStatus === "completed") {
      elements.approveStageButton.textContent = "✅ Run completed";
      elements.approveStageButton.title = "All stages approved.";
    } else if (runStatus === "failed") {
      elements.approveStageButton.textContent = "❌ Run failed";
      elements.approveStageButton.title = state.runSummary?.last_error || "Run failed.";
    } else {
      elements.approveStageButton.textContent = stage ? `✅ ${stage.approved ? "Approved" : "Approve"} ${short}` : "✅ Approve & Continue";
      elements.approveStageButton.title = "Nothing is awaiting review right now.";
    }
    elements.approveStageButton.disabled = true;
    elements.sendFeedbackButton.textContent = busy
      ? `✍︎ Wait for ${shortStageTitle(busy.title)}`
      : "✍︎ Send Feedback & Re-run";
    elements.sendFeedbackButton.disabled = true;
    elements.sendFeedbackButton.title = "";
  }
}

function renderIterationForm() {
  elements.iterationStage.innerHTML = "";
  for (const stage of state.runSummary?.stages || []) {
    const option = document.createElement("option");
    option.value = stage.slug;
    option.textContent = stage.title;
    if (stage.slug === state.selectedStageSlug) {
      option.selected = true;
    }
    elements.iterationStage.appendChild(option);
  }
  elements.iterationScopeValue.value = state.selectedStageSlug || "";
  renderIterationPlan();
}

function renderIterationPlan() {
  if (!state.iterationPlan) {
    renderIterationPlaceholder("No iteration brief generated yet.");
    return;
  }

  const plan = state.iterationPlan;
  elements.iterationPlan.classList.remove("empty-state");
  elements.iterationPlan.innerHTML = `
    <p class="plan-summary">${escapeHtml(plan.summary)}</p>
    <div class="plan-grid">
      <div>Preserved</div>
      <strong>${escapeHtml(plan.preserved_stages.join(", ") || "none")}</strong>
      <div>Affected</div>
      <strong>${escapeHtml(plan.affected_stages.join(", ") || "none")}</strong>
      <div>Stale</div>
      <strong>${escapeHtml(plan.stale_stages.join(", ") || "none")}</strong>
      <div>Branch run</div>
      <strong>${escapeHtml(plan.branch_run_id || "current run")}</strong>
    </div>
    <pre class="brief-block">${escapeHtml(plan.operator_brief)}</pre>
  `;
}

function renderFileTree() {
  // File tree moved into the Notebook view; bail when DOM is absent.
  if (!elements.fileTree) return;
  elements.fileTree.innerHTML = "";
  if (!state.fileTree) {
    return;
  }
  elements.fileTree.appendChild(renderTreeNode(state.fileTree));
  renderFilePreview();
}

function renderTreeNode(node) {
  const wrapper = document.createElement("div");
  wrapper.className = "tree-node";

  const label = document.createElement("button");
  label.type = "button";
  label.className = `tree-label${node.rel_path === state.selectedFilePath ? " is-active" : ""}`;
  label.textContent = `${node.node_type === "directory" ? "▾" : "•"} ${node.name}`;
  if (node.node_type === "file") {
    label.addEventListener("click", () => {
      void safeAction(loadFileContent(node.rel_path));
    });
  } else {
    label.disabled = true;
  }
  wrapper.appendChild(label);

  if (node.children?.length) {
    const children = document.createElement("div");
    children.className = "tree-children";
    for (const child of node.children) {
      children.appendChild(renderTreeNode(child));
    }
    wrapper.appendChild(children);
  }

  return wrapper;
}

function renderFilePreview() {
  // Files panel was folded into Notebook; bail when DOM is absent.
  if (!elements.filePreview) return;
  const preview = state.filePreview;
  if (!preview) {
    elements.filePreviewTitle.textContent = "File preview";
    elements.filePreviewMeta.textContent = "";
    renderEmpty(elements.filePreview, "Select a file from the workspace tree to preview it here.");
    return;
  }

  elements.filePreviewTitle.textContent = preview.relative_path;
  elements.filePreviewMeta.textContent = `${preview.encoding} · ${preview.size_bytes} bytes`;

  if (preview.encoding === "binary") {
    renderEmpty(elements.filePreview, "Binary file preview is unavailable in the browser.");
    return;
  }

  if (preview.relative_path.endsWith(".md")) {
    renderMarkdown(elements.filePreview, preview.content);
    return;
  }

  if (preview.relative_path.endsWith(".json")) {
    const pretty = tryPrettyJson(preview.content);
    renderCode(elements.filePreview, pretty);
    return;
  }

  renderCode(elements.filePreview, preview.content);
}

function renderPaperPreview() {
  // Paper panel was folded into Notebook; bail when DOM is absent.
  if (!elements.paperSummary) return;
  const preview = state.paperPreview;
  elements.paperSummary.innerHTML = "";
  elements.paperSections.innerHTML = "";

  if (!preview) {
    elements.paperStatus.textContent = "No PDF yet";
    elements.paperMeta.textContent = "";
    renderEmpty(elements.paperFrameContainer, "Select a run with writing artifacts to preview the paper.");
    renderEmpty(elements.paperTexPreview, "No manuscript source found.");
    renderEmpty(elements.paperBuildLog, "No build log found.");
    _paperRenderedKey.ref = "";
    return;
  }

  // A markdown run has no PDF by design, so reporting "TeX only" for it would read as a
  // failed build rather than the configured output format.
  const isMarkdownRun = preview.output_format === "markdown";
  if (isMarkdownRun) {
    elements.paperStatus.textContent = preview.report_available ? "Report ready" : "No report yet";
  } else {
    elements.paperStatus.textContent = preview.pdf_available ? "PDF ready" : "TeX only";
  }
  elements.paperMeta.textContent =
    (isMarkdownRun ? preview.report_relative_path : null) ||
    preview.pdf_relative_path ||
    preview.tex_relative_path ||
    "No manuscript files";
  renderDefinitionList(elements.paperSummary, isMarkdownRun
    ? [
        ["Output format", "markdown"],
        ["Report", preview.report_relative_path || "missing"],
      ]
    : [
        ["Main TeX", preview.tex_relative_path || "missing"],
        ["Compiled PDF", preview.pdf_relative_path || "missing"],
        ["Sections", String(preview.section_paths.length)],
        ["Build log", preview.build_log_relative_path || "missing"],
      ]);

  if (preview.section_paths.length) {
    elements.paperSections.innerHTML = preview.section_paths
      .map((path) => `<li>${escapeHtml(path)}</li>`)
      .join("");
  } else {
    elements.paperSections.innerHTML = "<li>No section files found.</li>";
  }

  // Only (re)mount the iframe when the (run, pdf_available) key changes.
  // Polling re-runs this function every 800ms; if we unconditionally reset
  // innerHTML the iframe tears down and re-downloads the PDF each tick,
  // which manifests as a visible flashing/reloading preview.
  const pdfKey = preview.pdf_available && state.selectedRunId
    ? `${state.selectedRunId}|ready`
    : "none";
  if (pdfKey !== _paperRenderedKey.ref) {
    if (preview.pdf_available && state.selectedRunId) {
      elements.paperFrameContainer.classList.remove("empty-state");
      elements.paperFrameContainer.innerHTML = `
        <iframe
          class="paper-frame"
          src="/api/runs/${encodeURIComponent(state.selectedRunId)}/paper/pdf"
          title="Compiled paper preview"
        ></iframe>
      `;
    } else if (isMarkdownRun) {
      renderEmpty(elements.paperFrameContainer, "This run produces a markdown report. The report source is shown below.");
    } else {
      renderEmpty(elements.paperFrameContainer, "No compiled PDF found yet. Main TeX and build logs can still be reviewed here.");
    }
    _paperRenderedKey.ref = pdfKey;
  }

  const manuscriptSource = isMarkdownRun ? preview.report_content : preview.tex_content;
  if (manuscriptSource) {
    renderCode(elements.paperTexPreview, manuscriptSource);
  } else {
    renderEmpty(
      elements.paperTexPreview,
      isMarkdownRun ? "No report.md found yet." : "No manuscript source found.",
    );
  }

  if (preview.build_log_content) {
    renderCode(elements.paperBuildLog, preview.build_log_content);
  } else {
    renderEmpty(elements.paperBuildLog, "No build log found.");
  }
}

function renderHistory() {
  const history = state.history;
  elements.versionList.innerHTML = "";
  elements.historyArtifacts.innerHTML = "";
  elements.traceTimeline.innerHTML = "";

  if (!history) {
    elements.versionCount.textContent = "0";
    elements.traceCount.textContent = "0 events";
    elements.historyTitle.textContent = "Version detail";
    elements.historyMeta.textContent = "";
    renderEmpty(elements.historySummary, "Select a checkpoint to inspect its stage summary and changed artifacts.");
    renderEmpty(elements.historyStagePreview, "Select a checkpoint to preview its associated stage summary.");
    return;
  }

  elements.versionCount.textContent = String(history.versions.length);
  elements.traceCount.textContent = `${history.trace_events.length} events`;

  for (const version of history.versions) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `version-card${version.version_id === state.selectedVersionId ? " is-active" : ""}`;
    item.innerHTML = `
      <div class="version-card-header">
        <span class="version-card-title">${escapeHtml(version.label)}</span>
        <span class="pill">${escapeHtml(version.kind.replaceAll("_", " "))}</span>
      </div>
      <div class="run-card-meta">${escapeHtml(version.created_at)}</div>
      <div class="run-card-meta">${escapeHtml(version.stage_title || "Run-wide checkpoint")}</div>
    `;
    item.addEventListener("click", () => {
      state.selectedVersionId = version.version_id;
      renderHistory();
      if (version.stage_slug) {
        void safeAction(loadStageDocument(version.stage_slug));
      }
    });
    elements.versionList.appendChild(item);
  }

  const selectedVersion = getSelectedVersion();
  if (!selectedVersion) {
    renderEmpty(elements.historySummary, "Select a checkpoint to inspect its stage summary and changed artifacts.");
    renderEmpty(elements.historyStagePreview, "Select a checkpoint to preview its associated stage summary.");
  } else {
    elements.historyTitle.textContent = selectedVersion.label;
    elements.historyMeta.textContent = `${selectedVersion.kind.replaceAll("_", " ")} · ${selectedVersion.created_at}`;
    elements.historySummary.classList.remove("empty-state");
    elements.historySummary.innerHTML = `
      <p><strong>Checkpoint type.</strong> ${escapeHtml(selectedVersion.kind.replaceAll("_", " "))}</p>
      <p><strong>Stage.</strong> ${escapeHtml(selectedVersion.stage_title || "Run-wide checkpoint")}</p>
      <p><strong>Notes.</strong> ${escapeHtml(selectedVersion.notes)}</p>
      <p><strong>Session.</strong> ${escapeHtml(selectedVersion.session_id || "not recorded")}</p>
    `;

    if (selectedVersion.artifact_paths.length) {
      elements.historyArtifacts.innerHTML = selectedVersion.artifact_paths
        .slice(0, 12)
        .map((path) => `<li>${escapeHtml(path)}</li>`)
        .join("");
    } else {
      elements.historyArtifacts.innerHTML = "<li>No artifacts recorded for this checkpoint.</li>";
    }

    const selectedStage = state.runSummary?.stages.find((stage) => stage.slug === selectedVersion.stage_slug) || null;
    if (selectedStage && selectedVersion.stage_slug === state.selectedStageSlug && state.stageDocument) {
      renderMarkdown(elements.historyStagePreview, markdownExcerpt(state.stageDocument, 28));
    } else if (selectedVersion.stage_slug) {
      renderEmpty(elements.historyStagePreview, "Open this checkpoint to preview its stage summary here.");
    } else {
      renderEmpty(elements.historyStagePreview, "This checkpoint is run-wide and has no single stage summary attached.");
    }
  }

  for (const event of history.trace_events) {
    const item = document.createElement("div");
    item.className = `trace-item status-${event.status}`;
    item.innerHTML = `
      <div class="trace-time">${escapeHtml(event.timestamp)}</div>
      <div class="trace-card">
        <div class="trace-title-row">
          <span class="trace-title">${escapeHtml(event.title)}</span>
          <span class="pill">${escapeHtml(event.actor)}</span>
        </div>
        <div class="run-card-meta">${escapeHtml(event.detail)}</div>
      </div>
    `;
    elements.traceTimeline.appendChild(item);
  }
}

function renderWorkspaceSkeleton(message) {
  renderHeader();
  renderProjectBrief();
  renderEmpty(elements.overviewStageSummary, message);
  renderEmpty(elements.stageDocument, message);
  // filePreview / paperFrameContainer / paperTexPreview / paperBuildLog
  // were folded into the Notebook view; renderEmpty no-ops when the element
  // is missing.
  renderEmpty(elements.filePreview, "Select a file from the workspace tree to preview it here.");
  renderEmpty(elements.paperFrameContainer, "Select a run with writing artifacts to preview the paper.");
  renderEmpty(elements.paperTexPreview, "No manuscript source found.");
  renderEmpty(elements.paperBuildLog, "No build log found.");
  renderEmpty(elements.historySummary, "Select a checkpoint to inspect its stage summary and changed artifacts.");
  renderEmpty(elements.historyStagePreview, "Select a checkpoint to preview its associated stage summary.");
  const setEmpty = (node, html = "") => {
    if (node) node.innerHTML = html;
  };
  const setText = (node, text) => {
    if (node) node.textContent = text;
  };
  setText(elements.versionCount, "0");
  setText(elements.traceCount, "0 events");
  setEmpty(elements.runSummary);
  setEmpty(elements.artifactSummary);
  setEmpty(elements.stageRail);
  setEmpty(elements.fileTree);
  setEmpty(elements.versionList);
  setEmpty(elements.historyArtifacts);
  setEmpty(elements.traceTimeline);
  renderIterationPlaceholder("No iteration brief generated yet.");
}

function clearRunState() {
  state.selectedRunId = null;
  state.selectedStageSlug = null;
  state.selectedFilePath = null;
  state.selectedVersionId = null;
  state.runSummary = null;
  state.artifactIndex = null;
  state.fileTree = null;
  state.stageDocument = "";
  state.filePreview = null;
  state.paperPreview = null;
  state.history = null;
  state.iterationPlan = null;
}

function renderIterationPlaceholder(message) {
  renderEmpty(elements.iterationPlan, message);
}

function renderDefinitionList(target, rows) {
  target.innerHTML = "";
  for (const [label, value] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    target.append(dt, dd);
  }
}

function renderMarkdown(element, markdown) {
  if (!markdown?.trim()) {
    renderEmpty(element, "Nothing to preview yet.");
    return;
  }
  element.classList.remove("empty-state");
  element.classList.add("markdown-body");
  element.innerHTML = markdownToHtml(markdown);
}

function renderCode(element, content) {
  if (!content?.length) {
    renderEmpty(element, "Nothing to preview yet.");
    return;
  }
  element.classList.remove("empty-state");
  element.classList.remove("markdown-body");
  element.innerHTML = `<pre>${escapeHtml(content)}</pre>`;
}

function renderEmpty(element, message) {
  // Several consumers (renderWorkspaceSkeleton, renderFilePreview, renderPaperPreview)
  // refer to elements that were folded into the Notebook view and no longer
  // exist in the DOM. Bail silently in that case.
  if (!element) return;
  element.classList.remove("markdown-body");
  element.classList.add("empty-state");
  element.textContent = message;
}

function markdownToHtml(markdown) {
  const lines = markdown.replaceAll("\r", "").split("\n");
  const blocks = [];
  let paragraph = [];
  let listItems = [];
  let listKind = null;
  let codeFence = null;
  let codeLines = [];

  const flushParagraph = () => {
    if (!paragraph.length) {
      return;
    }
    blocks.push(`<p>${formatInline(paragraph.join(" "))}</p>`);
    paragraph = [];
  };

  const flushList = () => {
    if (!listItems.length || !listKind) {
      return;
    }
    blocks.push(`<${listKind}>${listItems.map((item) => `<li>${formatInline(item)}</li>`).join("")}</${listKind}>`);
    listItems = [];
    listKind = null;
  };

  const flushCode = () => {
    if (codeFence === null) {
      return;
    }
    blocks.push(`<pre>${escapeHtml(codeLines.join("\n"))}</pre>`);
    codeFence = null;
    codeLines = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();

    if (line.startsWith("```")) {
      flushParagraph();
      flushList();
      if (codeFence === null) {
        codeFence = line.slice(3).trim();
      } else {
        flushCode();
      }
      continue;
    }

    if (codeFence !== null) {
      codeLines.push(rawLine);
      continue;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      flushList();
      const level = headingMatch[1].length;
      blocks.push(`<h${level}>${formatInline(headingMatch[2])}</h${level}>`);
      continue;
    }

    const orderedMatch = line.match(/^\d+\.\s+(.*)$/);
    if (orderedMatch) {
      flushParagraph();
      if (listKind && listKind !== "ol") {
        flushList();
      }
      listKind = "ol";
      listItems.push(orderedMatch[1]);
      continue;
    }

    const bulletMatch = line.match(/^[-*]\s+(.*)$/);
    if (bulletMatch) {
      flushParagraph();
      if (listKind && listKind !== "ul") {
        flushList();
      }
      listKind = "ul";
      listItems.push(bulletMatch[1]);
      continue;
    }

    const quoteMatch = line.match(/^>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      flushList();
      blocks.push(`<blockquote>${formatInline(quoteMatch[1])}</blockquote>`);
      continue;
    }

    paragraph.push(line.trim());
  }

  flushParagraph();
  flushList();
  flushCode();
  return blocks.join("");
}

function formatInline(value) {
  return escapeHtml(value)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function markdownExcerpt(markdown, maxLines) {
  const lines = markdown.replaceAll("\r", "").split("\n").filter((line) => line.trim());
  if (lines.length <= maxLines) {
    return markdown;
  }
  return `${lines.slice(0, maxLines).join("\n")}\n\n...`;
}

function tryPrettyJson(content) {
  try {
    return JSON.stringify(JSON.parse(content), null, 2);
  } catch {
    return content;
  }
}

function setPage(page) {
  if (!PAGE_IDS.includes(page)) {
    return;
  }
  state.page = page;
  if (window.location.hash !== `#${page}`) {
    window.location.hash = page;
  }
  renderPageNav();
}

function renderPageNav() {
  for (const button of elements.pageButtons) {
    const isActive = button.dataset.page === state.page;
    button.classList.toggle("is-active", isActive);
    button.setAttribute("aria-selected", String(isActive));
  }
  for (const [page, element] of Object.entries(elements.pages)) {
    element.classList.toggle("is-active", page === state.page);
  }
}

function getSelectedProject() {
  return state.projects.find((project) => project.project_id === state.selectedProjectId) || null;
}

function getSelectedStage() {
  return state.runSummary?.stages.find((stage) => stage.slug === state.selectedStageSlug) || null;
}

function getSelectedVersion() {
  return state.history?.versions.find((version) => version.version_id === state.selectedVersionId) || null;
}

function readHashPage() {
  const raw = window.location.hash.replace(/^#/, "");
  if (LEGACY_PAGE_REDIRECTS[raw]) {
    return LEGACY_PAGE_REDIRECTS[raw];
  }
  return PAGE_IDS.includes(raw) ? raw : "overview";
}

function setConnection(text) {
  elements.connectionStatus.textContent = text;
  const t = (text || "").toLowerCase();
  let status = "connecting";
  if (t.includes("error")) status = "error";
  else if (t.includes("idle") || t.includes("ready") || t.includes("connected") || t.includes("ok")) status = "ok";
  elements.connectionStatus.dataset.status = status;
}

async function safeAction(promise) {
  try {
    await promise;
  } catch (error) {
    console.error(error);
    setConnection("Error");
    renderWorkspaceSkeleton(error.message || "Unexpected studio error.");
  }
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    method: options.method || "GET",
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return response.json();
}

// ---------- Toast notifications ----------
let _toastContainer = null;
function showToast(message, level = "info", timeout = 3200) {
  if (!_toastContainer) {
    _toastContainer = document.createElement("div");
    _toastContainer.className = "toast-stack";
    document.body.appendChild(_toastContainer);
  }
  const t = document.createElement("div");
  t.className = `toast toast-${level}`;
  t.textContent = message;
  _toastContainer.appendChild(t);
  // Animate in on next frame
  requestAnimationFrame(() => t.classList.add("toast-visible"));
  setTimeout(() => {
    t.classList.remove("toast-visible");
    setTimeout(() => t.remove(), 260);
  }, timeout);
}

// ---------- Button loading state ----------
// IMPORTANT: clearButtonLoading must NOT restore the previous label. After a
// successful POST we always re-run the renderer (loadRun → render*), which
// is the source of truth for the button text. If we restored the saved label
// here, we'd overwrite the renderer's correct new label and the button would
// stay looking clickable even though the action succeeded — making it feel
// like the click did nothing.
function setButtonLoading(btn, loadingLabel = "Working…") {
  if (!btn) return;
  // Remember the original label only as a fallback for the error path; the
  // happy path leaves it untouched and the renderer overwrites it.
  if (!btn.dataset.fallbackLabel) btn.dataset.fallbackLabel = btn.textContent;
  btn.disabled = true;
  btn.classList.add("is-loading");
  btn.textContent = loadingLabel;
}
function clearButtonLoading(btn, { restoreLabel = false } = {}) {
  if (!btn) return;
  btn.classList.remove("is-loading");
  btn.disabled = false;
  // Only restore the saved label if explicitly asked (error path). The
  // normal post-success path lets the renderer own the label.
  if (restoreLabel && btn.dataset.fallbackLabel) {
    btn.textContent = btn.dataset.fallbackLabel;
  }
  delete btn.dataset.fallbackLabel;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
