import { t, getLang } from "../i18n.js";
import { searchCaseNumber, searchSessions, searchExperts, searchExecution, searchInternal, importRecord, listTracked, untrackCase, listCasesCached, listOfficialSources, recordOfficialCheck, listProcedureTypes, getPermission } from "../api.js";
import { formatDate, toast, escapeHtml, icon, formatNumber } from "../ui.js";
import { openCaseDetail } from "./cases.js";
import { previewDocument } from "./documents.js";
import { canRequestUpdate, openRequestUpdateDialog } from "../request-update.js";
import { printRecord, printButton } from "../print.js";

/**
 * Case ids the current user is already tracking.
 *
 * Loaded once per page render so every result row can show a truthful
 * tracked/not-tracked state. Before this existed, "Import to Tracking List"
 * wrote a row to `imported_records` (which nothing ever read) plus a
 * `case_watchers` row (only visible as a bookmark deep inside the case-detail
 * modal) — so the button looked like it did nothing at all.
 */
let trackedCaseIds = new Set();

async function loadTracked() {
  try {
    const rows = await listTracked();
    trackedCaseIds = new Set(rows.map((r) => r.case_id));
  } catch {
    trackedCaseIds = new Set();
  }
}

const TABS = [
  { key: "case_number", label: "tab_case_number", shortLabel: "tab_case_number_short" },
  { key: "sessions", label: "tab_sessions", shortLabel: "tab_sessions_short" },
  { key: "experts", label: "tab_experts", shortLabel: "tab_experts" },
  { key: "execution", label: "tab_execution", shortLabel: "tab_execution" },
  { key: "internal", label: "tab_internal", shortLabel: "tab_internal_short" },
];

let activeTab = "case_number";

export function destroy() {}

/**
 * Reload in place for the Cases hub's tab-click refresh (js/hub.js), keeping
 * what the user typed: tracked state is re-read, the current sub-tab's search
 * is re-run with the same criteria if one had been run, and the Official Sync
 * panel re-reads its lists. A full render() would wipe the inputs.
 */
export async function refresh(container, user) {
  await loadTracked();
  const content = container.querySelector("#search-tab-content");
  const hasResults = content?.querySelector(".table-wrap table, .table-wrap .empty-state");
  if (hasResults) content.querySelector("#btn-search")?.click();
  if (getPermission("official_sync") !== "none") await wireOfficialSyncPanel(container);
}

export async function render(container, user) {
  // Tracked state is needed before any result renders, so the Track button
  // tells the truth on first paint rather than after a click.
  await loadTracked();

  container.innerHTML = `
    <div class="panel" style="margin-bottom:20px;">
      <div class="panel-body">
        <h2 class="mt-0">${t("search_hub_title")}</h2>
        <p class="text-muted mt-0">${t("search_hub_subtitle")}</p>
        <p class="search-source-notice">${icon("circle-info")} ${t("search_source_notice")}</p>
        <div class="tabs" id="search-tabs">
          ${TABS.map((tb) => `<button class="tab-btn ${tb.key === activeTab ? "active" : ""}" data-tab="${tb.key}"><span class="label-full">${t(tb.label)}</span><span class="label-short">${t(tb.shortLabel)}</span></button>`).join("")}
        </div>
        <div id="search-tab-content"></div>
      </div>
    </div>
    ${getPermission("official_sync") !== "none" ? officialSyncPanelSkeleton() : ""}
  `;

  container.querySelectorAll("[data-tab]").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTab = btn.getAttribute("data-tab");
      render(container, user);
    });
  });

  const content = container.querySelector("#search-tab-content");
  const renderers = {
    case_number: renderCaseNumberTab,
    sessions: renderSessionsTab,
    experts: renderExpertsTab,
    execution: renderExecutionTab,
    internal: renderInternalTab,
  };
  renderers[activeTab](content, user);

  if (getPermission("official_sync") !== "none") {
    wireOfficialSyncPanel(container);
  }
}

/**
 * Assisted Manual Sync — "Check official portal" (Phase 1 blueprint
 * section 4.5). Every result on the five tabs above is the FIRM'S OWN
 * records, matched to look like the real MOJ e-Services search screen
 * (see the header subtitle) — this panel is the honest bridge to the real
 * government portal: it opens the real site in a new tab for the user to
 * sign in and look themselves (no credential or CAPTCHA ever passes
 * through this app), then records only what a human reports having seen.
 */
function officialSyncPanelSkeleton() {
  return `
    <div class="panel" id="official-sync-panel">
      <div class="panel-header"><h3>${icon("arrows-rotate")} ${t("official_sync_title")}</h3></div>
      <div class="panel-body">
        <p class="text-muted mt-0">${t("official_sync_disclaimer")}</p>
        <div id="official-sync-body"><p class="text-muted">${icon("spinner", "fa-spin")}</p></div>
      </div>
    </div>`;
}

