import { t, getLang } from "../i18n.js";
import {
  getDashboardStats, getUpcomingHearings, getDashboardTaskStats, getPermission, listCases,
  listDeadlines, listStaleOfficialSync, syncDeadlines, listReminders, listNotifications,
  markAllNotificationsRead,
} from "../api.js";
import { formatDate, icon, parseServerDate, toast, escapeHtml, openModal, closeModal } from "../ui.js";
import { openCaseDetail } from "./cases.js";
import { canRequestUpdate, openRequestUpdateDialog } from "../request-update.js";
import { printRecord, printButton } from "../print.js";
import { usefulWebsitesPanel } from "../kuwait-websites.js";
import { mergeActionFeed } from "../action-feed.js";
import { initCommandPalette, destroyCommandPalette, openCommandPalette } from "../command-palette.js";

/** Quick Case Access is a browse-only shortcut, not a filtered/permissioned case
 *  list — it's for the two roles whose day-to-day job is "which case do I
 *  open next", matching the same Admin/Lawyer gate the rest of the app uses
 *  for hand-off actions (canRequestUpdate). Everyone else already reaches
 *  cases through the Cases page/search when their role permits it. */
function canSeeQuickActions(user) {
  return user?.role_code === "Admin" || user?.role_code === "Lawyer";
}

let intervalId = null;

export function destroy() {
  if (intervalId) clearInterval(intervalId);
  intervalId = null;
  destroyCommandPalette();
}

/**
 * Where each statistic actually leads.
 *
 * Every card on this page is a count of real rows, so every card can open the
 * page that lists those rows — previously all eight were inert numbers with no
 * affordance at all. The `filter` value is read by the destination page from
 * the URL hash (see cases.js / documents.js / reminders.js `readFilter`), so
 * these are real navigations into a pre-filtered real list, not invented routes.
 */
const CARD_TARGETS = {
  unread_notifications: { route: "notifications" },
  pending_documents: { route: "documents", filter: "pending" },
  today_hearings: { route: "cases", filter: "today-hearings" },
  active_cases: { route: "cases", filter: "active" },
  my_open_tasks: { route: "reminders", filter: "mine-open" },
  overdue_tasks: { route: "reminders", filter: "overdue" },
  pending_status_requests: { route: "reminders", filter: "status-requests" },
  tasks_i_assigned: { route: "reminders", filter: "assigned-by-me" },
  deadlines_due_week: { route: "deadlines", filter: "" },
  deadlines_overdue: { route: "deadlines", filter: "" },
  deadlines_provisional: { route: "deadlines", filter: "" },
  cases_sync_stale: { route: "deadlines", filter: "" },
};

function go(key) {
  const target = CARD_TARGETS[key];
  if (!target) return;
  location.hash = target.filter ? `#/${target.route}/${target.filter}` : `#/${target.route}`;
}

