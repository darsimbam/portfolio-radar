const app = document.querySelector("#app");
let model;
let currentPage = "dashboard";
let selectedCompany = null;
let selectedTemplate = "discovery";
let searchTerm = "";
let categoryFilter = "All";
let monitoringPollTimer = null;
let csrfToken = null;
let authenticationRequired = false;
let navigationInstalled = false;

const esc = value => String(value ?? "").replace(/[&<>"']/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const companyFor = id => model.companies.find(company => company.id === id);
const toast = message => {
  const node = document.querySelector("#toast");
  node.textContent = message;
  node.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => node.classList.remove("show"), 2400);
};
const pageName = page => ({ dashboard: "Overview", discover: "Discovery", trackers: "Company trackers", detail: "Company tracker", notes: "Notes & watchlists", templates: "Review templates" }[page]);
const companyLogo = company => `<span class="company-logo">${esc(company.ticker)}</span>`;
const badgeClass = company => company.signalTone === "warning" ? "warning" : company.signalTone === "positive" ? "positive" : "";

async function request(path, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Content-Type", "application/json");
  if (csrfToken && options.method && options.method.toUpperCase() !== "GET") headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(path, { ...options, headers });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || "Request failed.");
    error.status = response.status;
    if (response.status === 401 && data.authRequired) {
      csrfToken = null;
      model = null;
      authenticationRequired = true;
      renderLogin();
    }
    throw error;
  }
  if (data.csrfToken) csrfToken = data.csrfToken;
  return data;
}

function go(page, companyId) {
  currentPage = page;
  if (companyId) selectedCompany = companyId;
  document.querySelector("#page-crumb").textContent = pageName(page);
  document.querySelectorAll("[data-page]").forEach(button => button.classList.toggle("active", button.dataset.page === page || (page === "detail" && button.dataset.page === "trackers")));
  render();
}