async function wireOfficialSyncPanel(container) {
  const body = container.querySelector("#official-sync-body");
  if (!body) return;
  let cases = [];
  let sources = [];
  try {
    // Cached: this panel re-renders on every sub-tab click above, and the
    // My Cases tab beside this one needs the same list.
    [cases, sources] = await Promise.all([listCasesCached(), listOfficialSources()]);
  } catch (err) {
    body.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
    return;
  }
  if (cases.length === 0 || sources.length === 0) {
    body.innerHTML = `<p class="text-muted">${t("official_sync_no_cases")}</p>`;
    return;
  }
  const lang = getLang();
  body.innerHTML = `
    <div class="search-form-grid">
      <div class="form-group">
        <label>${t("official_sync_case")}</label>
        <select id="osync-case">
          ${cases.map((c) => `<option value="${c.id}">${c.case_number}/${c.case_year} — ${escapeHtml(lang === "ar" ? c.parties_ar : c.parties_en)}</option>`).join("")}
        </select>
      </div>
      <div class="form-group">
        <label>${t("official_sync_source")}</label>
        <select id="osync-source">
          ${sources.map((s) => `<option value="${s.id}" data-url="${s.base_url}">${escapeHtml(lang === "ar" ? s.name_ar : s.name_en)}${s.requires_captcha ? ` (${t("official_sync_captcha")})` : ""}</option>`).join("")}
        </select>
      </div>
    </div>
    <button type="button" class="btn btn-outline btn-sm" id="osync-open-btn">${icon("arrow-up-right-from-square")} ${t("official_sync_open")}</button>
    <div style="margin-top:14px;">
      <div class="search-form-grid">
        <div class="form-group">
          <label>${t("official_sync_outcome")}</label>
          <select id="osync-outcome">
            <option value="no_change">${t("official_sync_outcome_no_change")}</option>
            <option value="change_recorded">${t("official_sync_outcome_change_recorded")}</option>
            <option value="not_found">${t("official_sync_outcome_not_found")}</option>
            <option value="blocked">${t("official_sync_outcome_blocked")}</option>
          </select>
        </div>
      </div>
      <div class="form-group" id="osync-change-fields" style="display:none;">
        <label>${t("official_sync_new_procedure_type")}</label>
        <select id="osync-proc-type"></select>
      </div>
      <div class="form-group">
        <label>${t("official_sync_note")}</label>
        <textarea id="osync-note" rows="2"></textarea>
      </div>
      <button class="btn btn-primary btn-sm" id="osync-record-btn">${icon("paper-plane")} ${t("official_sync_record")}</button>
    </div>
  `;

  body.querySelector("#osync-open-btn").addEventListener("click", () => {
    const sel = body.querySelector("#osync-source");
    const url = sel.options[sel.selectedIndex]?.getAttribute("data-url");
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  });

  const outcomeSelect = body.querySelector("#osync-outcome");
  const changeFields = body.querySelector("#osync-change-fields");
  const procTypeSelect = body.querySelector("#osync-proc-type");
  let procTypesLoaded = false;
  outcomeSelect.addEventListener("change", async () => {
    const isChange = outcomeSelect.value === "change_recorded";
    changeFields.style.display = isChange ? "" : "none";
    if (isChange && !procTypesLoaded) {
      try {
        const types = await listProcedureTypes();
        procTypeSelect.innerHTML = types.map((pt) => `<option value="${pt.id}">${escapeHtml(lang === "ar" ? pt.name_ar : pt.name_en)}</option>`).join("");
        procTypesLoaded = true;
      } catch (err) {
        toast(err.message, "error");
      }
    }
  });

  body.querySelector("#osync-record-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const caseId = Number(body.querySelector("#osync-case").value);
    const sourceId = Number(body.querySelector("#osync-source").value);
    const outcome = outcomeSelect.value;
    const rawNote = body.querySelector("#osync-note").value.trim() || null;
    if (outcome === "change_recorded" && !procTypeSelect.value) {
      toast(t("official_sync_new_procedure_type_required"), "error");
      return;
    }
    const payload = { source_id: sourceId, outcome, raw_note: rawNote };
    if (outcome === "change_recorded") {
      payload.new_procedure = { procedure_type_id: Number(procTypeSelect.value), occurred_at: new Date().toISOString() };
    }
    btn.disabled = true;
    try {
      await recordOfficialCheck(caseId, payload);
      toast(t("official_sync_recorded_success"), "success");
      body.querySelector("#osync-note").value = "";
    } catch (err) {
      toast(err.message, "error");
    } finally {
      btn.disabled = false;
    }
  });
}