export async function render(container, user) {
  destroy();
  const lang = getLang();
  const showTaskStats = getPermission("reminders") !== "none";
  const showDeadlineStats = getPermission("deadlines") !== "none";
  const showQuickActions = canSeeQuickActions(user);

  // Quick Actions row gates — each mirrors the same permission check the
  // destination page/dialog already enforces, so a button never appears for
  // a role that would immediately hit a wall behind it.
  const canNewCase = ["full", "limited"].includes(getPermission("cases"));
  const canAssignTask = ["full", "edit"].includes(getPermission("reminders"));
  const canAskUpdate = canRequestUpdate(user);
  const canCheckPortal = getPermission("search") !== "none";

  container.innerHTML = `
    <div class="flex-between" style="margin-bottom:16px;">
      <h2 class="mt-0">${t("nav_dashboard")}</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
        <button type="button" class="btn btn-outline btn-sm" id="cmdk-trigger" title="${escapeHtml(t("cmdk_hint"))}">
          ${icon("magnifying-glass")} <span class="label-full">${t("cmdk_trigger_label")}</span> <kbd class="cmdk-kbd">Ctrl K</kbd>
        </button>
        ${printButton("dash-print")}
      </div>
    </div>
    ${quickActionsRowHtml({ canNewCase, canAssignTask, canAskUpdate, canCheckPortal, showDeadlineStats })}
    ${showQuickActions ? quickActionsSkeleton() : ""}
    <div class="stat-grid" id="stat-grid">
      ${[1, 2, 3, 4].map(() => `<div class="stat-card"><div class="text-muted">${icon("spinner", "fa-spin")}</div></div>`).join("")}
    </div>
    ${showTaskStats ? `
    <div class="stat-section-label">${t("stat_tasks_section")}</div>
    <div class="stat-grid" id="task-stat-grid">
      ${[1, 2, 3, 4].map(() => `<div class="stat-card"><div class="text-muted">${icon("spinner", "fa-spin")}</div></div>`).join("")}
    </div>` : ""}
    ${showDeadlineStats ? `
    <div class="stat-section-label">${t("stat_deadlines_section")}</div>
    <div class="stat-grid" id="deadline-stat-grid">
      ${[1, 2, 3, 4].map(() => `<div class="stat-card"><div class="text-muted">${icon("spinner", "fa-spin")}</div></div>`).join("")}
    </div>` : ""}

    <div class="dash-grid">
      <div class="dash-col-main">
        <div class="panel">
          <div class="panel-header"><h3>${t("upcoming_hearings")}</h3></div>
          <div class="panel-body" id="upcoming-hearings-list"></div>
        </div>
        ${actionStreamSkeleton()}
      </div>
      <div class="dash-col-side">
        ${showTaskStats ? myWeekSkeleton() : ""}
        <div class="panel" id="watched-rail-panel">
          <div class="panel-header"><h3>${icon("bookmark")} ${t("watched_title")}</h3></div>
          <div class="panel-body" id="watched-rail-body"><p class="text-muted mt-0">${icon("spinner", "fa-spin")}</p></div>
        </div>
        ${usefulWebsitesPanel()}
      </div>
    </div>
  `;

  const listEl = container.querySelector("#upcoming-hearings-list");
  let upcoming = [];
  // Kept so the Print button composes its sheet from exactly the numbers and
  // rows on screen, rather than issuing a second round of requests that could
  // return different values a moment later.
  let stats = null;
  let taskStats = null;
  let cases = [];
  let reminders = [];

  // Wired before the first `await`, so the button works the moment it is
  // visible rather than only once every request has come back. `doPrint`
  // closes over the mutable variables above, so it always prints whatever has
  // loaded by the time it is clicked.
  container.querySelector("#dash-print").addEventListener("click", () => doPrint());
  container.querySelector("#cmdk-trigger").addEventListener("click", () => openCommandPalette(buildCommandItems()));

  // Captured once and reused, rather than looked up again after each await.
  const statGridEl = container.querySelector("#stat-grid");
  const taskGridEl = container.querySelector("#task-stat-grid");

  try {
    const [loadedStats, hearings] = await Promise.all([getDashboardStats(), getUpcomingHearings()]);
    stats = loadedStats;
    upcoming = hearings;
    statGridEl.innerHTML = `
      ${statCard("unread_notifications", "bell", "var(--color-danger)", "var(--color-danger-bg)", stats.unread_notifications, t("stat_open_notifications"), t("card_action_view_notifications"))}
      ${statCard("pending_documents", "file-lines", "var(--color-accent)", "#fbf3e8", stats.pending_documents, t("stat_pending_docs"), t("card_action_view_documents"))}
      ${statCard("today_hearings", "clock", "var(--color-warning)", "var(--color-warning-bg)", stats.today_hearings, t("stat_today_hearings"), t("card_action_view_hearings"))}
      ${statCard("active_cases", "folder-open", "var(--color-info)", "var(--color-info-bg)", stats.active_cases, t("stat_active_cases"), t("card_action_view_cases"))}
    `;
  } catch {
    statGridEl.innerHTML = `<p class="text-muted">—</p>`;
  }

  if (showTaskStats) {
    try {
      taskStats = await getDashboardTaskStats();
      taskGridEl.innerHTML = `
        ${statCard("my_open_tasks", "list-check", "var(--color-info)", "var(--color-info-bg)", taskStats.my_open_tasks, t("stat_my_open_tasks"), t("card_action_view_tasks"))}
        ${statCard("overdue_tasks", "triangle-exclamation", "var(--color-danger)", "var(--color-danger-bg)", taskStats.overdue_tasks, t("stat_overdue_tasks"), t("card_action_view_tasks"))}
        ${statCard("pending_status_requests", "arrow-right-arrow-left", "var(--color-warning)", "var(--color-warning-bg)", taskStats.pending_status_requests, t("stat_pending_status_requests"), t("card_action_view_tasks"))}
        ${statCard("tasks_i_assigned", "paper-plane", "var(--color-accent)", "#fbf3e8", taskStats.tasks_i_assigned, t("stat_tasks_i_assigned"), t("card_action_view_tasks"))}
      `;
    } catch {
      taskGridEl.innerHTML = `<p class="text-muted">—</p>`;
    }
    try {
      reminders = await listReminders();
    } catch {
      reminders = [];
    }
    renderMyWeek(container, reminders, user);
  }

  async function loadDeadlineStats() {
    if (!showDeadlineStats) return;
    const deadlineGridEl = container.querySelector("#deadline-stat-grid");
    if (!deadlineGridEl) return;
    try {
      // Idempotent, mirroring escalation's own on-request contract — see
      // procedures.py's module docstring.
      await syncDeadlines();
      const [openDeadlines, stale] = await Promise.all([listDeadlines({ status_filter: "open" }), listStaleOfficialSync()]);
      const now = Date.now();
      const weekAhead = now + 7 * 86400000;
      const dueThisWeek = openDeadlines.filter((d) => new Date(d.due_at).getTime() <= weekAhead).length;
      const overdue = openDeadlines.filter((d) => new Date(d.due_at).getTime() < now).length;
      const provisional = openDeadlines.filter((d) => d.confidence === "provisional").length;
      deadlineGridEl.innerHTML = `
        ${statCard("deadlines_due_week", "hourglass-half", "var(--color-warning)", "var(--color-warning-bg)", dueThisWeek, t("stat_deadlines_due_week"), t("card_action_view_deadlines"))}
        ${statCard("deadlines_overdue", "triangle-exclamation", "var(--color-danger)", "var(--color-danger-bg)", overdue, t("stat_deadlines_overdue"), t("card_action_view_deadlines"))}
        ${statCard("deadlines_provisional", "circle-question", "var(--color-info)", "var(--color-info-bg)", provisional, t("stat_deadlines_provisional"), t("card_action_view_deadlines"))}
        ${statCard("cases_sync_stale", "rotate", "var(--color-accent)", "#fbf3e8", (stale.stale_case_ids || []).length, t("stat_cases_sync_stale"), t("card_action_view_deadlines"))}
      `;
    } catch {
      deadlineGridEl.innerHTML = `<p class="text-muted">—</p>`;
    }
  }
  await loadDeadlineStats();

  try {
    cases = await listCases();
  } catch {
    cases = [];
  }
  renderWatchedRail(container, cases, user);
  if (showQuickActions) {
    try {
      renderQuickActions(container, cases, user);
    } catch {
      const body = container.querySelector("#qcp-body");
      if (body) body.innerHTML = `<p class="text-muted">—</p>`;
    }
  }

  let notifications = [];
  try {
    notifications = await listNotifications();
  } catch {
    notifications = [];
  }
  const feedRows = mergeActionFeed(notifications, showTaskStats ? reminders : [], user);
  renderActionStream(container, feedRows, user);

  wireCards(container);
  wireQuickActionsRow(container);
  initCommandPalette(buildCommandItems);

  // ---------------- Quick Actions row handlers ----------------

  function wireQuickActionsRow(scope) {
    scope.querySelectorAll("[data-qa-action]").forEach((btn) => {
      btn.addEventListener("click", () => runQuickAction(btn.getAttribute("data-qa-action")));
    });
  }

  function runQuickAction(key) {
    switch (key) {
      case "new_case": return handleNewCase();
      case "assign_task": return handleAssignTask();
      case "mark_all_read": return handleMarkAllRead();
      case "request_update": return handleRequestUpdate();
      case "check_portal": return handleCheckPortal();
      case "sync_deadlines": return handleSyncDeadlinesAction();
      default: return undefined;
    }
  }

  function handleNewCase() {
    location.hash = "#/cases";
  }
  function handleAssignTask() {
    location.hash = "#/reminders";
  }
  function handleCheckPortal() {
    location.hash = "#/search";
  }
  async function handleMarkAllRead() {
    try {
      await markAllNotificationsRead();
      toast(t("qa_mark_all_read_success"), "success");
      notifications = await listNotifications().catch(() => notifications);
      renderActionStream(container, mergeActionFeed(notifications, showTaskStats ? reminders : [], user), user);
    } catch (err) {
      toast(err.message, "error");
    }
  }
  function handleRequestUpdate() {
    if (!canAskUpdate) return;
    openCaseQuickPicker(cases, "qa_request_update", (c) => {
      openRequestUpdateDialog({
        sourceType: "case",
        sourceRefId: c.id,
        contextLabel: `${c.case_number}/${c.case_year}`,
      });
    });
  }
  async function handleSyncDeadlinesAction() {
    if (!showDeadlineStats) return;
    await loadDeadlineStats();
    toast(t("qa_sync_deadlines_success"), "success");
  }

  function buildCommandItems() {
    const items = [];
    const navGroup = t("cmdk_group_navigate");
    const actionsGroup = t("cmdk_group_actions");
    const casesGroup = t("cmdk_group_cases");

    const navList = [
      { route: "dashboard", labelKey: "nav_dashboard", icon: "house", always: true },
      { route: "search", labelKey: "nav_search", icon: "magnifying-glass", perm: "search" },
      { route: "cases", labelKey: "nav_cases", icon: "folder-open", perm: "cases" },
      { route: "documents", labelKey: "nav_documents", icon: "file-lines", perm: "documents" },
      { route: "reminders", labelKey: "nav_reminders", icon: "clock-rotate-left", perm: "reminders" },
      { route: "deadlines", labelKey: "nav_deadlines", icon: "hourglass-half", perm: "deadlines" },
      { route: "notifications", labelKey: "nav_notifications", icon: "bell", always: true },
      { route: "users", labelKey: "nav_users", icon: "user-gear", perm: "users" },
      { route: "activity-log", labelKey: "nav_activity_log", icon: "clipboard-list", perm: "users" },
      { route: "rules-admin", labelKey: "nav_rules_admin", icon: "gavel", perm: "rules_admin" },
    ];
    navList.forEach((n) => {
      if (!n.always && getPermission(n.perm) === "none") return;
      const label = t(n.labelKey);
      items.push({
        label, hint: navGroup, group: navGroup, icon: n.icon,
        searchText: `${label} ${n.route}`.toLowerCase(),
        run: () => { location.hash = `#/${n.route}`; },
      });
    });

    const qa = (labelKey, iconName, run) => ({
      label: t(labelKey), hint: actionsGroup, group: actionsGroup, icon: iconName,
      searchText: t(labelKey).toLowerCase(), run,
    });
    if (canNewCase) items.push(qa("qa_new_case", "plus", handleNewCase));
    if (canAssignTask) items.push(qa("qa_assign_task", "user-plus", handleAssignTask));
    items.push(qa("qa_mark_all_read", "check-double", handleMarkAllRead));
    if (canAskUpdate) items.push(qa("qa_request_update", "rotate", handleRequestUpdate));
    if (canCheckPortal) items.push(qa("qa_check_portal", "arrow-up-right-from-square", handleCheckPortal));
    if (showDeadlineStats) items.push(qa("qa_sync_deadlines", "hourglass-half", handleSyncDeadlinesAction));

    const cLang = getLang();
    (cases || []).forEach((c) => {
      const parties = (cLang === "ar" ? c.parties_ar : c.parties_en) || c.parties_ar || "";
      items.push({
        label: `${c.case_number}/${c.case_year} — ${parties}`,
        hint: casesGroup, group: casesGroup, icon: "folder-open",
        searchText: `${c.case_number} ${c.automated_number || ""} ${c.parties_ar || ""} ${c.parties_en || ""}`.toLowerCase(),
        run: () => openCaseDetail(c.id, user),
      });
    });

    return items;
  }

  function doPrint() {
    if (!stats && !taskStats && upcoming.length === 0) {
      toast(t("print_nothing_to_print"), "info");
      return;
    }
    // The figures, then the hearings behind the most time-critical of them —
    // i.e. the sheet a lawyer would actually carry into the morning.
    const figures = [];
    if (stats) {
      figures.push(
        [t("stat_open_notifications"), stats.unread_notifications],
        [t("stat_pending_docs"), stats.pending_documents],
        [t("stat_today_hearings"), stats.today_hearings],
        [t("stat_active_cases"), stats.active_cases]
      );
    }
    if (taskStats) {
      figures.push(
        [t("stat_my_open_tasks"), taskStats.my_open_tasks],
        [t("stat_overdue_tasks"), taskStats.overdue_tasks],
        [t("stat_pending_status_requests"), taskStats.pending_status_requests],
        [t("stat_tasks_i_assigned"), taskStats.tasks_i_assigned]
      );
    }
    printRecord({
      title: t("print_dashboard_title"),
      subtitle: t("firm_name"),
      sections: [
        figures.length
          ? { heading: t("nav_dashboard"), table: { columns: [t("print_statistic"), t("print_value")], rows: figures } }
          : null,
        {
          heading: t("upcoming_hearings"),
          table: {
            columns: [t("case_number"), t("print_parties"), t("circuit"), t("session_date")],
            rows: upcoming.map((s) => [
              `${s.case_number}/${s.case_year}`,
              lang === "ar" ? s.parties_ar : s.parties_en,
              lang === "ar" ? s.circuit_ar : s.circuit_en,
              formatDate(s.session_at, { time: true }),
            ]),
          },
        },
      ].filter(Boolean),
    });
  }

  function renderList() {
    if (upcoming.length === 0) {
      listEl.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon("calendar-days")}</div>${t("no_hearings")}</div>`;
      return;
    }
    const mayAsk = canRequestUpdate(user);
    listEl.innerHTML = upcoming
      .map(
        (s) => `
        <div class="hearing-row">
          <div class="hearing-info">
            <div style="font-weight:700;font-size:13.5px;">${s.case_number}/${s.case_year} — ${lang === "ar" ? s.parties_ar : s.parties_en}</div>
            <div class="hearing-meta">${lang === "ar" ? s.circuit_ar : s.circuit_en} • ${formatDate(s.session_at, { time: true })}</div>
          </div>
          <div class="countdown-pill" data-target="${s.session_at}"></div>
          <div class="hearing-actions">
            <button class="btn btn-outline btn-sm" data-open-case="${s.case_id}" title="${t("open_case")}">${icon("folder-open")} ${t("open_case")}</button>
            ${mayAsk ? `<button class="btn btn-outline btn-sm" data-ask-case="${s.case_id}" data-label="${s.case_number}/${s.case_year}" title="${t("request_update")}">${icon("rotate")} ${t("request_update")}</button>` : ""}
          </div>
        </div>`
      )
      .join("");

    listEl.querySelectorAll("[data-open-case]").forEach((btn) => {
      btn.addEventListener("click", () => openCaseDetail(Number(btn.getAttribute("data-open-case")), user));
    });
    listEl.querySelectorAll("[data-ask-case]").forEach((btn) => {
      btn.addEventListener("click", () =>
        openRequestUpdateDialog({
          sourceType: "case",
          sourceRefId: Number(btn.getAttribute("data-ask-case")),
          contextLabel: btn.getAttribute("data-label"),
        })
      );
    });
    updateCountdowns();
  }

  function updateCountdowns() {
    listEl.querySelectorAll("[data-target]").forEach((pill) => {
      // parseServerDate, not new Date(): the API's naive timestamps are UTC,
      // and parsing them as local time made every countdown three hours out.
      const target = parseServerDate(pill.getAttribute("data-target")).getTime();
      const diff = target - Date.now();
      if (diff <= 0) {
        pill.innerHTML = `<span class="badge badge-muted">${t("status_done")}</span>`;
        return;
      }
      // Days / hours / minutes only. A seconds digit on a court date weeks
      // away was visual noise that redrew the whole row every second for no
      // information gain. The arithmetic below is unchanged — the seconds
      // unit is simply no longer rendered — and the tick stays at 1s so the
      // minutes value is never stale.
      const days = Math.floor(diff / 86400000);
      const hours = Math.floor((diff % 86400000) / 3600000);
      const mins = Math.floor((diff % 3600000) / 60000);
      const urgent = diff < 86400000 ? "urgent" : "";
      pill.innerHTML = `
        <div class="countdown-unit ${urgent}"><b>${days}</b><span>${t("countdown_days")}</span></div>
        <div class="countdown-unit ${urgent}"><b>${hours}</b><span>${t("countdown_hours")}</span></div>
        <div class="countdown-unit ${urgent}"><b>${mins}</b><span>${t("countdown_minutes")}</span></div>`;
    });
  }

  renderList();
  intervalId = setInterval(updateCountdowns, 1000);
}

function wireCards(container) {
  container.querySelectorAll("[data-card-key]").forEach((card) => {
    const key = card.getAttribute("data-card-key");
    card.addEventListener("click", () => go(key));
    // Keyboard parity: the card is a real control, so Enter/Space must work
    // for anyone not using a mouse.
    card.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        go(key);
      }
    });
  });
}

function statCard(key, iconName, color, bg, value, label, actionLabel) {
  return `
    <div class="stat-card stat-card-clickable" data-card-key="${key}"
         role="button" tabindex="0" aria-label="${label}: ${value}. ${actionLabel}" title="${actionLabel}">
      <div class="stat-icon" style="background:${bg};color:${color};">${icon(iconName)}</div>
      <div class="stat-value">${value}</div>
      <div class="stat-label">${label}</div>
      <div class="stat-action">${actionLabel} ${icon("arrow-right", "stat-action-arrow")}</div>
    </div>`;
}

// =====================================================================
// Quick Actions row (Sub-phase 3.4, Gap C) — six one-click shortcuts, not
// to be confused with the pre-existing "Quick Case Access" (.qcp-*) browse
// panel below, whose i18n key (`quick_actions_title`) predates this row and
// is left as-is.
// =====================================================================
function quickActionsRowHtml({ canNewCase, canAssignTask, canAskUpdate, canCheckPortal, showDeadlineStats }) {
  const items = [];
  if (canNewCase) items.push({ key: "new_case", iconName: "plus", label: t("qa_new_case") });
  if (canAssignTask) items.push({ key: "assign_task", iconName: "user-plus", label: t("qa_assign_task") });
  items.push({ key: "mark_all_read", iconName: "check-double", label: t("qa_mark_all_read") });
  if (canAskUpdate) items.push({ key: "request_update", iconName: "rotate", label: t("qa_request_update") });
  if (canCheckPortal) items.push({ key: "check_portal", iconName: "arrow-up-right-from-square", label: t("qa_check_portal") });
  if (showDeadlineStats) items.push({ key: "sync_deadlines", iconName: "hourglass-half", label: t("qa_sync_deadlines") });
  if (items.length === 0) return "";
  return `
    <div class="qa-actions-row" role="group" aria-label="${escapeHtml(t("qa_row_title"))}">
      ${items
        .map(
          (it) => `
        <button type="button" class="qa-action-btn" data-qa-action="${it.key}">
          ${icon(it.iconName)}<span>${it.label}</span>
        </button>`
        )
        .join("")}
    </div>`;
}

function openCaseQuickPicker(cases, titleKey, onPick) {
  if (!cases || cases.length === 0) {
    toast(t("qa_no_cases"), "info");
    return;
  }
  const lang = getLang();
  const overlay = openModal(
    t(titleKey),
    `
    <div class="form-group">
      <label>${t("linked_case")}</label>
      <select id="qa-case-picker">
        ${cases
          .map((c) => {
            const parties = (lang === "ar" ? c.parties_ar : c.parties_en) || c.parties_ar || "";
            return `<option value="${c.id}">${escapeHtml(`${c.case_number}/${c.case_year} — ${parties}`)}</option>`;
          })
          .join("")}
      </select>
    </div>
    <button class="btn btn-accent btn-block" id="qa-case-picker-go">${t("qa_picker_continue")}</button>
  `
  );
  overlay.querySelector("#qa-case-picker-go").addEventListener("click", () => {
    const id = Number(overlay.querySelector("#qa-case-picker").value);
    const c = cases.find((x) => x.id === id);
    closeModal();
    if (c) onPick(c);
  });
}

// =====================================================================
// Action Stream — merged notifications + open tasks (Sub-phase 3.4)
// =====================================================================
function actionStreamSkeleton() {
  return `
    <div class="panel astream-panel" id="astream-panel">
      <div class="panel-header"><h3>${icon("bolt")} ${t("astream_title")}</h3></div>
      <div class="panel-body" id="astream-body">
        <p class="text-muted mt-0">${icon("spinner", "fa-spin")}</p>
      </div>
    </div>`;
}

function renderActionStream(container, rows, user) {
  const body = container.querySelector("#astream-body");
  if (!body) return;
  if (rows.length === 0) {
    body.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon("circle-check")}</div>${t("astream_empty")}</div>`;
    return;
  }
  const lang = getLang();
  // Capped so the dashboard stays a summary, not a duplicate of the full
  // Notifications / Reminders pages it links out to.
  const shown = rows.slice(0, 12);
  body.innerHTML = `
    <div class="astream-list">${shown.map((row) => astreamRowHtml(row, lang)).join("")}</div>
    ${rows.length > shown.length ? `<a class="rail-more" href="#/notifications">${t("astream_view_all")}</a>` : ""}
  `;
  body.querySelectorAll("[data-astream-case]").forEach((el) => {
    el.addEventListener("click", () => openCaseDetail(Number(el.getAttribute("data-astream-case")), user));
  });
}

