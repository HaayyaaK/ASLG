import { t, getLang } from '../i18n.js';
import { listNotificationsCached, markNotificationRead, markAllNotificationsRead } from '../api.js';
import { formatDate, icon, toast, escapeHtml, isSmartNudge, makeKeyboardActivatable } from '../ui.js';
import { printRecord, printButton } from '../print.js';

export function destroy() {}

export async function render(container, user) {
  container.innerHTML = `
    <div class="flex-between" style="margin-bottom:16px;">
      <h2 class="mt-0">${t('notifications_title')}</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        ${printButton('notif-print')}
        <button class="btn btn-accent btn-sm" id="mark-all">${icon('check-double')} ${t('mark_all_read')}</button>
      </div>
    </div>
    <div class="panel"><div class="panel-body" id="notif-list"><p class="text-muted">${icon('spinner', 'fa-spin')}</p></div></div>
  `;

  // Only ever this user's own notifications — the list below is exactly what
  // /api/notifications scoped to them, so the printout cannot widen it.
  let visibleNotifs = [];

  // Wired before the first `await`, so the button is live as soon as it is
  // visible; it closes over `visibleNotifs`.
  container.querySelector('#notif-print').addEventListener('click', () => {
    if (visibleNotifs.length === 0) {
      toast(t('print_nothing_to_print'), 'info');
      return;
    }
    const lang = getLang();
    printRecord({
      title: t('print_notifications_title'),
      subtitle: lang === 'ar' ? user.name_ar : user.name_en,
      sections: [
        {
          heading: t('notifications_title'),
          table: {
            columns: [t('print_when'), t('print_message'), t('print_type'), t('print_read_state')],
            rows: visibleNotifs.map((n) => [
              formatDate(n.created_at, { time: true }),
              lang === 'ar' ? n.message_ar : n.message_en,
              isSmartNudge(n) ? t('smart_followup') : n.type,
              n.is_read ? t('print_read') : t('print_unread'),
            ]),
          },
        },
      ],
    });
  });

  async function refresh() {
    const listEl = container.querySelector('#notif-list');
    let notifs;
    try {
      // Cached (60s) for tab switches; mark-read / mark-all invalidate it,
      // so the refresh() after either always sees the change.
      notifs = await listNotificationsCached();
    } catch (err) {
      listEl.innerHTML = `<p class="text-muted">${err.message}</p>`;
      return;
    }
    visibleNotifs = notifs;
    if (notifs.length === 0) {
      listEl.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon('bell')}</div>${t('no_notifications')}</div>`;
      return;
    }
    listEl.innerHTML = notifs
      .map((n) => {
        // type="system" is what the automatic follow-up engine sends. It is
        // marked out clearly so nobody mistakes an automatic nudge for a
        // colleague personally chasing them — and so a lawyer reading their
        // copy understands the system sent it, not them.
        const isSmart = isSmartNudge(n);
        return `
      <div class="hearing-row notif-row ${isSmart ? 'notif-smart' : ''}" data-notif-id="${n.id}"${n.is_read ? '' : ' data-unread'} style="cursor:pointer;${n.is_read ? '' : 'background:var(--color-info-bg);border-radius:8px;padding-inline:12px;'}">
        <div class="hearing-info">
          ${isSmart ? `<div class="smart-tag">${icon('robot')} ${t('smart_followup')}</div>` : ''}
          <div style="font-weight:${n.is_read ? '500' : '700'};">${escapeHtml(getLang() === 'ar' ? n.message_ar : n.message_en)}</div>
          <div class="hearing-meta">${formatDate(n.created_at, { time: true })}</div>
        </div>
        ${n.is_read ? '' : `<span class="badge badge-info">${getLang() === 'ar' ? 'جديد' : 'New'}</span>`}
      </div>`;
      })
      .join('');

    listEl.querySelectorAll('[data-notif-id]').forEach((row) => {
      // Unread rows are the actionable ones (click = mark read): make them
      // reachable and operable by keyboard too, not only by mouse.
      if (row.hasAttribute('data-unread')) {
        makeKeyboardActivatable(row);
        row.title = t('notif_mark_read_hint');
      }
      row.addEventListener('click', async () => {
        try {
          await markNotificationRead(Number(row.getAttribute('data-notif-id')));
          refresh();
        } catch (err) {
          toast(err.message, 'error');
        }
      });
    });
  }

  await refresh();

  // Optional call: defence in depth alongside the per-render container in
  // app.js, so a late resume can never dereference null.
  container.querySelector('#mark-all')?.addEventListener('click', async () => {
    try {
      await markAllNotificationsRead();
      refresh();
    } catch (err) {
      toast(err.message, 'error');
    }
  });
}
