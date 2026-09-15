import { t, getLang } from '../i18n.js';
import {
  listCases,
  getCase,
  createCase,
  listCourts,
  listCaseLawyers,
  addCaseNote,
  updateCaseStage,
  watchCase,
  unwatchCase,
  getPermission,
  listCaseLinks,
  linkUserToCase,
  unlinkCaseUser,
  listLinkableClients,
} from '../api.js';
import {
  formatDate,
  openModal,
  closeModal,
  escapeHtml,
  toast,
  icon,
  routeFilter,
  parseServerDate,
  DISPLAY_TIMEZONE,
  requiredNote,
} from '../ui.js';
import { canRequestUpdate, openRequestUpdateDialog } from '../request-update.js';
import { printRecord, printButton } from '../print.js';

const STAGES = ['new', 'prep', 'pleading', 'judgment', 'execution', 'closed'];
let filters = { status: '', lawyer: '' };
let cachedCases = [];

/** "Is this hearing today?" judged in Kuwait, not in the viewer's timezone —
 *  otherwise a 10:00 UTC hearing (1:00 PM Kuwait) could be counted against the
 *  wrong calendar day for anyone travelling or on a differently-set laptop. */
function isToday(iso) {
  if (!iso) return false;
  const d = parseServerDate(iso);
  if (!d) return false;
  const inKuwait = (x) => x.toLocaleDateString('en-CA', { timeZone: DISPLAY_TIMEZONE });
  return inKuwait(d) === inKuwait(new Date());
}

function lawyerName(c) {
  return (getLang() === 'ar' ? c.assigned_lawyer_name_ar : c.assigned_lawyer_name_en) || null;
}

export function destroy() {}