function astreamRowHtml(row, lang) {
  const { type, source, urgencyBucket } = row;
  const icons = { alert: "bell", system: "robot", task: "list-check" };
  const urgencyClass = urgencyBucket === 0 ? "astream-overdue" : urgencyBucket === 1 ? "astream-soon" : "";
  const caseLabel = source.caseRef ? `${source.caseRef.case_number}${source.caseRef.case_year ? "/" + source.caseRef.case_year : ""}` : null;
  const clickable = type === "task" && source.caseRef;
  const unreadDot = source.isRead === false ? `<span class="astream-dot" aria-hidden="true" title="${escapeHtml(t("astream_unread"))}"></span>` : "";
  const inner = `
      <span class="astream-icon astream-icon-${type}">${icon(icons[type] || "circle")}</span>
      <span class="astream-body-text">
        <span class="astream-title-line">${unreadDot}${escapeHtml(source.title || "")}</span>
        <span class="astream-meta">
          ${caseLabel ? `${escapeHtml(caseLabel)} • ` : ""}${formatDate(row.sortAt.toISOString(), { time: true })}
          ${urgencyBucket === 0 ? ` • <b class="astream-overdue-tag">${t("overdue")}</b>` : urgencyBucket === 1 ? ` • ${t("astream_due_soon")}` : ""}
        </span>
      </span>`;
  return clickable
    ? `<button type="button" class="astream-row ${urgencyClass} astream-clickable" data-astream-case="${source.caseRef.id}">${inner}</button>`
    : `<div class="astream-row ${urgencyClass}">${inner}</div>`;
}

