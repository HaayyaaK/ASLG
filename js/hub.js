/**
 * Hub pages: one sidebar entry whose page is a row of contained tabs, each
 * tab an existing page module mounted unchanged into its own pane. Shared by
 * the Cases hub (My Cases + Official Search Engine) and the Notifications hub
 * (Notifications + Reminders & Follow-ups) so the two cannot drift apart.
 *
 * Behavior:
 * - Permission gate: a section is shown only if its permission key isn't
 *   "none". With one visible section the tab bar is not drawn at all.
 * - URL: `#/<base>` is the default section, `#/<base>/<segment>` the others.
 *   Segments after that (a page's own filter, e.g. `#/cases/active` or
 *   `#/notifications/reminders/overdue`) are remembered per section, so
 *   leaving a tab and coming back restores its filtered view. Tab switches
 *   rewrite the URL with replaceState: no history entry, no re-render.
 * - A URL naming a section the role can't see (a Client following an old
 *   link) lands on the default section with the segment dropped.
 * - Sections mount lazily on first activation and then stay mounted, so
 *   switching tabs repeats no request and keeps each tab's state.
 * - CLICKING a tab -- including the already-selected one -- is the refresh
 *   control: it invalidates that section's cached lists and reloads it,
 *   showing a spinner on the tab until the reload settles. Programmatic
 *   activation (initial load, a route alias, arrow-key navigation) never
 *   forces a reload; it serves from the 60s cache.
 * - Keyboard: WAI-ARIA tabs pattern, arrows relative to the focused tab and
 *   reading-direction aware, Home/End, roving tabindex.
 *
 * A section's page module needs `render(container, user)` and may export
 * `refresh(container, user)` to reload in place without losing UI state
 * (the search tab uses this to keep its inputs and re-run its last search);
 * without one, a refresh re-renders the section.
 */
import { t } from "./i18n.js";
import { getPermission, invalidateListCache } from "./api.js";
import { icon, escapeHtml } from "./ui.js";

/**
 * @param {object} cfg
 * @param {string} cfg.base  route path, e.g. "cases"
 * @param {string} cfg.tabsLabelKey  i18n key naming the tablist for AT
 * @param {Array<{key:string, segment:string|null, label:string, icon:string,
 *   page:object, perm:string, lists:string[]}>} cfg.sections
 *   `segment: null` marks the default section; `lists` names the api.js list
 *   caches a click on this tab invalidates.
 */
