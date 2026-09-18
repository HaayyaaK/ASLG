import { getLang, t } from "./i18n.js";

export function toast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transition = "opacity .25s";
    setTimeout(() => el.remove(), 250);
  }, 3200);
}

/** The firm operates in Kuwait; every user-facing time is shown in this zone
 *  regardless of where the viewer's device happens to be set. */
export const DISPLAY_TIMEZONE = "Asia/Kuwait";

/**
 * Parse a timestamp coming from this application's API.
 *
 * The backend stores and returns naive UTC — `datetime.utcnow()` throughout,
 * with the MySQL session pinned to +00:00 (see backend/app/database.py) — so
 * the JSON looks like "2026-09-13T10:00:00" with no zone suffix. JavaScript
 * treats a bare date-time like that as the *viewer's local* time, which on
 * this UTC+3 server silently rendered every timestamp three hours earlier
 * than the instant it actually represents. Appending "Z" pins it to UTC so
 * the conversion below is correct.
 */
export function parseServerDate(iso) {
  if (!iso) return null;
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(iso);
  return new Date(hasZone ? iso : `${iso}Z`);
}

export function formatDate(iso, opts = {}) {
  if (!iso) return "—";
  const d = parseServerDate(iso);
  const lang = getLang();
  // "ar-KW" alone renders Eastern Arabic-Indic digits (٠١٢٣...) by default —
  // the "-u-nu-latn" Unicode extension keeps Arabic month/weekday names but
  // forces Western 0-9 digits, per the app-wide "English digits only" rule.
  const text = d.toLocaleString(lang === "ar" ? "ar-KW-u-nu-latn" : "en-GB", {
    timeZone: DISPLAY_TIMEZONE,
    year: "numeric", month: "short", day: "numeric",
    hour: opts.time ? "numeric" : undefined,
    minute: opts.time ? "2-digit" : undefined,
    // Legal staff read court times as "9:30 AM", not "09:30".
    hour12: opts.time ? true : undefined,
  });
  // en-GB renders the meridiem lowercase ("1:00 pm"); the firm's documents and
  // the rest of this UI use the uppercase form.
  return text.replace(/\b(am|pm)\b/gi, (m) => m.toUpperCase());
}

// Centralized numeric formatting so any future toLocaleString() need goes
// through one place already forcing Western digits, instead of each call
// site risking the same Eastern Arabic-Indic default as formatDate above.
export function formatNumber(n) {
  return Number(n).toLocaleString("en-US");
}

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function openModal(title, bodyHtml, opts = {}) {
  closeModal();
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.id = "active-modal";
  overlay.innerHTML = `
    <div class="modal-box" style="${opts.wide ? "max-width:960px" : ""}">
      <div class="modal-header">
        <h3>${title}</h3>
        <button class="modal-close" data-close-modal aria-label="${escapeHtml(t("close"))}" title="${escapeHtml(t("close"))}">&times;</button>
      </div>
      <div class="modal-body">${bodyHtml}</div>
    </div>`;
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add("open"));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay || e.target.hasAttribute("data-close-modal")) closeModal();
  });
  // Esc closes the topmost modal from anywhere, not just when the close
  // button itself has focus — the listener is removed again in closeModal()
  // so it never piles up across repeated open/close cycles.
  document.addEventListener("keydown", handleModalEscape);
  return overlay;
}

function handleModalEscape(e) {
  if (e.key === "Escape") closeModal();
}

export function closeModal() {
  const existing = document.getElementById("active-modal");
  if (existing) existing.remove();
  document.removeEventListener("keydown", handleModalEscape);
}

export function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/**
 * Hub pages (js/hub.js) whose non-default tabs occupy the segment after the
 * page name: in "#/notifications/reminders/overdue" the "reminders" names a
 * tab, so the filter is the segment after it.
 */
const HUB_TAB_SEGMENTS = { cases: ["search"], notifications: ["reminders"] };

/**
 * The page's filter segment, e.g. "#/documents/pending" -> "pending",
 * "#/notifications/reminders/overdue" -> "overdue". Used by the Dashboard's
 * stat cards to open a destination already filtered to the exact rows the
 * number counted.
 *
 * app.js's router only reads the FIRST segment when picking a page, so the
 * extra segments are free to carry intent without needing new routes.
 */
