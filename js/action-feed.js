/**
 * Action Stream — merges notifications and open tasks into one
 * reverse-chronological, urgency-first feed for the Dashboard (Sub-phase
 * 3.4). This is the same merge Sub-phase 3.6 will reuse to replace the
 * separate Notifications and Reminders & Follow-ups pages with a single
 * Unified Action Feed, so the row shape and sort here are the one both will
 * share -- not a dashboard-only convenience that gets thrown away later.
 *
 * Row shape (locked, see the sub-phase 3.4 plan):
 *   {
 *     type: 'alert' | 'system' | 'task',
 *     sortAt: Date,
 *     urgencyBucket: 0 | 1 | 2,   // 0 = overdue task, 1 = task due soon, 2 = everything else
 *     source: {
 *       id, title, caseRef: {id, case_number, case_year} | null,
 *       status: 'open'|'done'|'dismissed' | null,   // task rows only
 *       isRead: boolean | null,                       // alert/system rows only
 *     }
 *   }
 * Sorted: urgencyBucket asc, then sortAt asc within 0/1 (soonest-due first),
 * desc within 2 (most-recent-first, like a normal activity feed).
 */
import { getLang } from "./i18n.js";
import { parseServerDate, isSmartNudge } from "./ui.js";

// A task due within this window is flagged "due soon" (bucket 1) rather than
// folded into the general feed (bucket 2) -- matches the "3 days" mid-layer
// of the app's own three-warning escalation schedule (see GUIDELINES.md
// 3.1), so this widget's sense of "soon" agrees with the alerts the user is
// already receiving about the same task.
export const DUE_SOON_MS = 3 * 24 * 3600 * 1000;

/**
 * @param {object[]} notifications  raw NotificationOut rows (already scoped
 *   server-side to the signed-in user -- see GET /api/notifications)
 * @param {object[]} reminders  raw ReminderOut rows (listReminders() returns
 *   every reminder the caller created OR was assigned; this function keeps
 *   only ones ASSIGNED TO the given user -- "what do I owe", matching what
 *   an action stream on my own dashboard should show)
 * @param {{id:number}} user
 * @returns {object[]} rows in the shape documented above, pre-sorted
 */
export function mergeActionFeed(notifications, reminders, user) {
  const now = Date.now();
  const lang = getLang();
  const rows = [];

  (notifications || []).forEach((n) => {
    rows.push({
      type: isSmartNudge(n) || n.type === "system" ? "system" : "alert",
      sortAt: parseServerDate(n.created_at) || new Date(0),
      urgencyBucket: 2,
      source: {
        id: n.id,
        title: (lang === "ar" ? n.message_ar : n.message_en) || n.message_ar,
        caseRef: null,
        status: null,
        isRead: !!n.is_read,
        kind: "notification",
        notifType: n.type,
      },
    });
  });

  (reminders || []).forEach((r) => {
    if (!user || r.assigned_to !== user.id) return;
    const dueAt = parseServerDate(r.due_at);
    const dueMs = dueAt ? dueAt.getTime() : Infinity;
    const isOpen = r.status === "open";
    const overdue = isOpen && dueMs < now;
    const dueSoon = isOpen && !overdue && dueMs - now <= DUE_SOON_MS;
    const resolvedAt = parseServerDate(r.resolved_at);
    rows.push({
      type: "task",
      sortAt: isOpen ? dueAt || new Date(0) : resolvedAt || parseServerDate(r.created_at) || new Date(0),
      urgencyBucket: overdue ? 0 : dueSoon ? 1 : 2,
      source: {
        id: r.id,
        title: r.note,
        caseRef: { id: r.case_id, case_number: r.case_number, case_year: r.case_year ?? null },
        status: r.status,
        isRead: null,
        kind: "reminder",
        reminderType: r.type,
        requestedStage: r.requested_stage,
        dueAt: r.due_at,
      },
    });
  });

  rows.sort((a, b) => {
    if (a.urgencyBucket !== b.urgencyBucket) return a.urgencyBucket - b.urgencyBucket;
    const diff = a.sortAt.getTime() - b.sortAt.getTime();
    return a.urgencyBucket === 2 ? -diff : diff;
  });

  return rows;
}
