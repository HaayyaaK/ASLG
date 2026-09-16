import { t, getLang } from "../i18n.js";
import { getDashboardStats, getUpcomingHearings, getDashboardTaskStats, getPermission, listCases, listDeadlines, listStaleOfficialSync, syncDeadlines } from "../api.js";
import { formatDate, icon, parseServerDate, toast, escapeHtml } from "../ui.js";
import { openCaseDetail } from "./cases.js";
import { canRequestUpdate, openRequestUpdateDialog } from "../request-update.js";
import { printRecord, printButton } from "../print.js";

/** Quick Actions is a browse-only shortcut, not a filtered/permissioned case
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

  container.innerHTML = `
    <div class="flex-between" style="margin-bottom:16px;">
      <h2 class="mt-0">${t("nav_dashboard")}</h2>
      ${printButton("dash-print")}
    </div>
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
    <div class="panel">
      <div class="panel-header"><h3>${t("upcoming_hearings")}</h3></div>
      <div class="panel-body" id="upcoming-hearings-list"></div>
    </div>
  `;

  const listEl = container.querySelector("#upcoming-hearings-list");
  let upcoming = [];
  // Kept so the Print button composes its sheet from exactly the numbers and
  // rows on screen, rather than issuing a second round of requests that could
  // return different values a moment later.
  let stats = null;
  let taskStats = null;

  // Wired before the first `await`, so the button works the moment it is
  // visible rather than only once every request has come back. `doPrint`
  // closes over the mutable variables above, so it always prints whatever has
  // loaded by the time it is clicked.
  container.querySelector("#dash-print").addEventListener("click", () => doPrint());

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
  }

  if (showDeadlineStats) {
    const deadlineGridEl = container.querySelector("#deadline-stat-grid");
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

  if (showQuickActions) {
    try {
      const cases = await listCases();
      renderQuickActions(container, cases, user);
    } catch {
      const body = container.querySelector("#qa-body");
      if (body) body.innerHTML = `<p class="text-muted">—</p>`;
    }
  }

  wireCards(container);

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

/**
 * Quick Actions — Admin/Lawyer only: jump straight into any case's details
 * without typing anything. Every existing case is grouped by its category
 * (case.category_ar/en, the same free-text field used on the Cases page and
 * the New Case form) so the whole caseload is browsable as chips rather than
 * one long list. Clicking a case reuses cases.js's own openCaseDetail, so the
 * "latest updates" shown are exactly the case-detail modal's timeline/notes —
 * nothing duplicated here.
 */
function quickActionsSkeleton() {
  return `
    <div class="panel qa-panel" id="qa-panel">
      <div class="panel-header"><h3>${t("quick_actions_title")}</h3></div>
      <div class="panel-body" id="qa-body">
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

let qaActiveCategory = null;

function renderQuickActions(container, cases, user) {
  const panel = container.querySelector("#qa-panel");
  const body = container.querySelector("#qa-body");
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

  if (!qaActiveCategory || !groups.has(qaActiveCategory)) qaActiveCategory = categories[0];

  body.innerHTML = `
    <p class="text-muted mt-0">${t("quick_actions_hint")}</p>
    <div class="qa-chip-row" id="qa-chip-row" role="tablist">
      ${categories
        .map(
          (cat) => `
        <button type="button" class="qa-chip ${cat === qaActiveCategory ? "active" : ""}"
                data-qa-cat="${escapeHtml(cat)}" role="tab" aria-selected="${cat === qaActiveCategory}">
          ${escapeHtml(cat)} <span class="qa-chip-count">${groups.get(cat).length}</span>
        </button>`
        )
        .join("")}
    </div>
    <div class="qa-case-list" id="qa-case-list"></div>
  `;

  const listEl = body.querySelector("#qa-case-list");

  function renderCaseList() {
    const rows = groups.get(qaActiveCategory) || [];
    const lang = getLang();
    listEl.innerHTML = rows
      .map(
        (c) => `
      <button type="button" class="qa-case-pill" data-qa-case="${c.id}">
        <span class="qa-case-number">${escapeHtml(`${c.case_number}/${c.case_year}`)}</span>
        <span class="qa-case-parties">${escapeHtml((lang === "ar" ? c.parties_ar : c.parties_en) || c.parties_ar || "")}</span>
      </button>`
      )
      .join("");
    listEl.querySelectorAll("[data-qa-case]").forEach((btn) => {
      btn.addEventListener("click", () => openCaseDetail(Number(btn.getAttribute("data-qa-case")), user));
    });
  }

  body.querySelectorAll("[data-qa-cat]").forEach((chip) => {
    chip.addEventListener("click", () => {
      qaActiveCategory = chip.getAttribute("data-qa-cat");
      body.querySelectorAll("[data-qa-cat]").forEach((c) => {
        const isActive = c === chip;
        c.classList.toggle("active", isActive);
        c.setAttribute("aria-selected", String(isActive));
      });
      renderCaseList();
    });
  });

  renderCaseList();
}