export async function render(container, user) {
  const perm = getPermission('cases');

  const canCreate = perm === 'full' || perm === 'limited';

  // Arriving from a Dashboard stat card: pre-apply the filter that matches
  // the number that was clicked, so the list shown is the list counted.
  const incoming = routeFilter();
  const todayHearingsOnly = incoming === 'today-hearings';
  if (incoming === 'active') filters.status = 'active';

  container.innerHTML = `
    <div class="flex-between" style="margin-bottom:16px;">
      <h2 class="mt-0">${t('cases_title')}</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        ${printButton('cases-print')}
        ${canCreate ? `<button class="btn btn-primary" id="btn-new-case">${icon('plus')} ${t('new_case')}</button>` : ''}
      </div>
    </div>
    ${
      todayHearingsOnly
        ? `
    <div class="filter-chip-row">
      <span class="filter-chip">${icon('filter')} ${t('stat_today_hearings')}
        <button class="filter-chip-clear" id="clear-filter" title="${t('show_all')}" aria-label="${t('show_all')}">${icon('xmark')}</button>
      </span>
    </div>`
        : ''
    }
    <div class="filters-row">
      <div class="form-group">
        <label>${t('filter_status')}</label>
        <select id="filter-status">
          <option value="">${t('all')}</option>
          <option value="active">${getLang() === 'ar' ? 'نشطة' : 'Active'}</option>
          <option value="closed">${t('stage_closed')}</option>
        </select>
      </div>
      <div class="form-group">
        <label>${t('filter_lawyer')}</label>
        <select id="filter-lawyer">
          <option value="">${t('all')}</option>
        </select>
      </div>
    </div>
    <div id="cases-view"><p class="text-muted">${icon('spinner', 'fa-spin')}</p></div>
  `;

  const viewEl = container.querySelector('#cases-view');

  // Wired before the list loads so the button is never a dead control, even if
  // the request below fails; it prints whatever `filtered()` currently holds.
  container.querySelector('#cases-print').addEventListener('click', () => {
    const rows = filtered();
    if (rows.length === 0) {
      toast(t('print_nothing_to_print'), 'info');
      return;
    }
    const lang = getLang();
    const activeFilters = [
      todayHearingsOnly ? t('stat_today_hearings') : null,
      filters.status
        ? `${t('filter_status')}: ${filters.status === 'closed' ? t('stage_closed') : lang === 'ar' ? 'نشطة' : 'Active'}`
        : null,
      filters.lawyer ? `${t('filter_lawyer')}: ${lawyerName(rows[0]) || filters.lawyer}` : null,
    ].filter(Boolean);
    printRecord({
      title: t('print_case_list'),
      subtitle: t('cases_title'),
      meta: [
        { label: t('print_filters_applied'), value: activeFilters.join(' • ') || t('print_none') },
      ],
      sections: [
        {
          heading: t('nav_cases'),
          table: {
            columns: [
              t('case_number'),
              t('print_parties'),
              t('court_level'),
              t('filter_lawyer'),
              t('print_stage'),
              t('print_next_hearing'),
            ],
            rows: rows.map((c) => [
              `${c.case_number}/${c.case_year}`,
              lang === 'ar' ? c.parties_ar : c.parties_en,
              lang === 'ar' ? c.court_name_ar : c.court_name_en,
              lawyerName(c),
              t('stage_' + c.stage),
              c.next_hearing_at ? formatDate(c.next_hearing_at, { time: true }) : '—',
            ]),
          },
        },
      ],
    });
  });

  try {
    cachedCases = await listCases();
  } catch (err) {
    viewEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
    return;
  }

  // Belt and braces. app.js hands each render its own container element, so a
  // render that resumes after the user navigated on still finds its controls
  // (detached, but intact). This guard covers the remaining case where the
  // markup above simply failed to produce them.
  const lawyerSelect = container.querySelector('#filter-lawyer');
  const statusSelect = container.querySelector('#filter-status');
  if (!lawyerSelect || !statusSelect) return;

  const lawyers = [
    ...new Map(
      cachedCases
        .filter((c) => c.assigned_lawyer_id)
        .map((c) => [c.assigned_lawyer_id, lawyerName(c)]),
    ).entries(),
  ];
  lawyerSelect.innerHTML += lawyers
    .map(([id, name]) => `<option value="${id}">${name}</option>`)
    .join('');

  statusSelect.value = filters.status;
  lawyerSelect.value = filters.lawyer;
  statusSelect.addEventListener('change', (e) => {
    filters.status = e.target.value;
    renderView();
  });
  lawyerSelect.addEventListener('change', (e) => {
    filters.lawyer = e.target.value;
    renderView();
  });

  const newCaseBtn = container.querySelector('#btn-new-case');
  if (newCaseBtn) {
    newCaseBtn.addEventListener('click', () =>
      openNewCaseForm(async () => {
        cachedCases = await listCases();
        renderView();
      }),
    );
  }

  container.querySelector('#clear-filter')?.addEventListener('click', () => {
    location.hash = '#/cases';
  });

  function filtered() {
    return cachedCases.filter((c) => {
      if (todayHearingsOnly && !isToday(c.next_hearing_at)) return false;
      if (filters.status && c.status !== filters.status) return false;
      if (filters.lawyer && String(c.assigned_lawyer_id) !== filters.lawyer) return false;
      return true;
    });
  }

  function renderView() {
    renderTable(viewEl, filtered(), user);
  }

  renderView();
}