/**
 * The case a related record (session / expert / execution) belongs to, shown
 * on the result itself.
 *
 * The values come from the record's own case_id foreign key on the server
 * (search.py::_case_ctx), read live on every request — so a result can never
 * contradict the case page. Previously these tabs showed only a bare
 * "1123/2024" with no parties, court, or current stage, which made it easy to
 * act on the wrong case.
 */
function caseCell(r) {
  const lang = getLang();
  return `
    <b>${r.case_number}/${r.case_year}</b> ${statusBadge(r.case_stage)}
    <div class="text-muted" style="font-size:11.5px;">
      ${escapeHtml(lang === "ar" ? r.case_parties_ar : (r.case_parties_en || r.case_parties_ar))}<br>
      ${escapeHtml(lang === "ar" ? r.case_court_ar : r.case_court_en)}${r.case_status === "closed" ? ` • <span class="badge badge-muted">${t("stage_closed")}</span>` : ""}
    </div>`;
}

function courtOptions() {
  const lang = getLang();
  const courts = [
    { v: "cassation", ar: "محكمة التمييز", en: "Court of Cassation" },
    { v: "appeal", ar: "محكمة الاستئناف", en: "Court of Appeal" },
    { v: "first_instance", ar: "المحكمة الكلية", en: "Court of First Instance" },
    { v: "misdemeanor", ar: "محكمة الجنح", en: "Misdemeanor Court" },
    { v: "family", ar: "محكمة الأسرة", en: "Family Court" },
  ];
  return courts.map((c) => `<option value="${c.v}">${lang === "ar" ? c.ar : c.en}</option>`).join("");
}

function resultsShell(id) {
  return `<div id="${id}" class="table-wrap"></div>`;
}

/**
 * "Results" heading with an empty slot beside it for a Print button.
 *
 * The button is added only once a search has actually returned rows — an
 * always-present Print control on an empty results area would be an
 * affordance for nothing, and would print a blank sheet.
 */
function resultsHead(slotId) {
  return `<div class="flex-between" style="align-items:center;margin-bottom:8px;">
    <h4 style="margin:0;">${t("results")}</h4>
    <span id="${slotId}"></span>
  </div>`;
}

function mountResultsPrint(root, slotId, buildSpec) {
  const slot = root.querySelector(`#${slotId}`);
  if (!slot) return;
  slot.innerHTML = printButton(`${slotId}-btn`);
  slot.querySelector("button").addEventListener("click", () => printRecord(buildSpec()));
}

function clearResultsPrint(root, slotId) {
  const slot = root.querySelector(`#${slotId}`);
  if (slot) slot.innerHTML = "";
}

/** The criteria that produced the sheet, so a printout is self-explaining:
 *  reading it later, you can tell what was asked as well as what came back. */
function criteriaMeta(pairs) {
  const used = pairs.filter(([, v]) => v !== undefined && v !== null && String(v).trim() !== "");
  return [
    {
      label: t("print_criteria"),
      value: used.length ? used.map(([k, v]) => `${k}: ${v}`).join(" • ") : t("print_all"),
    },
  ];
}

function loadingRow() {
  return `<p class="text-muted">${icon("spinner", "fa-spin")} ${t("results")}...</p>`;
}

function noResults() {
  return `<div class="empty-state"><div class="empty-icon">${icon("magnifying-glass")}</div>${t("no_results")}</div>`;
}

/**
 * The action set every Official Search result gets.
 *
 * Three actions, each of which does something real and visible:
 *   Open   — opens the linked case (the record every result hangs off)
 *   Track  — pins the case to the user's tracked list, and SHOWS that it did
 *   Ask    — Admin/Lawyer only: creates a real task in Reminders & Follow-ups
 *
 * `caseId` is what Track/Open act on; `sourceType`/`sourceRefId` identify the
 * specific row so the server can record precisely what was tracked.
 */
function resultActions(sourceType, sourceRefId, caseId, label, user) {
  if (!caseId) return "";
  const tracked = trackedCaseIds.has(caseId);
  return `
    <div class="result-actions">
      <button class="btn btn-outline btn-sm" data-open-case="${caseId}" title="${t("open_case")}">
        ${icon("folder-open")} ${t("open_case")}
      </button>
      <button class="btn ${tracked ? "btn-accent" : "btn-outline"} btn-sm"
              data-track-type="${sourceType}" data-track-id="${sourceRefId}" data-case-id="${caseId}"
              title="${tracked ? t("tracked_tooltip") : t("track_tooltip")}">
        ${icon(tracked ? "bookmark" : "bookmark")} ${tracked ? t("tracked") : t("track")}
      </button>
      ${
        canRequestUpdate(user)
          ? `<button class="btn btn-outline btn-sm" data-ask-case="${caseId}" data-label="${escapeHtml(label || "")}"
                     title="${t("request_update_hint_short")}">${icon("rotate")} ${t("request_update")}</button>`
          : ""
      }
    </div>`;
}