function dashboardView() {
  const dashboard = model.dashboard;
  const monitoring = model.monitoring;
  const monitoringEnabled = monitoring.enabled;
  const monitoringBusy = monitoring.status === "running";
  const monitoringStatusText = monitoringBusy ? "Run in progress" : monitoringEnabled ? monitoring.status.replaceAll("_", " ") : "Paused · local demo";
  const nextRunText = monitoring.nextRunAt ? new Date(monitoring.nextRunAt).toLocaleString() : "Not scheduled";
  const priorities = dashboard.priorities.map(item => {
    const company = companyFor(item.companyId);
    return `<div class="priority-row"><span class="priority-icon">${esc(company.ticker)}</span><div><strong>${esc(item.label)}</strong><small>${esc(company.name)} · ${esc(item.detail)}</small></div><button class="btn" data-open-company="${company.id}">Open →</button></div>`;
  }).join("");
  const events = model.events.map(event => `<div class="event-row"><span class="event-date">${esc(event.date)}</span><div><strong>${esc(event.title)}</strong><small>${esc(event.detail)}</small><span class="event-tag">${esc(event.kind)}</span></div></div>`).join("");
  const savedWatchlist = model.companies.filter(company => model.watchlist.includes(company.id));
  return `<div class="heading-row"><div><div class="eyebrow">Wednesday · research desk</div><h1 class="page-title">Good evening, Research desk.</h1><p class="subtitle">A calm view of what needs attention across your coverage.</p></div><div class="date-label">07 OCT 2026 · DEMO</div></div>
    <div class="about-banner"><strong>Fictional seed data.</strong> Companies, metrics, events and seeded findings are invented. When configured, manual OpenAI runs analyze only a selected seed tracker and are shown separately; they are not verified or live-source research.</div>
    <div class="summary-grid">
      <div class="summary-card"><div class="summary-head"><span>Priority items</span><span class="summary-icon">↗</span></div><div class="summary-value">${dashboard.priorityCount.toString().padStart(2, "0")}</div><div class="summary-foot">Across your sample coverage</div></div>
      <div class="summary-card"><div class="summary-head"><span>Data freshness</span><span class="summary-icon">◷</span></div><div class="summary-value" style="font-size:15px;margin:12px 0 5px">Sample only</div><div class="summary-foot">Not connected to a live feed</div></div>
      <div class="summary-card"><div class="summary-head"><span>Coverage</span><span class="summary-icon">◎</span></div><div class="summary-value">${model.companies.length.toString().padStart(2, "0")}</div><div class="summary-foot">Fictional company trackers</div></div>
      <div class="summary-card"><div class="summary-head"><span>Monitoring</span><span class="summary-icon">⌁</span></div><div class="summary-value" style="font-size:15px;margin:12px 0 5px">${monitoringEnabled ? "Enabled" : "Paused"}</div><div class="summary-foot">${monitoringEnabled ? "Daily · saved watchlist" : model.researchRuns.length ? "Manual analysis only · no schedule" : "Local demo · no agent runs"}</div></div>
    </div>
    <div class="dashboard-grid"><section class="panel priority-panel"><div class="panel-heading"><div><h2 class="section-title">Priority queue</h2><div class="section-sub">Your next best research actions</div></div><button class="text-link" data-page="trackers">All trackers →</button></div><div class="priority-list">${priorities}</div></section>
    <section class="panel events-panel"><div class="panel-heading"><div><h2 class="section-title">Coming up</h2><div class="section-sub">Sample calendar · verify dates independently</div></div><span class="section-sub">OCT</span></div><div class="event-list">${events}</div></section></div>
    <div class="lower-grid"><section class="panel monitor-card"><div class="panel-heading"><div><h2 class="section-title">Monitoring status</h2><div class="section-sub">Opt-in · saved watchlist only</div></div><span class="status-badge ${monitoringEnabled ? "status-active" : ""}">● &nbsp;${monitoringEnabled ? (monitoringBusy ? "RUNNING" : "ENABLED") : "PAUSED"}</span></div><div class="monitor-status"><strong style="font-size:11px">${esc(monitoringStatusText)}</strong></div><div class="monitor-note">${monitoringEnabled ? "A local background scheduler analyzes saved-watchlist trackers daily at 09:00 local time. Only tracker data is sent to OpenAI; no external sources are searched. Pausing stops future runs; an in-progress run completes." : model.integrations.openai.configured ? "No scheduled research is running. Enable to send saved-watchlist tracker data to OpenAI each day at 09:00 local time." : "Scheduled monitoring requires a locally configured OPENAI_API_KEY. This workspace makes no scheduled provider calls."}</div><div class="agent-status"><span>Next scheduled run</span><span>${esc(nextRunText)}</span></div><div class="agent-status"><span>Last completed</span><span>${monitoring.lastCompletedAt ? esc(new Date(monitoring.lastCompletedAt).toLocaleString()) : "NEVER"}</span></div>${monitoring.lastError ? `<div class="monitor-error">${esc(monitoring.lastError)}</div>` : ""}${monitoring.lastOutcomes.length ? `<div class="monitor-outcomes">${monitoring.lastOutcomes.map(outcome => `<span class="tag ${outcome.status === "failed" ? "warning" : "positive"}">${esc(outcome.companyId)} · ${esc(outcome.status)}</span>`).join("")}</div>` : ""}<div class="quick-actions">${monitoringEnabled ? `<button class="btn" data-monitoring="disable">Pause schedule</button>` : `<button class="btn btn-primary" data-monitoring="enable" ${model.integrations.openai.configured ? "" : "disabled"}>Enable daily monitoring</button>`}<button class="btn" data-monitoring="run" ${model.integrations.openai.configured && model.watchlist.length && !monitoringBusy ? "" : "disabled"}>Run now</button><button class="btn" data-page="templates">Weekly review</button></div></section>
    <section class="panel watchlist-strip"><h2 class="section-title">Your watchlist</h2><div class="section-sub">Saved companies · local to this browser</div><div class="watchlist-items">${savedWatchlist.length ? savedWatchlist.map(company => `<button class="ticker-chip" data-open-company="${company.id}">${esc(company.ticker)} &nbsp;↗</button>`).join("") : `<span class="section-sub">No companies saved yet.</span>`}</div><button class="text-link" style="margin-top:14px" data-page="notes">Manage watchlist →</button></section></div>`;
}