export function createHub({ base, tabsLabelKey, sections }) {
  let mountedPages = [];

  function visibleSections() {
    return sections.filter((s) => getPermission(s.perm) !== "none");
  }

  function destroy() {
    mountedPages.forEach((p) => p.destroy?.());
    mountedPages = [];
  }

  async function render(container, user) {
    destroy();
    const visible = visibleSections();
    const segs = location.hash.replace(/^#\//, "").split("/").slice(1).filter(Boolean);
    const requested = visible.find((s) => s.segment && s.segment === segs[0]);
    const namesHiddenSection = !requested && sections.some((s) => s.segment && s.segment === segs[0]);
    const defaultSection = visible.find((s) => !s.segment) || visible[0];
    let active = requested || defaultSection;

    const tails = new Map();
    if (requested) tails.set(requested.key, segs.slice(1));
    else if (!namesHiddenSection) tails.set(defaultSection.key, segs);
    const hashFor = (s) => "#/" + [base, s.segment, ...(tails.get(s.key) || [])].filter(Boolean).join("/");

    if (namesHiddenSection) history.replaceState(null, "", hashFor(active));

    const showTabs = visible.length > 1;
    container.innerHTML = `
      ${
        showTabs
          ? `<div class="hub-toolbar">
              <div class="hub-tabs" role="tablist" aria-label="${escapeHtml(t(tabsLabelKey))}">
                ${visible
                  .map(
                    (s) => `
                  <button type="button" class="hub-tab" role="tab" id="hub-tab-${s.key}" data-section="${s.key}"
                          aria-controls="hub-pane-${s.key}" aria-selected="false" tabindex="-1"
                          title="${escapeHtml(`${t(s.label)} — ${t("hub_tab_refresh_hint")}`)}">
                    <span class="hub-tab-icon" aria-hidden="true">${icon(s.icon)}</span><span class="btn-label">${escapeHtml(t(s.label))}</span>
                  </button>`
                  )
                  .join("")}
              </div>
            </div>`
          : ""
      }
      ${visible
        .map((s) => `<div class="hub-pane" id="hub-pane-${s.key}" ${showTabs ? `role="tabpanel" aria-labelledby="hub-tab-${s.key}"` : ""} hidden></div>`)
        .join("")}
    `;

    const mounted = new Set();
    const loadTokens = new Map();

    function paneOf(s) {
      return container.querySelector(`#hub-pane-${s.key}`);
    }

    /** Runs a section's first mount or reload with the tab's loading state
     *  shown until it settles. The token makes a slower, older reload unable
     *  to clear the spinner of a newer one still in flight. */
    function load(section, work) {
      const token = (loadTokens.get(section.key) || 0) + 1;
      loadTokens.set(section.key, token);
      const tab = container.querySelector(`#hub-tab-${section.key}`);
      const pane = paneOf(section);
      tab?.classList.add("is-loading");
      pane.setAttribute("aria-busy", "true");
      const iconEl = tab?.querySelector(".hub-tab-icon");
      if (iconEl) iconEl.innerHTML = icon("spinner", "fa-spin");
      return Promise.resolve()
        .then(work)
        .catch((err) => {
          // Same failure net app.js puts around a whole page render, scoped
          // to the tab: a failed tab shows its error, the other stays usable.
          console.error(`[ASLG] ${base} tab "${section.key}" failed:`, err);
          pane.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon("triangle-exclamation")}</div>${escapeHtml(err?.message || t("unexpected_error"))}</div>`;
        })
        .finally(() => {
          if (loadTokens.get(section.key) !== token) return;
          tab?.classList.remove("is-loading");
          pane.removeAttribute("aria-busy");
          if (iconEl) iconEl.innerHTML = icon(section.icon);
        });
    }

    function activate(section, { focus = false, reload = false } = {}) {
      active = section;
      container.querySelectorAll(".hub-tab").forEach((tab) => {
        const isActive = tab.getAttribute("data-section") === section.key;
        tab.setAttribute("aria-selected", String(isActive));
        tab.tabIndex = isActive ? 0 : -1;
        if (isActive && focus) tab.focus();
      });
      visible.forEach((s) => {
        paneOf(s).hidden = s.key !== section.key;
      });
      if (location.hash !== hashFor(section)) history.replaceState(null, "", hashFor(section));

      if (reload) invalidateListCache(...(section.lists || []));
      const pane = paneOf(section);
      if (!mounted.has(section.key)) {
        mounted.add(section.key);
        mountedPages.push(section.page);
        load(section, () => section.page.render(pane, user));
      } else if (reload) {
        load(section, () =>
          section.page.refresh ? section.page.refresh(pane, user) : section.page.render(pane, user)
        );
      }
    }

    container.querySelectorAll(".hub-tab").forEach((tab) => {
      tab.addEventListener("click", () =>
        activate(visible.find((s) => s.key === tab.getAttribute("data-section")), { reload: true })
      );
    });

    container.querySelector(".hub-tabs")?.addEventListener("keydown", (e) => {
      // Relative to the FOCUSED tab (the WAI-ARIA definition), falling back
      // to the selected one; "next" follows reading direction.
      const focusedKey = document.activeElement?.closest?.(".hub-tab")?.getAttribute("data-section");
      const focusedIdx = visible.findIndex((s) => s.key === focusedKey);
      const i = focusedIdx >= 0 ? focusedIdx : visible.indexOf(active);
      const rtl = document.documentElement.dir === "rtl";
      let next = null;
      if (e.key === (rtl ? "ArrowLeft" : "ArrowRight")) next = visible[(i + 1) % visible.length];
      else if (e.key === (rtl ? "ArrowRight" : "ArrowLeft")) next = visible[(i - 1 + visible.length) % visible.length];
      else if (e.key === "Home") next = visible[0];
      else if (e.key === "End") next = visible[visible.length - 1];
      if (!next) return;
      e.preventDefault();
      activate(next, { focus: true });
    });

    activate(active);
  }

  return { render, destroy, visibleSections };
}