function wireResultActions(root, user) {
  root.querySelectorAll("[data-open-case]").forEach((btn) => {
    btn.addEventListener("click", () => openCaseDetail(Number(btn.getAttribute("data-open-case")), user));
  });

  root.querySelectorAll("[data-track-id]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const caseId = Number(btn.getAttribute("data-case-id"));
      const wasTracked = trackedCaseIds.has(caseId);
      btn.disabled = true;
      try {
        if (wasTracked) {
          await untrackCase(caseId);
          trackedCaseIds.delete(caseId);
          toast(t("untracked_msg"), "info");
        } else {
          await importRecord(btn.getAttribute("data-track-type"), Number(btn.getAttribute("data-track-id")));
          trackedCaseIds.add(caseId);
          toast(t("tracked_msg"), "success");
        }
        // Reflect the new state on the button itself — the old version gave
        // no lasting feedback at all, which is why it felt broken.
        const nowTracked = trackedCaseIds.has(caseId);
        btn.classList.toggle("btn-accent", nowTracked);
        btn.classList.toggle("btn-outline", !nowTracked);
        btn.innerHTML = `${icon("bookmark")} ${nowTracked ? t("tracked") : t("track")}`;
        btn.title = nowTracked ? t("tracked_tooltip") : t("track_tooltip");
      } catch (err) {
        toast(err.message, "error");
      } finally {
        btn.disabled = false;
      }
    });
  });

  root.querySelectorAll("[data-ask-case]").forEach((btn) => {
    btn.addEventListener("click", () =>
      openRequestUpdateDialog({
        sourceType: "case",
        sourceRefId: Number(btn.getAttribute("data-ask-case")),
        contextLabel: btn.getAttribute("data-label"),
      })
    );
  });
}

function renderCaseNumberTab(root, user) {
  const lang = getLang();
  root.innerHTML = `
    <div class="search-form-grid">
      <div class="form-group"><label>${t("court_level")}</label><select id="f-court"><option value="">${t("all")}</option>${courtOptions()}</select></div>
      <div class="form-group"><label>${t("case_number")}</label><input id="f-num" placeholder="0000"/></div>
      <div class="form-group"><label>${t("automated_number")}</label><input id="f-auto" inputmode="numeric" placeholder="${lang === "ar" ? "مثال: 202400001" : "e.g. 202400001"}"/></div>
      <div class="form-group"><label>${t("party_civil_id")}</label><input id="f-party" placeholder="${lang === "ar" ? "اسم أو رقم مدني" : "Name or Civil ID"}"/></div>
      <div class="search-actions">
        <button class="btn btn-primary" id="btn-search">${icon("magnifying-glass")} ${t("search_btn")}</button>
        <button class="btn btn-outline" id="btn-reset">${t("reset_btn")}</button>
      </div>
    </div>
    <div style="margin-top:22px;">
      ${resultsHead("case-print-slot")}
      ${resultsShell("case-results")}
    </div>`;

  const resultsEl = root.querySelector("#case-results");
  resultsEl.innerHTML = `<p class="text-muted">${t("search_tips")}</p>`;

  root.querySelector("#btn-search").addEventListener("click", async () => {
    resultsEl.innerHTML = loadingRow();
    clearResultsPrint(root, "case-print-slot");
    const criteria = {
      court_level: root.querySelector("#f-court").value,
      case_number: root.querySelector("#f-num").value.trim(),
      automated_number: root.querySelector("#f-auto").value.trim(),
      party: root.querySelector("#f-party").value.trim(),
    };
    const courtLabel = root.querySelector("#f-court").selectedOptions[0]?.textContent.trim();
    let cases;
    try {
      cases = await searchCaseNumber(criteria);
    } catch (err) {
      resultsEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      return;
    }
    if (cases.length === 0) {
      resultsEl.innerHTML = noResults();
      return;
    }
    mountResultsPrint(root, "case-print-slot", () => ({
      title: t("print_search_results"),
      subtitle: t("tab_case_number"),
      meta: criteriaMeta([
        [t("court_level"), criteria.court_level ? courtLabel : ""],
        [t("case_number"), criteria.case_number],
        [t("automated_number"), criteria.automated_number],
        [t("party_civil_id"), criteria.party],
      ]),
      sections: [
        {
          heading: t("results"),
          table: {
            columns: [t("case_number"), t("print_parties"), t("court_level"), t("print_stage")],
            rows: cases.map((c) => [
              `${c.case_number}/${c.case_year}`,
              lang === "ar" ? c.parties_ar : c.parties_en,
              lang === "ar" ? c.court_name_ar : c.court_name_en,
              t("stage_" + c.stage),
            ]),
          },
        },
      ],
    }));
    resultsEl.innerHTML = `
      <table class="data-table">
        <thead><tr><th>${t("case_number")}</th><th>${t("court_level")}</th><th></th><th></th><th></th></tr></thead>
        <tbody>
          ${cases
            .map(
              (c) => `<tr>
              <td data-label="${t("case_number")}"><b>${c.case_number}/${c.case_year}</b><br><span class="text-muted">${lang === "ar" ? c.parties_ar : c.parties_en}</span></td>
              <td data-label="${t("court_level")}">${lang === "ar" ? c.court_name_ar : c.court_name_en}</td>
              <td><span class="badge badge-info">${lang === "ar" ? c.category_ar : c.category_en}</span></td>
              <td>${statusBadge(c.stage)}</td>
              <td>${resultActions("case", c.id, c.id, `${c.case_number}/${c.case_year}`, user)}</td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
    wireResultActions(resultsEl, user);
  });

  root.querySelector("#btn-reset").addEventListener("click", () => renderCaseNumberTab(root, user));
}