function discoveryView() {
  const categories = ["All", "Discovery", "Earnings", "Deterioration"];
  const results = model.discoveries.filter(item => {
    const company = companyFor(item.companyId);
    return (categoryFilter === "All" || item.category === categoryFilter) && `${company.name} ${item.finding} ${item.category}`.toLowerCase().includes(searchTerm.toLowerCase());
  });
  return `<div class="heading-row"><div><div class="eyebrow">Signal notebook · fictional</div><h1 class="page-title">Discovery</h1><p class="subtitle">Search brief findings, then expand evidence and source context.</p></div><button class="btn" data-page="templates">Browse templates</button></div>
    <div class="about-banner">Sample findings are simulated, not live research. Each evidence panel separates <strong>facts, assumptions and interpretation</strong>, with fictional source labels and timestamps.</div>
    <div class="search-bar"><input class="search-input" id="discovery-search" placeholder="Search companies or findings…" value="${esc(searchTerm)}" aria-label="Search discovery"><select class="select-input" id="category-filter" aria-label="Filter by category">${categories.map(category => `<option ${category === categoryFilter ? "selected" : ""}>${category}</option>`).join("")}</select></div>
    <div class="discovery-grid">${results.length ? results.map((item, index) => {
      const company = companyFor(item.companyId);
      return `<article class="panel discovery-card"><div class="card-top"><div class="company-title">${companyLogo(company)}<div><div class="company-name">${esc(company.name)}</div><div class="company-meta">${esc(company.ticker)} · ${esc(company.sector)}</div></div></div><span class="tag ${item.category === "Deterioration" ? "warning" : item.category === "Earnings" ? "positive" : ""}">${esc(item.category)}</span></div><p class="finding">${esc(item.finding)}</p><div class="card-bottom"><span class="confidence">Confidence · <b>${esc(item.confidence)}</b></span><button class="text-link" data-evidence="${index}">View evidence ↓</button></div><div class="disclosure" id="evidence-${index}">${company.evidence.map(evidence => `<div class="evidence-row"><div class="evidence-kind">${esc(evidence.type)}</div><div class="evidence-text">${esc(evidence.text)}</div><div class="evidence-meta">${esc(evidence.source)} · ${new Date(evidence.timestamp).toLocaleString()}</div></div>`).join("")}<button class="btn" style="margin-top:8px" data-open-company="${company.id}">Open company tracker →</button></div></article>`;
    }).join("") : `<div class="panel empty-state">No findings match those filters.</div>`}</div>`;
}

function trackerCard(company) {
  return `<article class="panel tracker-card" data-open-company="${company.id}" tabindex="0" role="button" aria-label="Open ${esc(company.name)} tracker"><div class="status-line"><span class="tag ${company.priority === "High" ? "warning" : ""}">${esc(company.status)}</span><span class="tag ${badgeClass(company)}">${esc(company.signal)}</span></div><div class="company-title">${companyLogo(company)}<div><div class="company-name">${esc(company.name)}</div><div class="company-meta">${esc(company.ticker)} · ${esc(company.sector)}</div></div></div><p class="finding">${esc(company.finding)}</p><div class="tracker-metrics">${company.metrics.map(metric => `<div><div class="metric-value">${esc(metric.value)}</div><div class="metric-label">${esc(metric.label)}</div></div>`).join("")}</div></article>`;
}

function trackersView() {
  if (currentPage === "detail") return detailView();
  return `<div class="heading-row"><div><div class="eyebrow">Coverage · ${model.companies.length} fictional companies</div><h1 class="page-title">Company trackers</h1><p class="subtitle">Theses, operating signals, risks and a change history in one place.</p></div><button class="btn" data-page="discover">＋ Discover companies</button></div>
    <div class="about-banner">Fictional sample portfolio. Metrics and theses are illustrative only and must not be treated as verified investment research.</div>
    <div class="tracker-grid">${model.companies.map(trackerCard).join("")}</div>`;
}

