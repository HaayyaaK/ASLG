/**
 * Command Palette (Ctrl+K / Cmd+K) — Sub-phase 3.4, Gap B feature 2.
 *
 * A generic overlay + fuzzy-filtered list + keyboard navigation component,
 * deliberately with no business logic of its own: the caller supplies the
 * list of items (label, hint, group, icon, a lowercased searchText, and a
 * `run()` callback). This mirrors the rest of the app's separation between
 * generic UI building blocks (ui.js) and page-owned data/actions.
 *
 * Scope note: this is wired from js/pages/dashboard.js only (this sub-phase's
 * approved file list does not include js/app.js), so Ctrl+K currently opens
 * the palette while the Dashboard is the active page. Promoting it to a
 * global shortcut is a one-line addition in app.js's boot() for a future
 * sub-phase, once that file is back in scope.
 */
import { t } from "./i18n.js";
import { icon, escapeHtml } from "./ui.js";

let overlay = null;
let keydownHandler = null;

export function initCommandPalette(getItems) {
  destroyCommandPalette();
  keydownHandler = (e) => {
    const isK = e.key === "k" || e.key === "K";
    if ((e.ctrlKey || e.metaKey) && isK) {
      e.preventDefault();
      if (overlay) close();
      else openCommandPalette(getItems());
    } else if (e.key === "Escape" && overlay) {
      close();
    }
  };
  document.addEventListener("keydown", keydownHandler);
}

export function destroyCommandPalette() {
  if (keydownHandler) document.removeEventListener("keydown", keydownHandler);
  keydownHandler = null;
  close();
}

/** Programmatic entry point for a visible trigger (e.g. a toolbar button) —
 *  touch-only devices have no Ctrl+K, so the keyboard shortcut cannot be the
 *  only way in. */
export function openCommandPalette(allItems) {
  if (overlay) close();
  open(allItems);
}

function open(allItems) {
  const previouslyFocused = document.activeElement;
  overlay = document.createElement("div");
  overlay.className = "cmdk-overlay";
  overlay.innerHTML = `
    <div class="cmdk-box" role="dialog" aria-modal="true" aria-label="${escapeHtml(t("cmdk_title"))}">
      <div class="cmdk-input-row">
        ${icon("magnifying-glass", "cmdk-search-icon")}
        <input type="text" class="cmdk-input" id="cmdk-input" placeholder="${escapeHtml(t("cmdk_placeholder"))}"
          autocomplete="off" aria-label="${escapeHtml(t("cmdk_title"))}" role="combobox" aria-expanded="true"
          aria-controls="cmdk-list" aria-autocomplete="list"/>
        <kbd class="cmdk-esc">Esc</kbd>
      </div>
      <div class="cmdk-list" id="cmdk-list" role="listbox" aria-label="${escapeHtml(t("cmdk_title"))}"></div>
    </div>`;
  document.body.appendChild(overlay);
  requestAnimationFrame(() => overlay.classList.add("open"));
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });
  overlay._restoreFocus = previouslyFocused;

  const input = overlay.querySelector("#cmdk-input");
  const listEl = overlay.querySelector("#cmdk-list");
  let activeIndex = 0;
  let filtered = allItems;

  function renderList() {
    if (filtered.length === 0) {
      listEl.innerHTML = `<p class="cmdk-empty">${escapeHtml(t("cmdk_no_results"))}</p>`;
      input.removeAttribute("aria-activedescendant");
      return;
    }
    listEl.innerHTML = filtered
      .map(
        (it, i) => `
      <button type="button" id="cmdk-opt-${i}" class="cmdk-item ${i === activeIndex ? "active" : ""}"
        data-idx="${i}" role="option" aria-selected="${i === activeIndex}">
        <span class="cmdk-item-icon">${icon(it.icon || "arrow-right")}</span>
        <span class="cmdk-item-body">
          <span class="cmdk-item-label">${escapeHtml(it.label)}</span>
          ${it.hint ? `<span class="cmdk-item-hint">${escapeHtml(it.hint)}</span>` : ""}
        </span>
        ${it.group ? `<span class="cmdk-item-group">${escapeHtml(it.group)}</span>` : ""}
      </button>`
      )
      .join("");
    listEl.querySelectorAll("[data-idx]").forEach((btn) => {
      btn.addEventListener("click", () => runItem(filtered[Number(btn.getAttribute("data-idx"))]));
    });
    input.setAttribute("aria-activedescendant", `cmdk-opt-${activeIndex}`);
  }

  function runItem(it) {
    close();
    it.run();
  }

  function scrollActiveIntoView() {
    listEl.querySelector(".cmdk-item.active")?.scrollIntoView({ block: "nearest" });
  }

  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();
    filtered = q ? allItems.filter((it) => it.searchText.includes(q)) : allItems;
    activeIndex = 0;
    renderList();
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (filtered.length) {
        activeIndex = Math.min(activeIndex + 1, filtered.length - 1);
        renderList();
        scrollActiveIntoView();
      }
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (filtered.length) {
        activeIndex = Math.max(activeIndex - 1, 0);
        renderList();
        scrollActiveIntoView();
      }
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filtered[activeIndex]) runItem(filtered[activeIndex]);
    }
  });

  renderList();
  requestAnimationFrame(() => input.focus());
}

function close() {
  if (!overlay) return;
  const restore = overlay._restoreFocus;
  overlay.remove();
  overlay = null;
  // Keyboard users invoked this from somewhere -- give focus back rather
  // than dropping it to <body> when the palette closes.
  if (restore && typeof restore.focus === "function") restore.focus();
}