function statusBadge(stage) {
  const map = {
    new: ["badge-info", "stage_new"],
    prep: ["badge-warning", "stage_prep"],
    pleading: ["badge-info", "stage_pleading"],
    judgment: ["badge-success", "stage_judgment"],
    execution: ["badge-danger", "stage_execution"],
    closed: ["badge-muted", "stage_closed"],
  };
  const [cls, key] = map[stage] || ["badge-muted", "stage_new"];
  return `<span class="badge ${cls}">${t(key)}</span>`;
}

function renderSessionsTab(root, user) {
  const lang = getLang();
  root.innerHTML = `
    <div class="search-form-grid">
      <div class="form-group"><label>${t("circuit")}</label><input id="f-circuit" placeholder="${lang === "ar" ? "رقم أو اسم الدائرة" : "Circuit name/number"}"/></div>
      <div class="form-group"><label>${t("session_date")}</label><input id="f-date" type="date"/></div>
      <div class="form-group"><label>${t("case_number")}</label><input id="f-casenum"/></div>
      <div class="search-actions">
        <button class="btn btn-primary" id="btn-search">${icon("magnifying-glass")} ${t("search_btn")}</button>
        <button class="btn btn-outline" id="btn-reset">${t("reset_btn")}</button>
      </div>
    </div>
    <div style="margin-top:22px;">${resultsHead("sess-print-slot")}${resultsShell("sess-results")}</div>`;

  const resultsEl = root.querySelector("#sess-results");
  resultsEl.innerHTML = `<p class="text-muted">${t("search_tips")}</p>`;

  root.querySelector("#btn-search").addEventListener("click", async () => {
    resultsEl.innerHTML = loadingRow();
    clearResultsPrint(root, "sess-print-slot");
    const criteria = {
      circuit: root.querySelector("#f-circuit").value.trim(),
      session_date: root.querySelector("#f-date").value,
      case_number: root.querySelector("#f-casenum").value.trim(),
    };
    let sessions;
    try {
      sessions = await searchSessions(criteria);
    } catch (err) {
      resultsEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      return;
    }
    if (sessions.length === 0) {
      resultsEl.innerHTML = noResults();
      return;
    }
    mountResultsPrint(root, "sess-print-slot", () => ({
      title: t("print_search_results"),
      subtitle: t("tab_sessions"),
      // The date filter is a Kuwait calendar date on the server too
      // (search.py uses kuwait_day_utc_range), so the criterion printed here
      // and the rows underneath it agree about which day was asked for.
      meta: criteriaMeta([
        [t("circuit"), criteria.circuit],
        [t("session_date"), criteria.session_date],
        [t("case_number"), criteria.case_number],
      ]),
      sections: [
        {
          heading: t("results"),
          table: {
            columns: [t("case_number"), t("print_parties"), t("circuit"), t("session_date"), t("print_status")],
            rows: sessions.map((s) => [
              `${s.case_number}/${s.case_year}`,
              lang === "ar" ? s.case_parties_ar : s.case_parties_en || s.case_parties_ar,
              lang === "ar" ? s.circuit_ar : s.circuit_en,
              formatDate(s.session_at, { time: true }),
              t(s.status === "done" ? "status_done" : s.status === "postponed" ? "status_postponed" : "status_scheduled"),
            ]),
          },
        },
      ],
    }));
    resultsEl.innerHTML = `
      <table class="data-table">
        <thead><tr><th>${t("case_number")}</th><th>${t("circuit")}</th><th>${t("session_date")}</th><th></th><th></th></tr></thead>
        <tbody>
          ${sessions
            .map(
              (s) => `<tr>
                <td data-label="${t("case_number")}">${caseCell(s)}</td>
                <td data-label="${t("circuit")}">${lang === "ar" ? s.circuit_ar : s.circuit_en}</td>
                <td data-label="${t("session_date")}">${formatDate(s.session_at, { time: true })}</td>
                <td>${sessionStatusBadge(s.status)}</td>
                <td>${resultActions("session", s.id, s.case_id, `${s.case_number}/${s.case_year}`, user)}</td>
              </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
    wireResultActions(resultsEl, user);
  });

  root.querySelector("#btn-reset").addEventListener("click", () => renderSessionsTab(root, user));
}