// =====================================================================
// My Week widget (Sub-phase 3.4, Gap B feature 3)
// =====================================================================
function myWeekSkeleton() {
  return `
    <div class="panel myweek-panel" id="myweek-panel">
      <div class="panel-header"><h3>${icon("calendar-week")} ${t("myweek_title")}</h3></div>
      <div class="panel-body" id="myweek-body"><p class="text-muted mt-0">${icon("spinner", "fa-spin")}</p></div>
    </div>`;
}

function renderMyWeek(container, reminders, user) {
  const body = container.querySelector("#myweek-body");
  if (!body) return;
  const now = Date.now();
  const weekMs = 7 * 86400000;
  const mine = (reminders || []).filter((r) => r.assigned_to === user.id);
  const dueThisWeek = mine.filter((r) => r.status === "open" && parseServerDate(r.due_at).getTime() <= now + weekMs);
  const overdue = dueThisWeek.filter((r) => parseServerDate(r.due_at).getTime() < now);
  const resolvedThisWeek = mine.filter((r) => r.resolved_at && parseServerDate(r.resolved_at).getTime() >= now - weekMs);
  const total = dueThisWeek.length + resolvedThisWeek.length;
  const pct = total > 0 ? Math.round((resolvedThisWeek.length / total) * 100) : 0;
  body.innerHTML = `
    <div class="myweek-stats">
      <div class="myweek-stat"><span class="myweek-num ${overdue.length ? "myweek-num-danger" : ""}">${dueThisWeek.length}</span><span class="myweek-label">${t("myweek_due")}</span></div>
      <div class="myweek-stat"><span class="myweek-num myweek-num-success">${resolvedThisWeek.length}</span><span class="myweek-label">${t("myweek_resolved")}</span></div>
      ${overdue.length ? `<div class="myweek-stat"><span class="myweek-num myweek-num-danger">${overdue.length}</span><span class="myweek-label">${t("myweek_overdue")}</span></div>` : ""}
    </div>
    ${
      total > 0
        ? `<div class="myweek-progress" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100" aria-label="${escapeHtml(t("myweek_progress_label"))}">
             <div class="myweek-progress-fill" style="inline-size:${pct}%"></div>
           </div>`
        : `<p class="text-muted mt-0">${t("myweek_empty")}</p>`
    }
  `;
}