function researchRunView(run) {
  const report = run.report;
  const list = values => values.length ? `<ul class="risk-list">${values.map(value => `<li>${esc(typeof value === "string" ? value : `${value.statement} — ${value.source || "Source unavailable in supplied tracker"}`)}</li>`).join("")}</ul>` : `<div class="section-sub">No items returned.</div>`;
  return `<section class="panel detail-panel research-report"><div class="panel-heading"><div><h2 class="section-title">OpenAI research analysis</h2><div class="section-sub">Real model response · ${esc(run.model)} · ${new Date(run.createdAt).toLocaleString()}</div></div><span class="tag positive">${run.trigger === "scheduled" ? "SCHEDULED RUN" : "MANUAL RUN"}</span></div><div class="about-banner">${esc(run.scope)} This is AI-generated analysis, not verified research or investment advice.</div><div class="report-grid"><div><h3>Facts from supplied tracker</h3>${list(report.facts)}</div><div><h3>Assumptions</h3>${list(report.assumptions)}</div><div><h3>Interpretation</h3><p class="thesis-copy">${esc(report.interpretation)}</p></div><div><h3>Risks</h3>${list(report.risks)}</div><div><h3>Open questions</h3>${list(report.openQuestions)}</div></div></section>`;
}

function detailView() {
  const company = companyFor(selectedCompany) || model.companies[0];
  const companyRuns = model.researchRuns.filter(run => run.companyId === company.id);
  const configured = model.integrations.openai.configured;
  return `<div class="heading-row"><div><button class="text-link" data-page="trackers">← All trackers</button><h1 class="page-title" style="margin-top:10px">${esc(company.name)}</h1><p class="subtitle">${esc(company.ticker)} · ${esc(company.sector)} · Fictional tracker</p></div><button class="btn ${model.watchlist.includes(company.id) ? "btn-primary" : ""}" data-watch="${company.id}">${model.watchlist.includes(company.id) ? "✓ Saved to watchlist" : "＋ Add to watchlist"}</button></div>
    <div class="about-banner">The seeded tracker content is fictional. Any OpenAI report below is a real API response to that fictional input, with no external sources searched; it is not verified or live investment research.</div>
    <div class="tracker-detail"><div class="detail-main"><section class="panel detail-panel"><h3>Investment thesis</h3><p class="thesis-copy">${esc(company.thesis)}</p><div class="detail-actions"><button class="btn btn-primary" data-page="notes">＋ Add a note</button><button class="btn" data-page="discover">Review evidence</button></div><div class="research-action"><p class="section-sub">${configured ? "Manual only. Running sends this company’s name, ticker, sector, thesis, metrics, risks and evidence to OpenAI’s API. No notes or watchlist are sent; no external sources are searched." : "Optional OpenAI analysis is not configured. Set OPENAI_API_KEY in your local environment to enable manual runs."}</p><button class="btn ${configured ? "" : "research-disabled"}" id="run-openai" ${configured ? "" : "disabled"}>${configured ? "Run OpenAI analysis" : "OpenAI not configured"}</button></div></section>
    <section class="panel detail-panel"><h3>Key metrics <span class="section-sub"> · sample values only</span></h3><table class="metric-table"><thead><tr><th>METRIC</th><th>VALUE</th><th>PERIOD</th><th>SIGNAL</th></tr></thead><tbody>${company.metrics.map(metric => `<tr><td>${esc(metric.label)}</td><td>${esc(metric.value)}</td><td>${esc(metric.period)}</td><td class="trend-${esc(metric.trend)}">${metric.trend === "up" ? "↗ Improving" : metric.trend === "down" || metric.trend === "warning" ? "↘ Watch" : metric.trend === "flat" ? "→ Stable" : "—"}</td></tr>`).join("")}</tbody></table></section>
    <section class="panel detail-panel"><h3>Evidence trail</h3>${company.evidence.map(item => `<div class="evidence-row"><div class="evidence-kind">${esc(item.type)}</div><div class="evidence-text">${esc(item.text)}</div><div class="evidence-meta">${esc(item.source)} · ${new Date(item.timestamp).toLocaleString()}</div></div>`).join("")}</section></div>
    <aside class="detail-side"><section class="panel detail-panel"><h3>Risks & open questions</h3><ul class="risk-list">${company.risks.map(risk => `<li>${esc(risk)}</li>`).join("")}</ul></section><section class="panel detail-panel"><h3>History of changes</h3>${company.history.map(item => `<div class="history-item"><small>${esc(item.date)} · ${esc(item.by)}</small>${esc(item.change)}</div>`).join("")}</section>
    <section class="panel detail-panel"><h3>Research provenance</h3><div class="evidence-meta">Sample tracker update · 07 Oct 2026, 16:30 UTC<br>Provider · Local fictional seed<br>OpenAI analysis · ${companyRuns.length ? `${companyRuns.length} locally saved manual run(s)` : "Not run"}<br>Monitoring · Disabled</div></section></aside></div>
    ${companyRuns.map(researchRunView).join("")}`;
}

