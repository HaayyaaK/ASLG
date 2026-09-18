/**
 * Recently-Viewed Cases — a per-device, per-user convenience rail (Sub-phase
 * 3.4, Sept 2026 overhaul, Gap B feature 1).
 *
 * Deliberately client-only: this is "what did I just look at", not a
 * business record, so it lives in localStorage rather than the database —
 * no endpoint, no migration, and it naturally forgets itself if the user
 * clears site data. Namespaced per signed-in user id so two people sharing
 * a staff workstation never see each other's recently-opened cases.
 *
 * The single write point is `js/pages/cases.js::openCaseDetail` — the one
 * function every "open a case" action in the app already funnels through
 * (dashboard tiles, hearing rows, case list rows, search results). Recording
 * there means every real case view is captured for free, with no per-caller
 * wiring anywhere else.
 */
import { getCurrentUser } from "./api.js";

const MAX_ENTRIES = 8;

function storageKey() {
  const user = getCurrentUser();
  return `aslg_recently_viewed_${user?.id ?? "anon"}`;
}

function readList() {
  try {
    const raw = localStorage.getItem(storageKey());
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    // Private browsing / storage disabled / corrupt JSON -- this rail is a
    // convenience, never something the rest of the app depends on.
    return [];
  }
}

/** @param {{id:number, case_number:string, case_year:number, parties_ar?:string, parties_en?:string}} caseSummary */
export function recordRecentlyViewed(caseSummary) {
  if (!caseSummary?.id) return;
  try {
    const list = readList().filter((c) => c.id !== caseSummary.id);
    list.unshift({
      id: caseSummary.id,
      case_number: caseSummary.case_number,
      case_year: caseSummary.case_year,
      parties_ar: caseSummary.parties_ar || "",
      parties_en: caseSummary.parties_en || "",
      viewedAt: Date.now(),
    });
    localStorage.setItem(storageKey(), JSON.stringify(list.slice(0, MAX_ENTRIES)));
  } catch {
    // Quota exceeded or storage disabled -- silently skip.
  }
}

export function listRecentlyViewed() {
  return readList();
}