// =====================================================================
// Watched Cases rail (uses is_watching already returned by listCases())
// =====================================================================
function renderWatchedRail(container, cases, user) {
  const body = container.querySelector("#watched-rail-body");
  if (!body) return;
  const watched = (cases || []).filter((c) => c.is_watching);
  if (watched.length === 0) {
    body.innerHTML = `<p class="text-muted mt-0 rail-empty">${t("watched_empty")}</p>`;
    return;
  }
  const lang = getLang();
  body.innerHTML = `
    <div class="watched-rail-list">
      ${watched
        .slice(0, 6)
        .map((c) => {
          const parties = (lang === "ar" ? c.parties_ar : c.parties_en) || c.parties_ar || "";
          return `
        <button type="button" class="watched-rail-item" data-watched-case="${c.id}">
          <span class="watched-rail-num">${escapeHtml(`${c.case_number}/${c.case_year}`)}</span>
          <span class="watched-rail-party">${escapeHtml(parties)}</span>
          ${c.next_hearing_at ? `<span class="watched-rail-hearing">${icon("clock")} ${formatDate(c.next_hearing_at, { time: true })}</span>` : ""}
        </button>`;
        })
        .join("")}
    </div>
    ${watched.length > 6 ? `<a class="rail-more" href="#/cases">${t("watched_view_all")}</a>` : ""}
  `;
  body.querySelectorAll("[data-watched-case]").forEach((btn) => {
    btn.addEventListener("click", () => openCaseDetail(Number(btn.getAttribute("data-watched-case")), user));
  });
}