function notesView() {
  const notes = model.notes.map(note => `<div class="note-item"><span class="note-company">${esc(note.companyName)}</span><span class="note-date">${new Date(note.createdAt).toLocaleString()}</span><div class="note-text">${esc(note.text)}</div></div>`).join("");
  const saved = model.companies.filter(company => model.watchlist.includes(company.id));
  return `<div class="heading-row"><div><div class="eyebrow">Personal workspace · local</div><h1 class="page-title">Notes & watchlists</h1><p class="subtitle">Capture research thoughts and keep a focused list of companies.</p></div></div>
    <div class="about-banner">Notes and watchlist changes are saved locally in <code>data/user_state.json</code>. Do not use this demo to store sensitive or confidential information.</div>
    <div class="notes-layout"><section class="panel note-composer"><h2 class="section-title">Write a note</h2><div class="section-sub">Attach a note to one of your sample company trackers.</div><form id="note-form"><select class="select-input" id="note-company" required style="margin-top:12px;width:100%">${model.companies.map(company => `<option value="${company.id}" ${company.id === selectedCompany ? "selected" : ""}>${esc(company.name)} · ${company.ticker}</option>`).join("")}</select><textarea id="note-text" maxlength="2000" placeholder="What should you remember, verify or revisit?" required></textarea><div class="form-row"><button class="btn btn-primary" type="submit">Save note</button><span class="section-sub">Up to 2,000 characters</span></div></form></section>
    <section class="panel watchlist-strip"><h2 class="section-title">Watchlist</h2><div class="section-sub">Click a company to open its tracker.</div><div class="watchlist-items">${saved.length ? saved.map(company => `<button class="ticker-chip" data-open-company="${company.id}">${esc(company.ticker)} · ${esc(company.name)}</button>`).join("") : `<span class="section-sub">Your watchlist is empty. Save a company from its tracker.</span>`}</div><h2 class="section-title" style="margin-top:25px">Quick add / remove</h2><div class="section-sub">Toggle companies in your local watchlist.</div>${model.companies.map(company => `<div class="priority-row"><span class="priority-icon">${esc(company.ticker)}</span><div><strong>${esc(company.name)}</strong><small>${esc(company.sector)}</small></div><button class="btn" data-watch="${company.id}">${model.watchlist.includes(company.id) ? "Remove" : "Add"}</button></div>`).join("")}</section>
    <section class="panel note-list" style="grid-column:1/-1"><h2 class="section-title">Saved notes</h2><div class="section-sub">Most recent first · stored locally</div>${notes || `<div class="empty-state">No notes yet. Add your first research note above.</div>`}</section></div>`;
}

function templatesView() {
  const template = model.templates.find(item => item.id === selectedTemplate) || model.templates[0];
  return `<div class="heading-row"><div><div class="eyebrow">Consistent research process · 4 templates</div><h1 class="page-title">Review templates</h1><p class="subtitle">A repeatable structure for discovery, earnings, deterioration and weekly review.</p></div></div><div class="about-banner">Templates provide structure, not conclusions. Record source links and capture source timestamps when using real research.</div>
    <div class="template-layout"><nav class="panel template-list" aria-label="Research templates">${model.templates.map(item => `<button class="template-option ${item.id === selectedTemplate ? "active" : ""}" data-template="${item.id}"><strong>${esc(item.name)}</strong><small>${esc(item.description)}</small></button>`).join("")}</nav>
    <section class="panel template-preview"><div class="eyebrow">Research template</div><h2>${esc(template.name)}</h2><p>${esc(template.description)} · Use separate evidence, assumptions and interpretation.</p><div class="template-sections">${template.sections.map(section => `<div class="template-section">${esc(section)}</div>`).join("")}</div><div class="detail-actions"><button class="btn btn-primary" id="copy-template">Copy outline</button><button class="btn" data-page="notes">Start a note</button></div></section></div>`;
}

