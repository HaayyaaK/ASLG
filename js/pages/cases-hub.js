/**
 * The Cases page (Merge A, Sept 2026 overhaul): "My Cases" (cases.js) and
 * "Official Search Engine" (search.js) as contained tabs. All behavior --
 * permission gate, URL handling, lazy mounting, tab-click refresh, keyboard
 * -- lives in js/hub.js, shared with the Notifications hub.
 *
 * Its own module rather than part of cases.js because search.js already
 * imports openCaseDetail from cases.js; cases.js importing search.js back
 * would be circular.
 */
import { createHub } from "../hub.js";
import * as casesPage from "./cases.js";
import * as searchPage from "./search.js";

const hub = createHub({
  base: "cases",
  tabsLabelKey: "cases_hub_tabs_label",
  sections: [
    { key: "mine", segment: null, label: "cases_tab_mine", icon: "folder-open", page: casesPage, perm: "cases", lists: ["cases"] },
    // "cases" too: this tab's Official Sync case picker reads the case list.
    { key: "search", segment: "search", label: "nav_search", icon: "magnifying-glass", page: searchPage, perm: "search", lists: ["cases"] },
  ],
});

export const { render, destroy, visibleSections } = hub;