function sessionStatusBadge(status) {
  const map = { scheduled: ["badge-info", "status_scheduled"], done: ["badge-success", "status_done"], postponed: ["badge-warning", "status_postponed"] };
  const [cls, key] = map[status] || ["badge-muted", "status_scheduled"];
  return `<span class="badge ${cls}">${t(key)}</span>`;
}

function renderExpertsTab(root, user) {
  const lang = getLang();
  root.innerHTML = `
    <div class="search-form-grid">
      <div class="form-group"><label>${t("expert_file_no")}</label><input id="f-fileno"/></div>
      <div class="form-group"><label>${t("expert_name")}</label><input id="f-name"/></div>
      <div class="form-group"><label>${t("case_number")}</label><input id="f-casenum"/></div>
      <div class="search-actions">
        <button class="btn btn-primary" id="btn-search">${icon("magnifying-glass")} ${t("search_btn")}</button>
        <button class="btn btn-outline" id="btn-reset">${t("reset_btn")}</button>
      </div>
    </div>
    <div style="margin-top:22px;">${resultsHead("exp-print-slot")}${resultsShell("exp-results")}</div>`;

  const resultsEl = root.querySelector("#exp-results");
  resultsEl.innerHTML = `<p class="text-muted">${t("search_tips")}</p>`;

  root.querySelector("#btn-search").addEventListener("click", async () => {
    resultsEl.innerHTML = loadingRow();
    clearResultsPrint(root, "exp-print-slot");
    const criteria = {
      file_no: root.querySelector("#f-fileno").value.trim(),
      expert_name: root.querySelector("#f-name").value.trim(),
      case_number: root.querySelector("#f-casenum").value.trim(),
    };
    let experts;
    try {
      experts = await searchExperts(criteria);
    } catch (err) {
      resultsEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      return;
    }
    if (experts.length === 0) {
      resultsEl.innerHTML = noResults();
      return;
    }
    mountResultsPrint(root, "exp-print-slot", () => ({
      title: t("print_search_results"),
      subtitle: t("tab_experts"),
      meta: criteriaMeta([
        [t("expert_file_no"), criteria.file_no],
        [t("expert_name"), criteria.expert_name],
        [t("case_number"), criteria.case_number],
      ]),
      sections: [
        {
          heading: t("results"),
          table: {
            columns: [t("expert_file_no"), t("expert_name"), t("case_number"), t("print_parties"), t("print_status")],
            rows: experts.map((e) => [
              e.file_no,
              `${e.expert_name} — ${lang === "ar" ? e.specialty_ar : e.specialty_en}`,
              `${e.case_number}/${e.case_year}`,
              lang === "ar" ? e.case_parties_ar : e.case_parties_en || e.case_parties_ar,
              t(e.status === "completed" ? "status_done" : e.status === "in_progress" ? "stage_pleading" : "status_scheduled"),
            ]),
          },
        },
      ],
    }));
    resultsEl.innerHTML = `
      <table class="data-table">
        <thead><tr><th>${t("expert_file_no")}</th><th>${t("expert_name")}</th><th>${t("case_number")}</th><th></th><th></th></tr></thead>
        <tbody>
          ${experts
            .map(
              (e) => `<tr>
                <td data-label="${t("expert_file_no")}">${e.file_no}</td>
                <td data-label="${t("expert_name")}">${e.expert_name}<br><span class="text-muted">${lang === "ar" ? e.specialty_ar : e.specialty_en}</span></td>
                <td data-label="${t("case_number")}">${caseCell(e)}</td>
                <td>${expertStatusBadge(e.status)}</td>
                <td>${resultActions("expert", e.id, e.case_id, `${e.case_number}/${e.case_year}`, user)}</td>
              </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
    wireResultActions(resultsEl, user);
  });

  root.querySelector("#btn-reset").addEventListener("click", () => renderExpertsTab(root, user));
}

