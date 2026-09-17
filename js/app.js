import { t, getLang, setLang, applyLangToDocument } from "./i18n.js";
import { getPermission, listNotifications } from "./api.js";
import { getCurrentUser, logout } from "./auth.js";
import { icon, brandMark, roleAvatar, toast, escapeHtml } from "./ui.js";
import { startIdleTimer, stopIdleTimer } from "./idle.js";
import * as loginPage from "./pages/login.js";
import * as dashboardPage from "./pages/dashboard.js";
import * as searchPage from "./pages/search.js";
import * as casesPage from "./pages/cases.js";
import * as documentsPage from "./pages/documents.js";
import * as notificationsPage from "./pages/notifications.js";
import * as remindersPage from "./pages/reminders.js";
import * as usersPage from "./pages/users.js";
import * as activityLogPage from "./pages/activity-log.js";
import * as deadlinesPage from "./pages/deadlines.js";
import * as adminRulesPage from "./pages/admin-rules.js";

const ROUTES = [
  { path: "dashboard", perm: "dashboard", icon: "house", label: "nav_dashboard", shortLabel: "nav_dashboard_short", page: dashboardPage },
  { path: "search", perm: "search", icon: "magnifying-glass", label: "nav_search", shortLabel: "nav_search_short", page: searchPage },
  { path: "cases", perm: "cases", icon: "folder-open", label: "nav_cases", shortLabel: "nav_cases", page: casesPage },
  { path: "documents", perm: "documents", icon: "file-lines", label: "nav_documents", shortLabel: "nav_documents_short", page: documentsPage },
  { path: "reminders", perm: "reminders", icon: "clock-rotate-left", label: "nav_reminders", shortLabel: "nav_reminders_short", page: remindersPage },
  { path: "deadlines", perm: "deadlines", icon: "hourglass-half", label: "nav_deadlines", shortLabel: "nav_deadlines_short", page: deadlinesPage },
  { path: "notifications", perm: "notifications", icon: "bell", label: "nav_notifications", shortLabel: "nav_notifications_short", page: notificationsPage },
  { path: "users", perm: "users", icon: "user-gear", label: "nav_users", shortLabel: "nav_users_short", page: usersPage },
  // Reuses the "users" permission key on purpose: only the Admin role has
  // non-"none" access to it today, which is exactly the "IT Admin only"
  // rule this nav entry needs — no new permission module was introduced
  // just for this. The real security boundary is server-side regardless
  // (every /api/activity-log/* route independently requires the Admin
  // role — see backend/app/routers/activity_log.py), so this only ever
  // controls whether the nav entry/page render, never actual access.
  { path: "activity-log", perm: "users", icon: "clipboard-list", label: "nav_activity_log", shortLabel: "nav_activity_log_short", page: activityLogPage },
  { path: "rules-admin", perm: "rules_admin", icon: "gavel", label: "nav_rules_admin", shortLabel: "nav_rules_admin_short", page: adminRulesPage },
];

const MAX_PRIMARY_TABS = 4;

const root = document.getElementById("app-root");
let activePage = null;

// Accessibility: every form field in the app renders as a bare
// `<label>` sibling of its `<input>/<select>/<textarea>` inside a
// `.form-group` wrapper (login, search, cases, documents, reminders,
// users — all of them), with no `for`/`id` pairing, which is exactly
// what triggers the browser's "a <label> isn't associated with a form
// field" warning. Rather than hand-adding a matching id/for pair at each
// of the several dozen call sites (high effort, easy to typo/miss one,
// and every future .form-group anywhere would need the same treatment
// repeated by hand), this observes the whole document body once and
// auto-wires any bare .form-group label it finds — covers every current
// page and modal (modals mount on document.body, outside #app-root) and
// every future one, with no per-page-module changes required.
let labelAutoId = 0;
function wireFormLabels(scope) {
  scope.querySelectorAll(".form-group > label:not([for])").forEach((label) => {
    const control = label.parentElement.querySelector("input, select, textarea");
    if (!control) return;
    if (!control.id) control.id = `fld-auto-${++labelAutoId}`;
    label.setAttribute("for", control.id);
  });
}
new MutationObserver(() => wireFormLabels(document.body)).observe(document.body, { childList: true, subtree: true });

