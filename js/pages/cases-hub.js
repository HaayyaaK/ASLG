/**
 * The Cases page: one sidebar entry, two contained tabs (Merge A, Sept 2026
 * overhaul) -- "My Cases" (js/pages/cases.js) and "Official Search Engine"
 * (js/pages/search.js). Both page modules are mounted unchanged into their
 * own tab pane; this file owns only the tab bar, the permission gate, the
 * URL, and the Refresh button. It exists as a separate module rather than
 * living in cases.js because search.js already imports openCaseDetail from
 * cases.js, and cases.js importing search.js back would be a circular import.
 *
 * Tabs are mounted lazily on first activation and then kept, so switching
 * back and forth never re-renders a tab -- search results and filters
 * survive the switch, and no request is repeated. The shared case list
 * underneath both tabs comes from api.js::listCasesCached.
 */
import { t } from "../i18n.js";
import { getPermission, invalidateCasesCache } from "../api.js";
import { icon, escapeHtml } from "../ui.js";
import * as casesPage from "./cases.js";
import * as searchPage from "./search.js";

const SECTIONS = [
  { key: "mine", label: "cases_tab_mine", icon: "folder-open", page: casesPage, perm: "cases" },
  { key: "search", label: "nav_search", icon: "magnifying-glass", page: searchPage, perm: "search" },
];

/** The tabs the signed-in role may see. A Client's `search` permission is
 *  "none", so a Client gets only My Cases -- and with one section the tab
 *  bar is not rendered at all. The server independently refuses every
 *  /api/search/* call for that role; this only decides what is drawn. */
export function visibleSections() {
  return SECTIONS.filter((s) => getPermission(s.perm) !== "none");
}

let mountedPages = [];

export function destroy() {
  mountedPages.forEach((p) => p.destroy?.());
  mountedPages = [];
}

export async function render(container, user) {
  destroy();
  const sections = visibleSections();
  const segment = location.hash.replace(/^#\//, "").split("/")[1] || "";
  const requested = sections.find((s) => s.key === segment);
  // Any other second segment ("active", "today-hearings") is a My Cases
  // filter that cases.js reads itself; keep it so leaving the search tab
  // and coming back restores the filtered list the user arrived with.
  const mineHash = segment && segment !== "search" ? `#/cases/${segment}` : "#/cases";
  const hashFor = (s) => (s.key === "search" ? "#/cases/search" : mineHash);
  let active = requested || sections[0];

  // #/cases/search reached by a role that can't search (a Client following
  // an old link): drop the segment so the URL doesn't claim a tab that isn't
  // there. replaceState, not a hash assignment: no history entry, no
  // re-entrant hashchange.
  if (segment === "search" && !requested) history.replaceState(null, "", mineHash);

  const showTabs = sections.length > 1;
  container.innerHTML = `
    <div class="hub-toolbar">
      ${
        showTabs
          ? `<div class="hub-tabs" role="tablist" aria-label="${escapeHtml(t("cases_hub_tabs_label"))}">
              ${sections
                .map(
                  (s) => `
                <button type="button" class="hub-tab" role="tab" id="hub-tab-${s.key}" data-section="${s.key}"
                        aria-controls="hub-pane-${s.key}" aria-selected="false" tabindex="-1">
                  ${icon(s.icon)}<span>${escapeHtml(t(s.label))}</span>
                </button>`
                )
                .join("")}
            </div>`
          : "<span></span>"
      }
      <button type="button" class="btn btn-outline btn-sm" id="hub-refresh" title="${escapeHtml(t("cases_hub_refresh_hint"))}">
        ${icon("arrows-rotate")} ${escapeHtml(t("cases_hub_refresh"))}
      </button>
    </div>
    ${sections
      .map(
        (s) => `<div class="hub-pane" id="hub-pane-${s.key}" ${showTabs ? `role="tabpanel" aria-labelledby="hub-tab-${s.key}"` : ""} hidden></div>`
      )
      .join("")}
  `;

  const mounted = new Set();

  function activate(section, { focus = false } = {}) {
    active = section;
    container.querySelectorAll(".hub-tab").forEach((tab) => {
      const isActive = tab.getAttribute("data-section") === section.key;
      tab.setAttribute("aria-selected", String(isActive));
      tab.tabIndex = isActive ? 0 : -1;
      if (isActive && focus) tab.focus();
    });
    sections.forEach((s) => {
      container.querySelector(`#hub-pane-${s.key}`).hidden = s.key !== section.key;
    });
    if (location.hash !== hashFor(section)) history.replaceState(null, "", hashFor(section));
    if (!mounted.has(section.key)) {
      mounted.add(section.key);
      mountedPages.push(section.page);
      const pane = container.querySelector(`#hub-pane-${section.key}`);
      // Same failure net app.js puts around a whole page render, scoped to
      // the tab: a failed tab shows its error and leaves the other tab usable.
      Promise.resolve()
        .then(() => section.page.render(pane, user))
        .catch((err) => {
          console.error("[ASLG] Cases tab render failed:", err);
          pane.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon("triangle-exclamation")}</div>${escapeHtml(err?.message || t("unexpected_error"))}</div>`;
        });
    }
  }

  container.querySelectorAll(".hub-tab").forEach((tab) => {
    tab.addEventListener("click", () => activate(sections.find((s) => s.key === tab.getAttribute("data-section"))));
  });

  // WAI-ARIA tabs keyboard pattern: arrows move between tabs, Home/End jump.
  // "Next" follows reading direction, so ArrowLeft is next under RTL.
  container.querySelector(".hub-tabs")?.addEventListener("keydown", (e) => {
    // Relative to the FOCUSED tab (the WAI-ARIA definition), falling back to
    // the selected one. The two only differ if focus was placed on an
    // unselected tab programmatically -- they are tabindex=-1 -- but the
    // pattern is defined by focus, so follow it exactly.
    const focusedKey = document.activeElement?.closest?.(".hub-tab")?.getAttribute("data-section");
    const focusedIdx = sections.findIndex((s) => s.key === focusedKey);
    const i = focusedIdx >= 0 ? focusedIdx : sections.indexOf(active);
    const rtl = document.documentElement.dir === "rtl";
    let next = null;
    if (e.key === (rtl ? "ArrowLeft" : "ArrowRight")) next = sections[(i + 1) % sections.length];
    else if (e.key === (rtl ? "ArrowRight" : "ArrowLeft")) next = sections[(i - 1 + sections.length) % sections.length];
    else if (e.key === "Home") next = sections[0];
    else if (e.key === "End") next = sections[sections.length - 1];
    if (!next) return;
    e.preventDefault();
    activate(next, { focus: true });
  });

  container.querySelector("#hub-refresh").addEventListener("click", () => {
    invalidateCasesCache();
    render(container, user);
  });

  activate(active);
}