function expertStatusBadge(status) {
  const map = { scheduled: "badge-info", in_progress: "badge-warning", completed: "badge-success" };
  const labels = { scheduled: "status_scheduled", in_progress: "stage_pleading", completed: "status_done" };
  return `<span class="badge ${map[status] || "badge-muted"}">${t(labels[status] || "status_scheduled")}</span>`;
}

function renderExecutionTab(root, user) {
  const lang = getLang();
  root.innerHTML = `
    <div class="search-form-grid">
      <div class="form-group"><label>${t("execution_file_no")}</label><input id="f-fileno"/></div>
      <div class="form-group"><label>${t("case_number")}</label><input id="f-casenum"/></div>
      <div class="form-group"><label>${t("judgment_status")}</label>
        <select id="f-status"><option value="">${t("all")}</option><option value="in_progress">${t("stage_pleading")}</option><option value="closed">${t("stage_closed")}</option></select>
      </div>
      <div class="search-actions">
        <button class="btn btn-primary" id="btn-search">${icon("magnifying-glass")} ${t("search_btn")}</button>
        <button class="btn btn-outline" id="btn-reset">${t("reset_btn")}</button>
      </div>
    </div>
    <div style="margin-top:22px;">${resultsHead("ex-print-slot")}${resultsShell("ex-results")}</div>`;

  const resultsEl = root.querySelector("#ex-results");
  resultsEl.innerHTML = `<p class="text-muted">${t("search_tips")}</p>`;

  root.querySelector("#btn-search").addEventListener("click", async () => {
    resultsEl.innerHTML = loadingRow();
    clearResultsPrint(root, "ex-print-slot");
    const criteria = {
      file_no: root.querySelector("#f-fileno").value.trim(),
      case_number: root.querySelector("#f-casenum").value.trim(),
      status: root.querySelector("#f-status").value,
    };
    const statusLabel = root.querySelector("#f-status").selectedOptions[0]?.textContent.trim();
    let executions;
    try {
      executions = await searchExecution(criteria);
    } catch (err) {
      resultsEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      return;
    }
    if (executions.length === 0) {
      resultsEl.innerHTML = noResults();
      return;
    }
    mountResultsPrint(root, "ex-print-slot", () => ({
      title: t("print_search_results"),
      subtitle: t("tab_execution"),
      meta: criteriaMeta([
        [t("execution_file_no"), criteria.file_no],
        [t("case_number"), criteria.case_number],
        [t("judgment_status"), criteria.status ? statusLabel : ""],
      ]),
      sections: [
        {
          heading: t("results"),
          table: {
            columns: [t("execution_file_no"), t("case_number"), t("print_parties"), t("judgment_status")],
            rows: executions.map((ex) => [
              `${ex.file_no} — ${formatNumber(ex.amount)} ${ex.currency}`,
              `${ex.case_number}/${ex.case_year}`,
              lang === "ar" ? ex.case_parties_ar : ex.case_parties_en || ex.case_parties_ar,
              `${ex.status === "closed" ? t("stage_closed") : lang === "ar" ? "قيد التنفيذ" : "In Progress"} — ${lang === "ar" ? ex.last_action_ar : ex.last_action_en}`,
            ]),
          },
        },
      ],
    }));
    resultsEl.innerHTML = `
      <table class="data-table">
        <thead><tr><th>${t("execution_file_no")}</th><th>${t("case_number")}</th><th>${t("judgment_status")}</th><th></th></tr></thead>
        <tbody>
          ${executions
            .map(
              (ex) => `<tr>
                <td data-label="${t("execution_file_no")}">${ex.file_no}<br><span class="text-muted">${formatNumber(ex.amount)} ${ex.currency}</span></td>
                <td data-label="${t("case_number")}">${caseCell(ex)}</td>
                <td data-label="${t("judgment_status")}">${ex.status === "closed" ? `<span class="badge badge-muted">${t("stage_closed")}</span>` : `<span class="badge badge-warning">${lang === "ar" ? "قيد التنفيذ" : "In Progress"}</span>`}<br><span class="text-muted">${lang === "ar" ? ex.last_action_ar : ex.last_action_en}</span></td>
                <td>${resultActions("execution", ex.id, ex.case_id, `${ex.case_number}/${ex.case_year}`, user)}</td>
              </tr>`
            )
            .join("")}
        </tbody>
      </table>`;
    wireResultActions(resultsEl, user);
  });

  root.querySelector("#btn-reset").addEventListener("click", () => renderExecutionTab(root, user));
}