function renderTable(el, list, user) {
  const lang = getLang();
  if (list.length === 0) {
    el.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon('folder-open')}</div>${t('no_results')}</div>`;
    return;
  }
  el.innerHTML = `
    <div class="table-wrap panel">
      <table class="data-table">
        <thead>
          <tr><th>${t('case_number')}</th><th>${t('court_level')}</th><th>${t('filter_lawyer')}</th><th>${t('filter_status')}</th><th></th></tr>
        </thead>
        <tbody>
          ${list
            .map(
              (c) => `
            <tr data-case-id="${c.id}" style="cursor:pointer;">
              <td data-label="${t('case_number')}"><b>${c.case_number}/${c.case_year}</b><br><span class="text-muted">${lang === 'ar' ? c.parties_ar : c.parties_en}</span></td>
              <td data-label="${t('court_level')}">${lang === 'ar' ? c.court_name_ar : c.court_name_en}</td>
              <td data-label="${t('filter_lawyer')}">${lawyerName(c) || '—'}</td>
              <td data-label="${t('filter_status')}"><span class="badge ${c.status === 'closed' ? 'badge-muted' : 'badge-success'}">${c.status === 'closed' ? t('stage_closed') : lang === 'ar' ? 'نشطة' : 'Active'}</span></td>
              <td><button class="btn btn-outline btn-sm" data-open="${c.id}">${t('case_details')}</button></td>
            </tr>`,
            )
            .join('')}
        </tbody>
      </table>
    </div>`;
  el.querySelectorAll('[data-case-id], [data-open]').forEach((elm) => {
    elm.addEventListener('click', () => {
      const id = elm.getAttribute('data-case-id') || elm.getAttribute('data-open');
      openCaseDetail(Number(id), user);
    });
  });
}

export async function openCaseDetail(caseId, user) {
  const overlay = openModal(
    t('case_details'),
    `<p class="text-muted">${icon('spinner', 'fa-spin')}</p>`,
    { wide: true },
  );
  let c;
  try {
    c = await getCase(caseId);
  } catch (err) {
    overlay.querySelector('.modal-body').innerHTML =
      `<p class="text-muted">${escapeHtml(err.message)}</p>`;
    return;
  }

  const lang = getLang();
  const perm = getPermission('cases');
  const canEdit = perm === 'full' || perm === 'limited';
  // Timeline "Request Update" is Admin/Lawyer only, matching the server-side
  // require_roles("Admin", "Lawyer") on /api/search/request-update.
  const canAskUpdate = canRequestUpdate(user);
  // Linked Clients management mirrors the server's own _assert_can_link:
  // Admin for any case, or the Lawyer this specific case is assigned to.
  const canManageLinks =
    user.role_code === 'Admin' || (user.role_code === 'Lawyer' && user.id === c.assigned_lawyer_id);

  const body = `
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px;">
      <span class="badge badge-info">${c.case_number}/${c.case_year}</span>
      <span class="badge badge-muted">${lang === 'ar' ? c.court_name_ar : c.court_name_en}</span>
      <span class="badge badge-muted">${lawyerName(c) || '—'}</span>
      <span class="watch-toggle ${c.is_watching ? 'active' : ''}" id="watch-toggle">
        ${icon('bookmark', 'watch-icon')} <span id="watch-label">${c.is_watching ? t('watching') : t('watch_case')}</span>
      </span>
      <span style="margin-inline-start:auto;">${printButton('case-print')}</span>
    </div>
    <p>${escapeHtml((lang === 'ar' ? c.summary_ar : c.summary_en) || '—')}</p>

    <h4>${t('timeline')}</h4>
    <div class="timeline-list">
      ${c.timeline
        .map(
          (step, idx) => `
        <div class="timeline-item ${step.is_done ? 'done' : ''}">
          <div class="ti-title">
            ${escapeHtml((lang === 'ar' ? step.step_title_ar : step.step_title_en) || '—')}
            ${
              // Only the latest point gets the action: that is where progress
              // has stalled, and it is the only place a lawyer asking "where
              // are we?" makes sense. Asking for an update never advances the
              // timeline itself — it only creates a task for a person.
              idx === c.timeline.length - 1 && canAskUpdate
                ? `<button class="btn btn-outline btn-xs ti-action" id="timeline-request-update"
                     title="${t('request_update_hint_short')}">${icon('rotate')} ${t('request_update')}</button>`
                : ''
            }
          </div>
          <div class="ti-date">${formatDate(step.step_date)}</div>
        </div>`,
        )
        .join('')}
    </div>
    ${c.timeline.length === 0 ? `<p class="text-muted">${t('timeline_empty')}</p>` : ''}

    ${
      canManageLinks
        ? `
    <h4>${t('linked_clients')}</h4>
    <div id="linked-clients-list"><p class="text-muted">${icon('spinner', 'fa-spin')}</p></div>
    <div style="margin:10px 0;">
      <button class="btn btn-outline btn-sm" id="btn-link-client">${icon('link')} ${t('link_a_client')}</button>
    </div>
    <div id="link-client-form-host" style="margin-bottom:22px;"></div>`
        : ''
    }

    ${
      canEdit
        ? `
    <h4>${t('filter_status')}</h4>
    <div class="form-group" style="max-width:260px;">
      <select id="stage-select">
        ${STAGES.map((s) => `<option value="${s}" ${s === c.stage ? 'selected' : ''}>${t('stage_' + s)}</option>`).join('')}
      </select>
    </div>`
        : ''
    }

    <h4>${t('notes')}</h4>
    <div id="notes-list" style="margin-bottom:12px;">
      ${c.notes.length ? c.notes.map((n) => `<div class="hearing-row"><div><b>${escapeHtml(lang === 'ar' ? n.author_name_ar : n.author_name_en)}</b><div class="hearing-meta">${escapeHtml(n.note_text)}</div></div><div class="text-muted" style="font-size:11.5px;">${formatDate(n.created_at)}</div></div>`).join('') : `<p class="text-muted">—</p>`}
    </div>
    ${
      canEdit
        ? `
    <div style="display:flex;gap:8px;margin-bottom:22px;">
      <input id="note-input" placeholder="${t('add_note')}" style="flex:1;padding:11px 14px;border:1px solid var(--color-border);border-radius:6px;"/>
      <button class="btn btn-primary" id="add-note-btn">${icon('paper-plane')} ${t('add_note')}</button>
    </div>`
        : ''
    }

  `;

  overlay.querySelector('.modal-body').innerHTML = body;
  overlay.querySelector('.modal-header h3').textContent =
    `${t('case_details')} — ${c.case_number}/${c.case_year}`;

  if (canManageLinks) {
    wireLinkedClients(overlay, c);
  }

  // The case record on paper: identity, current position, the whole timeline
  // and every note — everything the modal shows, minus the controls that only
  // make sense on screen (stage dropdown, note box).
  overlay.querySelector('#case-print').addEventListener('click', () => {
    printRecord({
      title: `${t('print_case_record')} — ${c.case_number}/${c.case_year}`,
      subtitle: lang === 'ar' ? c.court_name_ar : c.court_name_en,
      meta: [
        { label: t('case_number'), value: `${c.case_number}/${c.case_year}` },
        { label: t('court'), value: lang === 'ar' ? c.court_name_ar : c.court_name_en },
        { label: t('filter_lawyer'), value: lawyerName(c) },
        { label: t('print_stage'), value: t('stage_' + c.stage) },
        {
          label: t('print_status'),
          value: c.status === 'closed' ? t('stage_closed') : lang === 'ar' ? 'نشطة' : 'Active',
        },
        { label: t('print_category'), value: lang === 'ar' ? c.category_ar : c.category_en },
        { label: t('civil_id'), value: c.civil_id },
        {
          label: t('print_next_hearing'),
          value: c.next_hearing_at ? formatDate(c.next_hearing_at, { time: true }) : '—',
        },
      ],
      sections: [
        {
          heading: t('print_parties'),
          text: lang === 'ar' ? c.parties_ar : c.parties_en || c.parties_ar,
        },
        { heading: t('print_summary'), text: (lang === 'ar' ? c.summary_ar : c.summary_en) || '—' },
        {
          heading: t('timeline'),
          table: {
            columns: [t('print_when'), t('timeline'), t('print_status')],
            rows: c.timeline.map((s) => [
              formatDate(s.step_date),
              (lang === 'ar' ? s.step_title_ar : s.step_title_en) || s.step_title_ar,
              s.is_done ? t('status_done') : t('status_open'),
            ]),
          },
        },
        {
          heading: t('notes'),
          items: c.notes.map((n) => ({
            title: `${lang === 'ar' ? n.author_name_ar : n.author_name_en} — ${formatDate(n.created_at, { time: true })}`,
            meta: n.note_text,
          })),
        },
      ],
    });
  });

  overlay.querySelector('#timeline-request-update')?.addEventListener('click', () => {
    openRequestUpdateDialog({
      sourceType: 'case',
      sourceRefId: c.id,
      contextLabel: `${c.case_number}/${c.case_year}`,
    });
  });

  const watchToggle = overlay.querySelector('#watch-toggle');
  watchToggle.addEventListener('click', async () => {
    try {
      if (c.is_watching) {
        await unwatchCase(caseId);
        c.is_watching = false;
      } else {
        await watchCase(caseId);
        c.is_watching = true;
      }
      watchToggle.classList.toggle('active', c.is_watching);
      watchToggle.querySelector('#watch-label').textContent = c.is_watching
        ? t('watching')
        : t('watch_case');
    } catch (err) {
      toast(err.message, 'error');
    }
  });

  const stageSelect = overlay.querySelector('#stage-select');
  if (stageSelect) {
    stageSelect.addEventListener('change', async () => {
      try {
        await updateCaseStage(c.id, stageSelect.value);
        toast(getLang() === 'ar' ? 'تم تحديث حالة القضية' : 'Case status updated', 'success');
      } catch (err) {
        toast(err.message, 'error');
      }
    });
  }

  const addBtn = overlay.querySelector('#add-note-btn');
  if (addBtn) {
    addBtn.addEventListener('click', async () => {
      const input = overlay.querySelector('#note-input');
      const text = input.value.trim();
      if (!text) {
        toast(t('note_required'), 'error');
        input.focus();
        return;
      }
      try {
        await addCaseNote(c.id, text);
        closeModal();
        openCaseDetail(caseId, user);
      } catch (err) {
        toast(err.message, 'error');
      }
    });
  }

}

/**
 * "Linked Clients" block inside the Case Details modal — Admin/owning-Lawyer
 * only (gated by the caller). Lists everyone explicitly linked to this case
 * (independent of the civil_id match, which keeps working unchanged and
 * isn't shown here since it isn't something to unlink) and lets the manager
 * link another client or revoke an existing link, refreshing just this
 * block rather than the whole modal.
 */
function wireLinkedClients(overlay, c) {
  const listEl = overlay.querySelector('#linked-clients-list');
  const addBtn = overlay.querySelector('#btn-link-client');
  const formHost = overlay.querySelector('#link-client-form-host');
  if (!listEl || !addBtn) return;

  async function refreshLinks() {
    listEl.innerHTML = `<p class="text-muted">${icon('spinner', 'fa-spin')}</p>`;
    let links = [];
    try {
      links = await listCaseLinks(c.id);
    } catch (err) {
      listEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      return;
    }
    if (links.length === 0) {
      listEl.innerHTML = `<p class="text-muted">${t('no_linked_clients')}</p>`;
      return;
    }
    const lang = getLang();
    listEl.innerHTML = links
      .map(
        (l) => `
      <div class="hearing-row">
        <div>
          <b>${escapeHtml(lang === 'ar' ? l.user_name_ar : l.user_name_en)}</b>
          ${l.can_upload ? `<span class="badge badge-success">${t('allow_upload')}</span>` : ''}
          <div class="hearing-meta">${t('linked_by_label')}: ${escapeHtml((lang === 'ar' ? l.linked_by_name_ar : l.linked_by_name_en) || '—')} — ${formatDate(l.linked_at)}</div>
        </div>
        <button class="btn btn-outline btn-sm" data-unlink="${l.id}">${icon('link-slash')} ${t('unlink')}</button>
      </div>`,
      )
      .join('');
    listEl.querySelectorAll('[data-unlink]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        btn.disabled = true;
        try {
          await unlinkCaseUser(c.id, Number(btn.getAttribute('data-unlink')));
          toast(t('unlink_success'), 'success');
          await refreshLinks();
        } catch (err) {
          toast(err.message, 'error');
          btn.disabled = false;
        }
      });
    });
  }

  addBtn.addEventListener('click', async () => {
    if (formHost && formHost.innerHTML) {
      formHost.innerHTML = '';
      return;
    }
    let clients = [];
    try {
      clients = await listLinkableClients();
    } catch (err) {
      toast(err.message, 'error');
      return;
    }
    const lang = getLang();
    formHost.innerHTML = `
      <div class="search-form-grid" style="margin-top:10px;">
        <div class="form-group">
          <label>${t('select_client')}</label>
          <select id="link-client-select">
            ${clients.map((u) => `<option value="${u.id}">${escapeHtml(lang === 'ar' ? u.name_ar : u.name_en)}</option>`).join('')}
          </select>
        </div>
        <div class="form-group" style="display:flex;align-items:center;gap:8px;">
          <input type="checkbox" id="link-can-upload" style="width:auto;"/>
          <label for="link-can-upload" style="margin:0;">${t('allow_upload')}</label>
        </div>
      </div>
      <button class="btn btn-primary btn-sm" id="link-client-submit">${icon('link')} ${t('link_a_client')}</button>
    `;
    formHost.querySelector('#link-client-submit').addEventListener('click', async () => {
      const select = formHost.querySelector('#link-client-select');
      if (!select || !select.value) return;
      try {
        await linkUserToCase(c.id, Number(select.value), formHost.querySelector('#link-can-upload').checked);
        toast(t('link_created_success'), 'success');
        formHost.innerHTML = '';
        await refreshLinks();
      } catch (err) {
        toast(err.message, 'error');
      }
    });
  });

  refreshLinks();
}

async function openNewCaseForm(onCreated) {
  const lang = getLang();
  const overlay = openModal(
    t('new_case'),
    `<p class="text-muted">${icon('spinner', 'fa-spin')}</p>`,
    { wide: true },
  );

  let courts = [];
  let lawyers = [];
  try {
    [courts, lawyers] = await Promise.all([listCourts(), listCaseLawyers()]);
  } catch (err) {
    overlay.querySelector('.modal-body').innerHTML =
      `<p class="text-muted">${escapeHtml(err.message)}</p>`;
    return;
  }

  overlay.querySelector('.modal-body').innerHTML = `
    <div class="search-form-grid">
      <div class="form-group"><label class="required">${t('case_number')}</label><input id="f-case-number" aria-required="true"/></div>
      <div class="form-group"><label class="required">${t('case_year')}</label><input type="number" id="f-case-year" aria-required="true" value="${new Date().getFullYear()}"/></div>
      <div class="form-group">
        <label class="required">${t('court')}</label>
        <select id="f-court" aria-required="true">
          <option value="">${t('select_court')}</option>
          ${courts.map((c) => `<option value="${c.id}">${lang === 'ar' ? c.name_ar : c.name_en}</option>`).join('')}
        </select>
      </div>
      <div class="form-group"><label>${t('category_ar')}</label><input id="f-category-ar"/></div>
      <div class="form-group"><label>${t('category_en')}</label><input id="f-category-en"/></div>
      <div class="form-group"><label>${t('civil_id')}</label><input id="f-civil-id"/></div>
      <div class="form-group"><label class="required">${t('parties_ar')}</label><input id="f-parties-ar" aria-required="true"/></div>
      <div class="form-group"><label>${t('parties_en')}</label><input id="f-parties-en"/></div>
      <div class="form-group">
        <label>${t('assigned_lawyer_optional')}</label>
        <select id="f-lawyer">
          <option value="">${t('none_option')}</option>
          ${lawyers.map((u) => `<option value="${u.id}">${lang === 'ar' ? u.name_ar : u.name_en}</option>`).join('')}
        </select>
      </div>
      <div class="form-group">
        <label>${t('initial_stage')}</label>
        <select id="f-stage">
          ${STAGES.map((s) => `<option value="${s}">${t('stage_' + s)}</option>`).join('')}
        </select>
      </div>
      <div class="form-group"><label>${t('next_hearing_date')}</label><input type="datetime-local" id="f-next-hearing"/></div>
    </div>
    <div class="form-group">
      <label>${t('summary_ar')}</label>
      <textarea id="f-summary-ar" rows="2" style="width:100%;padding:11px 14px;border:1px solid var(--color-border);border-radius:6px;"></textarea>
    </div>
    <div class="form-group">
      <label>${t('summary_en')}</label>
      <textarea id="f-summary-en" rows="2" style="width:100%;padding:11px 14px;border:1px solid var(--color-border);border-radius:6px;"></textarea>
    </div>
    ${requiredNote()}
    <button class="btn btn-primary btn-block" id="case-form-submit">${icon('floppy-disk')} ${t('save')}</button>
  `;

  overlay.querySelector('#case-form-submit').addEventListener('click', async () => {
    const caseNumber = overlay.querySelector('#f-case-number').value.trim();
    const caseYear = Number(overlay.querySelector('#f-case-year').value);
    const courtId = overlay.querySelector('#f-court').value;
    const partiesAr = overlay.querySelector('#f-parties-ar').value.trim();
    if (!caseNumber || !caseYear || !courtId || !partiesAr) {
      toast(t('required'), 'error');
      return;
    }
    const nextHearing = overlay.querySelector('#f-next-hearing').value;
    const lawyerId = overlay.querySelector('#f-lawyer').value;
    try {
      await createCase({
        case_number: caseNumber,
        case_year: caseYear,
        court_id: Number(courtId),
        category_ar: overlay.querySelector('#f-category-ar').value.trim() || null,
        category_en: overlay.querySelector('#f-category-en').value.trim() || null,
        parties_ar: partiesAr,
        parties_en: overlay.querySelector('#f-parties-en').value.trim() || null,
        civil_id: overlay.querySelector('#f-civil-id').value.trim() || null,
        assigned_lawyer_id: lawyerId ? Number(lawyerId) : null,
        summary_ar: overlay.querySelector('#f-summary-ar').value.trim() || null,
        summary_en: overlay.querySelector('#f-summary-en').value.trim() || null,
        stage: overlay.querySelector('#f-stage').value,
        next_hearing_at: nextHearing ? new Date(nextHearing).toISOString() : null,
      });
      toast(t('case_created_success'), 'success');
      closeModal();
      await onCreated();
    } catch (err) {
      toast(
        err.message.includes('already exists') ? t('case_number_year_conflict') : err.message,
        'error',
      );
    }
  });
}