/**
 * Last-resort visibility for failures that would otherwise be silent.
 *
 * Page modules are `async render(container, user)`. Before this existed the
 * router called them without awaiting and without a catch, so any rejection
 * — a failed request, a typo in a page module — became an unhandled promise:
 * nothing logged to the user, no error state, and the page left showing
 * whatever partial markup it had written, which is almost always a spinner.
 * An operator cannot tell that apart from the application having frozen, and
 * that is exactly how the freeze on this deployment was described.
 *
 * These two handlers are the net under everything the explicit handling
 * below might still miss. They only surface the problem; they never try to
 * recover, because a handler that guesses at recovery hides the next bug.
 */
function installGlobalErrorHandlers() {
  window.addEventListener("unhandledrejection", (e) => {
    console.error("[ASLG] Unhandled promise rejection:", e.reason);
    toast(e.reason?.message || t("unexpected_error"), "error");
  });
  window.addEventListener("error", (e) => {
    console.error("[ASLG] Uncaught error:", e.error || e.message);
  });
}

function boot() {
  installGlobalErrorHandlers();
  applyLangToDocument();
  const user = getCurrentUser();
  if (user) {
    renderShell(user);
  } else {
    renderLogin();
  }
  window.addEventListener("hashchange", handleRoute);
}

function renderLogin() {
  if (activePage?.destroy) activePage.destroy();
  stopIdleTimer();
  activePage = null;
  loginPage.render(root, (user) => {
    location.hash = "#/dashboard";
    renderShell(user);
  });
}