function renderInternalTab(root, user) {
  const lang = getLang();
  root.innerHTML = `
    <div class="search-form-grid">
      <div class="form-group">
        <label>${t("tab_internal")}</label>
        <input id="f-internal" placeholder="${t("internal_query")}"/>
      </div>
      <div class="search-actions"><button class="btn btn-primary" id="btn-search">${icon("magnifying-glass")} ${t("search_btn")}</button></div>
    </div>
    <div style="margin-top:22px;">${resultsHead("int-print-slot")}${resultsShell("int-results")}</div>`;

  const resultsEl = root.querySelector("#int-results");
  resultsEl.innerHTML = `<p class="text-muted">${t("search_tips")}</p>`;

  const doSearch = async () => {
    const q = root.querySelector("#f-internal").value.trim();
    clearResultsPrint(root, "int-print-slot");
    if (!q) {
      resultsEl.innerHTML = `<p class="text-muted">${t("search_tips")}</p>`;
      return;
    }
    resultsEl.innerHTML = loadingRow();
    let result;
    try {
      result = await searchInternal(q);
    } catch (err) {
      resultsEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      return;
    }
    const { cases, documents } = result;
    if (cases.length === 0 && documents.length === 0) {
      resultsEl.innerHTML = noResults();
      return;
    }
    mountResultsPrint(root, "int-print-slot", () => ({
      title: t("print_search_results"),
      subtitle: t("tab_internal"),
      meta: criteriaMeta([[t("tab_internal"), q]]),
      sections: [
        cases.length
          ? {
              heading: t("nav_cases"),
              table: {
                columns: [t("case_number"), t("print_parties"), t("print_stage")],
                rows: cases.map((c) => [
                  `${c.case_number}/${c.case_year}`,
                  lang === "ar" ? c.parties_ar : c.parties_en,
                  t("stage_" + c.stage),
                ]),
              },
            }
          : null,
        documents.length
          ? {
              heading: t("nav_documents"),
              table: {
                columns: [t("file_name"), t("linked_case")],
                rows: documents.map((d) => [d.file_name, d.case_number || "—"]),
              },
            }
          : null,
      ].filter(Boolean),
    }));
    resultsEl.innerHTML = `
      ${cases.length ? `<h4 style="margin-top:0;">${t("nav_cases")}</h4><table class="data-table"><thead><tr><th>${t("case_number")}</th><th></th><th></th></tr></thead><tbody>
        ${cases.map((c) => `<tr>
          <td data-label="${t("case_number")}"><b>${c.case_number}/${c.case_year}</b><br><span class="text-muted">${escapeHtml(lang === "ar" ? c.parties_ar : c.parties_en)}</span></td>
          <td>${statusBadge(c.stage)}</td>
          <td>${resultActions("case", c.id, c.id, `${c.case_number}/${c.case_year}`, user)}</td>
        </tr>`).join("")}
      </tbody></table>` : ""}
      ${documents.length ? `<h4>${t("nav_documents")}</h4><table class="data-table"><thead><tr><th>${t("file_name")}</th><th>${t("linked_case")}</th><th></th></tr></thead><tbody>
        ${documents.map((d) => `<tr>
          <td data-label="${t("file_name")}">${icon("paperclip")} ${escapeHtml(d.file_name)}</td>
          <td data-label="${t("linked_case")}">${d.case_number || "—"}</td>
          <td>
            <button class="btn btn-outline btn-sm" data-preview-doc="${d.id}" title="${t("preview")}" aria-label="${t("preview")}">${icon("eye")}</button>
            ${d.case_id ? `<button class="btn btn-outline btn-sm" data-goto-case="${d.case_id}" title="${t("go_to_case")}" aria-label="${t("go_to_case")}">${icon("folder-open")}</button>` : ""}
          </td>
        </tr>`).join("")}
      </tbody></table>` : ""}
    `;
    if (cases.length) wireResultActions(resultsEl, user);
    if (documents.length) {
      resultsEl.querySelectorAll("[data-preview-doc]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const doc = documents.find((d) => d.id === Number(btn.getAttribute("data-preview-doc")));
          previewDocument(doc);
        });
      });
      resultsEl.querySelectorAll("[data-goto-case]").forEach((btn) => {
        btn.addEventListener("click", () => openCaseDetail(Number(btn.getAttribute("data-goto-case")), user));
      });
    }
  };

  root.querySelector("#btn-search").addEventListener("click", doSearch);
  root.querySelector("#f-internal").addEventListener("keydown", (e) => { if (e.key === "Enter") doSearch(); });
}