function render() {
  if (!model) return;
  document.querySelector("#logout-button").hidden = !authenticationRequired;
  document.querySelector("#page-crumb").textContent = pageName(currentPage);
  const views = { dashboard: dashboardView, discover: discoveryView, trackers: trackersView, detail: detailView, notes: notesView, templates: templatesView };
  app.innerHTML = views[currentPage]();
  clearInterval(monitoringPollTimer);
  monitoringPollTimer = null;
  if (currentPage === "dashboard" && (model.monitoring.enabled || model.monitoring.status === "running")) {
    monitoringPollTimer = setInterval(async () => {
      try {
        model = await request("/api");
        render();
      } catch (error) {
        clearInterval(monitoringPollTimer);
        monitoringPollTimer = null;
        toast(`Could not refresh monitoring status: ${error.message}`);
      }
    }, 5000);
  }
  app.querySelectorAll("[data-page]").forEach(button => button.addEventListener("click", () => go(button.dataset.page)));
  document.querySelectorAll("[data-open-company]").forEach(button => {
    const open = () => go("detail", button.dataset.openCompany);
    button.addEventListener("click", event => { event.stopPropagation(); open(); });
    if (button.tagName === "ARTICLE") button.addEventListener("keydown", event => { if (event.key === "Enter") open(); });
  });
  document.querySelectorAll("[data-evidence]").forEach(button => button.addEventListener("click", () => {
    const panel = document.querySelector(`#evidence-${button.dataset.evidence}`);
    panel.classList.toggle("open");
    button.textContent = panel.classList.contains("open") ? "Hide evidence ↑" : "View evidence ↓";
  }));
  document.querySelectorAll("[data-watch]").forEach(button => button.addEventListener("click", async () => {
    try { model.watchlist = (await request("/api/watchlist", { method: "POST", body: JSON.stringify({ companyId: button.dataset.watch }) })).watchlist; render(); toast("Watchlist updated locally."); }
    catch (error) { toast(error.message); }
  }));
  const runOpenAI = document.querySelector("#run-openai");
  if (runOpenAI && model.integrations.openai.configured) runOpenAI.addEventListener("click", async () => {
    const confirmed = window.confirm("This manual run sends the selected company’s name, ticker, sector, thesis, metrics, risks and evidence to OpenAI’s API. It does not send your notes or watchlist, and it does not search external sources. Continue?");
    if (!confirmed) return;
    runOpenAI.disabled = true;
    runOpenAI.textContent = "Running analysis…";
    try {
      const result = await request("/api/research/openai", { method: "POST", body: JSON.stringify({ companyId: selectedCompany }) });
      model.researchRuns.unshift(result.run);
      render();
      toast("OpenAI analysis completed and saved locally.");
    } catch (error) {
      render();
      toast(error.message);
    }
  });
  app.querySelectorAll("[data-monitoring]").forEach(button => button.addEventListener("click", async () => {
    const action = button.dataset.monitoring;
    if (action === "enable" && !window.confirm("Enable daily monitoring at 09:00 local time for saved-watchlist companies? Each run sends company name, ticker, sector, thesis, metrics, risks and evidence to OpenAI’s API. Notes and watchlist membership are not sent, and no external sources are searched. You can pause monitoring at any time.")) return;
    if (action === "run" && !window.confirm("Run research now for each saved-watchlist company? Their tracker name, ticker, sector, thesis, metrics, risks and evidence will be sent to OpenAI. This run is separate from the daily schedule.")) return;
    button.disabled = true;
    try {
      const result = action === "run"
        ? await request("/api/monitoring/run", { method: "POST", body: "{}" })
        : await request("/api/monitoring/settings", { method: "POST", body: JSON.stringify({ enabled: action === "enable" }) });
      model = await request("/api");
      render();
      toast(action === "enable" ? "Daily monitoring enabled." : action === "disable" ? "Daily monitoring paused." : `Monitoring started for ${result.run.companies.join(", ")}.`);
    } catch (error) {
      render();
      toast(error.message);
    }
  }));
  document.querySelectorAll("[data-template]").forEach(button => button.addEventListener("click", () => { selectedTemplate = button.dataset.template; render(); }));
  const search = document.querySelector("#discovery-search");
  if (search) search.addEventListener("input", event => { searchTerm = event.target.value; const caret = event.target.selectionStart; render(); const next = document.querySelector("#discovery-search"); next.focus(); next.setSelectionRange(caret, caret); });
  const filter = document.querySelector("#category-filter");
  if (filter) filter.addEventListener("change", event => { categoryFilter = event.target.value; render(); });
  const form = document.querySelector("#note-form");
  if (form) form.addEventListener("submit", async event => {
    event.preventDefault();
    const text = document.querySelector("#note-text").value.trim();
    const companyId = document.querySelector("#note-company").value;
    try { await request("/api/notes", { method: "POST", body: JSON.stringify({ text, companyId }) }); model = await request("/api"); render(); toast("Note saved on this device."); }
    catch (error) { toast(error.message); }
  });
  const copy = document.querySelector("#copy-template");
  if (copy) copy.addEventListener("click", async () => {
    const content = `${model.templates.find(item => item.id === selectedTemplate).name}\n\n${model.templates.find(item => item.id === selectedTemplate).sections.map(section => `${section}\n`).join("\n")}`;
    try { await navigator.clipboard.writeText(content); toast("Template outline copied."); }
    catch { toast("Clipboard unavailable. Select and copy the outline manually."); }
  });
}