/**
 * Quick Case Access — Admin/Lawyer only: jump straight into any case's details
 * without typing anything. Every existing case is grouped by its category
 * (case.category_ar/en, the same free-text field used on the Cases page and
 * the New Case form) so the whole caseload is browsable as chips rather than
 * one long list. Clicking a case reuses cases.js's own openCaseDetail, so the
 * "latest updates" shown are exactly the case-detail modal's timeline/notes —
 * nothing duplicated here.
 */
function quickActionsSkeleton() {
  return `
    <div class="panel qcp-panel" id="qcp-panel">
      <div class="panel-header"><h3>${t("quick_actions_title")}</h3></div>
      <div class="panel-body" id="qcp-body">
        <p class="text-muted mt-0">${icon("spinner", "fa-spin")}</p>
      </div>
    </div>`;
}

/** category label the case should be grouped under, in the active language;
 *  falls back to "Uncategorized" so every case lands in exactly one chip. */
function categoryLabel(c) {
  const lang = getLang();
  const label = (lang === "ar" ? c.category_ar : c.category_en) || c.category_ar || c.category_en;
  return label || t("quick_actions_uncategorized");
}

// Common connector words that shouldn't be read as a party's initial (e.g.
// the "v." in "Al-Sabah v. Al-Rashidi" would otherwise produce "VA" instead
// of "AS"). Not exhaustive by design -- this feeds a visual nicety (the
// avatar badge), never anything the app relies on for correctness.
const INITIALS_CONNECTOR_RE = /^(v\.?|vs\.?|and|ضد)$/i;