function currentRoutePath() {
  const hash = location.hash.replace(/^#\//, "") || "dashboard";
  return hash.split("/")[0];
}

function renderShell(user) {
  const lang = getLang();
  const visibleRoutes = ROUTES.filter((r) => getPermission(r.perm) !== "none");
  const primaryRoutes = visibleRoutes.slice(0, MAX_PRIMARY_TABS);
  const moreRoutes = visibleRoutes.slice(MAX_PRIMARY_TABS);

  root.innerHTML = `
    <div class="app-shell">
      <aside class="sidebar" id="sidebar">
        <div class="sidebar-brand">
          ${brandMark()}
          <div>
            <div class="brand-text">${t("app_name")}</div>
            <div class="brand-sub">${t("firm_name")}</div>
          </div>
        </div>
        <nav class="sidebar-nav" id="sidebar-nav">
          ${visibleRoutes
            .map(
              (r) => `<div class="nav-item" data-route="${r.path}">
              <span class="nav-icon">${icon(r.icon)}</span><span>${t(r.label)}</span>
            </div>`
            )
            .join("")}
        </nav>
        <div class="sidebar-footer">
          <div class="sidebar-user">
            ${roleAvatar(user)}
            <div>
              <div class="u-name">${lang === "ar" ? user.name_ar : user.name_en}</div>
              <div class="u-role">${t("role_" + user.role_code)}</div>
            </div>
          </div>
          <button class="btn btn-outline btn-block btn-sm" id="logout-btn">${icon("right-from-bracket")} ${t("logout")}</button>
        </div>
      </aside>
      <div class="main-area">
        <header class="topbar">
          <div class="topbar-title" id="page-title">
            <span class="label-full"></span><span class="label-short"></span>
          </div>
          <div class="topbar-actions">
            <button class="icon-btn" id="lang-toggle" title="${t("lang_toggle")}">${icon("globe")}</button>
            <button class="icon-btn" id="notif-btn" title="${t("nav_notifications")}" aria-label="${t("nav_notifications")}">
              ${icon("bell")}<span class="icon-badge" id="notif-badge" style="display:none;"></span>
            </button>
            ${roleAvatar(user, "width:34px;height:34px;font-size:12px;")}
          </div>
        </header>
        <main class="page-content" id="page-content"></main>
      </div>

      <nav class="bottom-nav" id="bottom-nav">
        ${primaryRoutes
          .map(
            (r) => `<button class="bn-item" data-route="${r.path}" title="${t(r.label)}" aria-label="${t(r.label)}">
            ${icon(r.icon)}${r.path === "notifications" ? '<span class="bn-badge" id="bn-notif-badge" style="display:none;"></span>' : ""}
            <span>${t(r.shortLabel)}</span>
          </button>`
          )
          .join("")}
        <button class="bn-item" id="bn-more-btn" title="${t("more")}" aria-label="${t("more")}">
          ${icon("ellipsis")}
          <span>${t("more")}</span>
        </button>
      </nav>

      <div class="bottom-sheet-overlay" id="bottom-sheet-overlay">
        <div class="bottom-sheet" id="bottom-sheet">
          <div class="bottom-sheet-handle"></div>
          ${moreRoutes
            .map(
              (r) => `<div class="bottom-sheet-item" data-route="${r.path}" data-close-sheet>
              ${icon(r.icon)} <span>${t(r.label)}</span>
            </div>`
            )
            .join("")}
          <div class="bottom-sheet-item" id="sheet-lang-toggle" data-close-sheet>
            ${icon("globe")} <span>${lang === "ar" ? "التبديل إلى الإنجليزية" : "Switch to Arabic"}</span>
          </div>
          <div class="bottom-sheet-item danger" id="sheet-logout" data-close-sheet>
            ${icon("right-from-bracket")} <span>${t("logout")}</span>
          </div>
        </div>
      </div>
    </div>
  `;

  wireShellEvents(user);
  refreshNotifBadge();
  // Started here rather than in boot(): the shell only renders for a
  // signed-in user, and renderShell() is also what a language toggle goes
  // through, so restarting the timer from a known-good state is correct in
  // both paths. renderLogin()/doLogout() stop it again.
  startIdleTimer(doLogout);
  handleRoute();
}

function wireShellEvents(user) {
  root.querySelectorAll("[data-route]").forEach((item) => {
    item.addEventListener("click", () => { location.hash = "#/" + item.getAttribute("data-route"); });
  });

  root.querySelector("#logout-btn").addEventListener("click", () => doLogout());

  root.querySelector("#lang-toggle").addEventListener("click", () => toggleLang(user));

  const sheetOverlay = root.querySelector("#bottom-sheet-overlay");
  const moreBtn = root.querySelector("#bn-more-btn");
  if (moreBtn) {
    moreBtn.addEventListener("click", () => sheetOverlay.classList.add("open"));
  }
  sheetOverlay?.addEventListener("click", (e) => {
    if (e.target === sheetOverlay) sheetOverlay.classList.remove("open");
  });
  root.querySelectorAll("[data-close-sheet]").forEach((el) => {
    el.addEventListener("click", () => sheetOverlay.classList.remove("open"));
  });
  root.querySelector("#sheet-logout")?.addEventListener("click", () => doLogout());
  root.querySelector("#sheet-lang-toggle")?.addEventListener("click", () => toggleLang(user));

  // The bell is a single, unambiguous action: it opens the Notifications page.
  // It used to toggle a preview dropdown that duplicated that page in a
  // cramped 360px panel — two ways to read the same list, with the dropdown
  // silently truncating to 8 rows and offering no "mark all read", no filters
  // and nothing on mobile. There is now exactly one place notifications are
  // read, so the bell and the nav entry cannot disagree.
  root.querySelector("#notif-btn").addEventListener("click", () => {
    location.hash = "#/notifications";
  });
}

function doLogout(opts = {}) {
  if (activePage?.destroy) activePage.destroy();
  stopIdleTimer();
  logout();
  location.hash = "";
  renderLogin();
  // Said after renderLogin() so the toast lands on the screen the user is
  // actually looking at, and only for an automatic sign-out: someone who
  // clicked Logout does not need to be told they were logged out.
  if (opts.reason === "idle") toast(t("idle_signed_out"), "info");
}

function toggleLang(user) {
  setLang(getLang() === "ar" ? "en" : "ar");
  renderShell(user);
}

async function refreshNotifBadge() {
  const badge = root.querySelector("#notif-badge");
  const bnBadge = root.querySelector("#bn-notif-badge");
  if (!badge && !bnBadge) return;
  try {
    const notifs = await listNotifications();
    const unread = notifs.filter((n) => !n.is_read).length;
    [badge, bnBadge].forEach((el) => {
      if (!el) return;
      if (unread > 0) {
        el.style.display = "block";
        el.textContent = unread > 9 ? "9+" : unread;
      } else {
        el.style.display = "none";
      }
    });
  } catch {
    // non-fatal: badge just stays hidden
  }
}

function handleRoute() {
  const user = getCurrentUser();
  if (!user) { renderLogin(); return; }

  const path = currentRoutePath();
  const route = ROUTES.find((r) => r.path === path) || ROUTES[0];
  const allowed = getPermission(route.perm) !== "none";
  const target = allowed ? route : ROUTES.find((r) => getPermission(r.perm) !== "none");

  root.querySelectorAll("[data-route]").forEach((item) => {
    item.classList.toggle("active", item.getAttribute("data-route") === target.path);
  });
  const titleEl = root.querySelector("#page-title");
  if (titleEl) {
    titleEl.querySelector(".label-full").textContent = t(target.label);
    titleEl.querySelector(".label-short").textContent = t(target.shortLabel);
  }

  if (activePage?.destroy) activePage.destroy();

  // Every page module is an `async render(container)`. It writes its markup,
  // awaits its data, and then goes back to `container.querySelector(...)` to
  // wire up buttons and fill panels. If the user navigates again while one of
  // those requests is still in flight, the old render resumes *after* the new
  // page has taken over the screen — and if both renders share one element,
  // every lookup the old one makes now returns null, which surfaces as an
  // uncaught "Cannot read properties of null" in the console.
  //
  // Guarding each individual lookup would mean auditing every call site in
  // every page and getting it right again in every page added later. Instead
  // the container itself is replaced on each navigation: the outgoing render
  // keeps a reference to the previous element, which is detached but still
  // fully populated, so its remaining lookups all resolve, its writes land
  // harmlessly off-screen, and it finishes quietly. The incoming render gets
  // a clean element of its own. No page module needs to know about this.
  const previousEl = root.querySelector("#page-content");
  if (!previousEl) return;
  const contentEl = document.createElement(previousEl.tagName);
  contentEl.id = "page-content";
  contentEl.className = previousEl.className;
  previousEl.replaceWith(contentEl);

  if (!allowed) {
    contentEl.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon("ban")}</div>${t("access_denied")}</div>`;
    activePage = null;
    return;
  }

  // Awaited via .catch() rather than left bare: see installGlobalErrorHandlers().
  // A rejection here used to leave the page on its own loading spinner with
  // nothing reported, which is indistinguishable from a frozen application.
  // Now it replaces the spinner with a real, actionable error state.
  Promise.resolve()
    .then(() => target.page.render(contentEl, user))
    .catch((err) => renderPageError(contentEl, err, user));
  activePage = target.page;
  refreshNotifBadge();
}

/**
 * What the user sees when a page fails to render.
 *
 * A timeout is called out separately from any other failure because it needs
 * a different response from the reader: "the server did not answer in time"
 * is usually the IIS worker cold-starting after its 20-minute idle shutdown
 * and Retry genuinely fixes it, whereas a 4xx/5xx message is a real answer
 * from the server and retrying will very likely say the same thing again.
 */
function renderPageError(contentEl, err, user) {
  console.error("[ASLG] Page render failed:", err);
  const isTimeout = err?.isTimeout === true;
  contentEl.innerHTML = `
    <div class="empty-state">
      <div class="empty-icon">${icon(isTimeout ? "clock" : "triangle-exclamation")}</div>
      <p><b>${escapeHtml(isTimeout ? t("page_timeout_title") : t("page_error_title"))}</b></p>
      <p class="text-muted">${escapeHtml(isTimeout ? t("page_timeout_body") : err?.message || t("unexpected_error"))}</p>
      <button class="btn btn-primary" id="page-error-retry">${icon("arrows-rotate")} ${escapeHtml(t("retry"))}</button>
    </div>`;
  contentEl.querySelector("#page-error-retry")?.addEventListener("click", () => handleRoute());
}

boot();
