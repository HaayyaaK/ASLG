/**
 * The Notifications page (Merge B, Sept 2026 overhaul): "Notifications"
 * (notifications.js) and "Reminders & Follow-ups" (reminders.js) as
 * contained tabs. All behavior -- permission gate, URL handling, lazy
 * mounting, tab-click refresh, keyboard -- lives in js/hub.js, shared with
 * the Cases hub so the two pages behave identically.
 *
 * A Client's `reminders` permission is "none": they get the Notifications
 * tab alone, no tab bar, and reminders.js is never mounted, so no reminder
 * request is ever sent for that role. /api/reminders refuses them
 * server-side regardless.
 */
import { createHub } from "../hub.js";
import * as notificationsPage from "./notifications.js";
import * as remindersPage from "./reminders.js";

const hub = createHub({
  base: "notifications",
  tabsLabelKey: "notifications_hub_tabs_label",
  sections: [
    { key: "notifications", segment: null, label: "nav_notifications", icon: "bell", page: notificationsPage, perm: "notifications", lists: ["notifications"] },
    { key: "reminders", segment: "reminders", label: "nav_reminders", icon: "clock-rotate-left", page: remindersPage, perm: "reminders", lists: ["reminders"] },
  ],
});

export const { render, destroy, visibleSections } = hub;