export function routeFilter() {
  const segs = location.hash.replace(/^#\//, "").split("/");
  const tabSegment = HUB_TAB_SEGMENTS[segs[0]]?.includes(segs[1]);
  return segs[tabSegment ? 2 : 1] || "";
}

/**
 * True only for the automatic follow-up nudges produced by the backend's
 * notification engine (backend/app/escalation.py::_nudge_messages).
 *
 * Checking `type === "system"` alone is not enough: the notification type
 * column is a fixed MySQL ENUM that cannot be extended by the application's
 * database account, and "system" is already used for genuine system messages
 * such as "System backup completed successfully" — which is not a nudge and
 * must not be badged as one. The message prefix is the reliable signal
 * because this application generates both sides of it.
 */
export function isSmartNudge(n) {
  if (!n || n.type !== "system") return false;
  const en = n.message_en || "";
  const ar = n.message_ar || "";
  return en.startsWith("Smart Follow-up") || en.startsWith("System follow-up") || ar.startsWith("متابعة تلقائية");
}

/**
 * The "* Required field" legend shown once under a form that has any
 * mandatory fields, so the asterisk is explained rather than assumed.
 * Which fields are mandatory is taken from the API request schemas in
 * backend/app/schemas.py, which in turn match the NOT NULL columns in
 * db/schema.sql — front end and back end cannot disagree.
 */
export function requiredNote() {
  return `<p class="required-note"><span class="req-star">*</span> ${t("required_field_note")}</p>`;
}

/**
 * Makes an existing mouse click target keyboard-operable: focusable,
 * announced as a button, and Enter/Space fire its existing click handler.
 * For targets that hold block content and so can't just be a <button> (a
 * notification row, an upload dropzone); anything that CAN be a <button>
 * should be one instead.
 */
export function makeKeyboardActivatable(el) {
  if (!el.hasAttribute("role")) el.setAttribute("role", "button");
  el.tabIndex = 0;
  el.addEventListener("keydown", (e) => {
    if (e.target !== el || (e.key !== "Enter" && e.key !== " ")) return;
    e.preventDefault();
    el.click();
  });
}

export function icon(name, extraClass = "") {
  return `<i class="fa-solid fa-${name} ${extraClass}"></i>`;
}

// Single shared brand-mark implementation for every location that shows
// the logo (sidebar, login screen). Tries /assets/logo.png; the inline
// onerror swap to the text fallback is synchronous with the image's own
// load failure, so app startup never depends on the file existing and a
// missing/broken asset never shows as a broken-image icon.
export function brandMark(extraClass = "") {
  const cls = `brand-mark${extraClass ? " " + extraClass : ""}`;
  return `
    <img class="${cls} brand-logo-img" src="/assets/logo.png" alt="${escapeHtml(t("app_name"))}"
      onerror="this.style.display='none';this.nextElementSibling.style.display='flex';" />
    <div class="${cls}" style="display:none;">AS</div>`;
}

// Role identity: same icon + semantic color for a given role everywhere a
// user avatar is shown, instead of the old plain-initials circle. Colors
// reuse existing design tokens (role-avatar-* classes in styles.css).
const ROLE_AVATAR = {
  Admin: { icon: "user-shield", cls: "role-avatar-admin" },
  Lawyer: { icon: "scale-balanced", cls: "role-avatar-lawyer" },
  consultant: { icon: "user-tie", cls: "role-avatar-consultant" },
  delegate: { icon: "user-clock", cls: "role-avatar-delegate" },
  User: { icon: "user", cls: "role-avatar-client" },
};

export function roleAvatar(user, extraStyle = "") {
  const cfg = ROLE_AVATAR[user.role_code] || ROLE_AVATAR.User;
  const name = getLang() === "ar" ? user.name_ar : user.name_en;
  const roleLabel = t("role_" + user.role_code);
  const label = `${name || ""} — ${roleLabel}`;
  return `<span class="quick-avatar ${cfg.cls}"${extraStyle ? ` style="${extraStyle}"` : ""} role="img" aria-label="${escapeHtml(label)}" title="${escapeHtml(label)}">${icon(cfg.icon)}</span>`;
}