function installNavigation() {
  if (navigationInstalled) return;
  navigationInstalled = true;
  const nav = document.createElement("nav");
  nav.className = "mobile-nav";
  nav.setAttribute("aria-label", "Mobile navigation");
  nav.innerHTML = `<button data-page="dashboard"><span>◫</span>Overview</button><button data-page="discover"><span>⌕</span>Discover</button><button data-page="trackers"><span>◎</span>Trackers</button><button data-page="notes"><span>▤</span>Notes</button><button data-page="templates"><span>▧</span>Templates</button>`;
  document.body.appendChild(nav);
  nav.querySelectorAll("[data-page]").forEach(button => button.addEventListener("click", () => go(button.dataset.page)));
  document.querySelectorAll(".sidebar [data-page]").forEach(button => button.addEventListener("click", () => go(button.dataset.page)));
  document.querySelector("#help-button").addEventListener("click", () => toast("Fictional seed data · OpenAI only on explicit runs or opted-in schedule · no trading."));
  document.querySelector("#logout-button").addEventListener("click", async () => {
    try {
      await request("/api/logout", { method: "POST", body: "{}" });
      csrfToken = null;
      model = null;
      renderLogin();
    } catch (error) {
      toast(`Could not sign out: ${error.message}`);
    }
  });
}

function renderLogin(message = "") {
  clearInterval(monitoringPollTimer);
  monitoringPollTimer = null;
  document.querySelector("#logout-button").hidden = true;
  app.innerHTML = `<section class="panel login-panel"><div class="brand-mark"><span></span><span></span><span></span></div><div class="eyebrow">Private workspace</div><h1 class="page-title">Sign in to Portfolio Radar</h1><p class="subtitle">This private instance requires its locally configured password.</p>${message ? `<div class="monitor-error">${esc(message)}</div>` : ""}<form id="login-form"><label for="login-password">Password</label><input id="login-password" name="password" type="password" autocomplete="current-password" minlength="12" required><button class="btn btn-primary" type="submit">Sign in</button></form><div class="section-sub">Your password is checked by the local server and is never sent to a third-party provider.</div></section>`;
  document.querySelector("#login-form").addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const password = new FormData(form).get("password");
    const submit = form.querySelector("button[type=submit]");
    submit.disabled = true;
    try {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Sign-in failed.");
      csrfToken = result.csrfToken;
      form.reset();
      await start();
    } catch (error) {
      renderLogin(error.message);
    }
  });
}

async function start() {
  try {
    model = await request("/api");
    authenticationRequired = Boolean(model.authRequired);
    installNavigation();
    render();
  } catch (error) {
    if (error.status === 401) {
      authenticationRequired = true;
      renderLogin();
      return;
    }
    app.innerHTML = `<section class="panel empty-state"><strong>Could not connect to the local app.</strong><p>${esc(error.message)}</p><p>Start it by running <code>python server.py</code> in the project folder.</p></section>`;
  }
}

start();
