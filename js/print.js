/**
 * Printing.
 *
 * The rule this module exists to enforce is that printing is never
 * "print whatever happens to be on screen". A raw `window.print()` on this
 * application would put the sidebar, the bottom navigation bar, the search
 * form, every Approve/Reject/Delete button, the notification dropdown and
 * whatever modal is open onto the paper, and would silently clip anything
 * inside a scrolling container (`.table-wrap`, the accordion bodies) because
 * only the visible slice of an overflow box is painted.
 *
 * Instead, each print action hands this module a *description of the record*
 * — title, identifying fields, and one or more sections of real data already
 * loaded by the page — and the module composes a self-contained document,
 * mounts it in a `#print-root` element that is invisible on screen and the
 * only visible thing on paper (see the `@media print` block in css/styles.css),
 * prints it, and removes it again.
 *
 * Consequences worth stating, because they are the point:
 *   - Nothing interactive is ever printed; buttons/inputs are not part of the
 *     composed document at all, rather than being hidden after the fact.
 *   - The printed content is the same data the user is looking at, taken from
 *     the same objects the page rendered from — this is not a mock-up, and it
 *     cannot drift from the screen.
 *   - Every date goes through `formatDate`, so paper gets exactly the same
 *     Kuwait (UTC+3) 12-hour AM/PM rendering as the screen.
 *   - Direction and language are inherited from the live document, so an
 *     Arabic session prints a right-to-left Arabic sheet.
 */

import { t, getLang } from "./i18n.js";
import { formatDate, escapeHtml, formatNumber } from "./ui.js";
import { getCurrentUser } from "./auth.js";

const PRINT_ROOT_ID = "print-root";

function cell(value) {
  if (value === null || value === undefined || value === "") return "—";
  return escapeHtml(value);
}

/** The Kuwait wall-clock moment this sheet was produced, 12-hour AM/PM.
 *  `formatDate` expects a server-style timestamp; an ISO string with the "Z"
 *  suffix already carries its zone, so it converts correctly. */
function printedAt() {
  return formatDate(new Date().toISOString(), { time: true });
}

function whoPrinted() {
  const u = getCurrentUser();
  if (!u) return "—";
  const name = getLang() === "ar" ? u.name_ar : u.name_en;
  return `${name || u.username} — ${t("role_" + u.role_code)}`;
}

function renderMeta(meta) {
  const rows = meta.filter((m) => m && m.label);
  if (!rows.length) return "";
  return `
    <dl class="print-meta">
      ${rows.map((m) => `<div><dt>${escapeHtml(m.label)}</dt><dd>${cell(m.value)}</dd></div>`).join("")}
    </dl>`;
}

function renderTable(section) {
  const { columns = [], rows = [] } = section.table;
  if (!rows.length) return `<p class="print-empty">${escapeHtml(t("print_no_rows"))}</p>`;
  return `
    <table class="print-table">
      <thead><tr>${columns.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
      <tbody>
        ${rows.map((r) => `<tr>${r.map((v) => `<td>${cell(v)}</td>`).join("")}</tr>`).join("")}
      </tbody>
    </table>`;
}

function renderList(section) {
  if (!section.items.length) return `<p class="print-empty">${escapeHtml(t("print_no_rows"))}</p>`;
  return `
    <ul class="print-list">
      ${section.items
        .map(
          (it) => `<li>
            <div class="pl-title">${cell(it.title)}</div>
            ${it.meta ? `<div class="pl-meta">${cell(it.meta)}</div>` : ""}
          </li>`
        )
        .join("")}
    </ul>`;
}

function renderPairs(section) {
  return `
    <dl class="print-pairs">
      ${section.pairs
        .filter((p) => p)
        .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${cell(value)}</dd></div>`)
        .join("")}
    </dl>`;
}

function renderSection(section) {
  if (!section) return "";
  let body;
  if (section.table) body = renderTable(section);
  else if (section.items) body = renderList(section);
  else if (section.pairs) body = renderPairs(section);
  else if (section.text !== undefined) body = `<p class="print-text">${cell(section.text)}</p>`;
  else return "";

  const count =
    section.table ? section.table.rows.length : section.items ? section.items.length : null;

  return `
    <section class="print-section">
      ${
        section.heading
          ? `<h2>${escapeHtml(section.heading)}${
              count !== null ? ` <span class="print-count">(${formatNumber(count)})</span>` : ""
            }</h2>`
          : ""
      }
      ${body}
    </section>`;
}

/**
 * Compose and print one record.
 *
 * @param {object} spec
 * @param {string} spec.title      Heading of the printed sheet.
 * @param {string} [spec.subtitle] One line of context under the title.
 * @param {Array}  [spec.meta]     `[{label, value}]` identity block.
 * @param {Array}  [spec.sections] `[{heading, table|items|pairs|text}]`.
 */
export function printRecord(spec) {
  // A previous sheet can still be mounted if the browser never fired
  // `afterprint` (some print dialogs are dismissed without it). Clearing
  // first guarantees exactly one sheet is ever in the DOM.
  document.getElementById(PRINT_ROOT_ID)?.remove();

  const lang = getLang();
  const root = document.createElement("div");
  root.id = PRINT_ROOT_ID;
  root.setAttribute("dir", document.documentElement.dir || (lang === "ar" ? "rtl" : "ltr"));
  root.setAttribute("lang", lang);
  root.setAttribute("aria-hidden", "true");

  root.innerHTML = `
    <header class="print-head">
      <div class="print-brand">
        <div class="pb-name">${escapeHtml(t("app_name"))}</div>
        <div class="pb-sub">${escapeHtml(t("firm_name"))}</div>
      </div>
      <div class="print-issued">
        <div><span>${escapeHtml(t("print_generated_at"))}:</span> <b>${escapeHtml(printedAt())}</b></div>
        <div><span>${escapeHtml(t("print_generated_by"))}:</span> <b>${escapeHtml(whoPrinted())}</b></div>
      </div>
    </header>

    <h1 class="print-title">${escapeHtml(spec.title || "")}</h1>
    ${spec.subtitle ? `<p class="print-subtitle">${escapeHtml(spec.subtitle)}</p>` : ""}
    ${renderMeta(spec.meta || [])}
    ${(spec.sections || []).map(renderSection).join("")}

    <footer class="print-foot">${escapeHtml(t("print_timezone_note"))}</footer>
  `;

  document.body.appendChild(root);

  const cleanup = () => {
    document.getElementById(PRINT_ROOT_ID)?.remove();
    window.removeEventListener("afterprint", cleanup);
  };
  window.addEventListener("afterprint", cleanup);

  // Let the browser lay the sheet out before opening the dialog; without a
  // frame, a long table can be measured at zero height and paginate wrongly.
  requestAnimationFrame(() => window.print());
}

/** The standard Print button markup, so every call site looks the same. */
export function printButton(id, extraClass = "btn-outline") {
  return `<button type="button" class="btn ${extraClass} btn-sm" id="${id}"
    title="${escapeHtml(t("print_hint"))}" aria-label="${escapeHtml(t("print"))}"><i class="fa-solid fa-print"></i> ${escapeHtml(t("print"))}</button>`;
}