/** Up to two initials from a case's party string, for the qcp-avatar
 *  badge -- ".AS" from "Al-Sabah v. Al-Rashidi", falling back to a single
 *  "?" for an empty/unusable string rather than rendering nothing. */
function partyInitials(text) {
  if (!text) return "?";
  const words = text.trim().split(/\s+/).filter((w) => w && !INITIALS_CONNECTOR_RE.test(w));
  const chars = words
    .slice(0, 2)
    .map((w) => w.replace(/[^A-Za-zء-ي]/g, "")[0])
    .filter(Boolean);
  return (chars.join("") || text[0] || "?").toUpperCase();
}

let qcpActiveCategory = null;

function renderQuickActions(container, cases, user) {
  const panel = container.querySelector("#qcp-panel");
  const body = container.querySelector("#qcp-body");
  if (!panel || !body) return;

  if (cases.length === 0) {
    body.innerHTML = `<p class="text-muted mt-0">${t("quick_actions_empty")}</p>`;
    return;
  }

  const groups = new Map();
  cases.forEach((c) => {
    const label = categoryLabel(c);
    if (!groups.has(label)) groups.set(label, []);
    groups.get(label).push(c);
  });
  // Real categories first (alphabetical), "Uncategorized" always last —
  // it's a fallback bucket, not something worth sorting to the top.
  const uncategorized = t("quick_actions_uncategorized");
  const categories = [...groups.keys()].sort((a, b) => {
    if (a === uncategorized) return 1;
    if (b === uncategorized) return -1;
    return a.localeCompare(b);
  });

  if (!qcpActiveCategory || !groups.has(qcpActiveCategory)) qcpActiveCategory = categories[0];

  body.innerHTML = `
    <p class="text-muted mt-0">${t("quick_actions_hint")}</p>
    <div class="qcp-chiprow" id="qcp-chiprow" role="tablist">
      ${categories
        .map(
          (cat) => `
        <button type="button" class="qcp-chip ${cat === qcpActiveCategory ? "active" : ""}"
                data-qcp-cat="${escapeHtml(cat)}" role="tab" aria-selected="${cat === qcpActiveCategory}">
          ${escapeHtml(cat)} <span class="qcp-chip-count">${groups.get(cat).length}</span>
        </button>`
        )
        .join("")}
    </div>
    <div class="qcp-grid" id="qcp-grid"></div>
  `;

  const listEl = body.querySelector("#qcp-grid");

  function renderCaseList() {
    const rows = groups.get(qcpActiveCategory) || [];
    const lang = getLang();
    listEl.innerHTML = rows
      .map((c) => {
        const parties = (lang === "ar" ? c.parties_ar : c.parties_en) || c.parties_ar || "";
        return `
      <button type="button" class="qcp-tile" data-qcp-case="${c.id}">
        <span class="qcp-avatar" aria-hidden="true">${escapeHtml(partyInitials(parties))}</span>
        <span class="qcp-tile-body">
          <span class="qcp-tile-num">${escapeHtml(`${c.case_number}/${c.case_year}`)}</span>
          <span class="qcp-tile-party">${escapeHtml(parties)}</span>
        </span>
      </button>`;
      })
      .join("");
    listEl.querySelectorAll("[data-qcp-case]").forEach((btn) => {
      btn.addEventListener("click", () => openCaseDetail(Number(btn.getAttribute("data-qcp-case")), user));
    });
  }

  body.querySelectorAll("[data-qcp-cat]").forEach((chip) => {
    chip.addEventListener("click", () => {
      qcpActiveCategory = chip.getAttribute("data-qcp-cat");
      body.querySelectorAll("[data-qcp-cat]").forEach((c) => {
        const isActive = c === chip;
        c.classList.toggle("active", isActive);
        c.setAttribute("aria-selected", String(isActive));
      });
      renderCaseList();
    });
  });

  renderCaseList();
}
