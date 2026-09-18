import { t, getLang } from '../i18n.js';
import {
  listUsers,
  createUser,
  updateUser,
  deleteUser,
  resetUserPassword,
  bulkUserAction,
  resetDatabase,
  downloadBackup,
  restoreDatabase,
  clearSession,
} from '../api.js';
import { toast, icon, openModal, closeModal, escapeHtml, roleAvatar, requiredNote } from '../ui.js';

const ROLES = ['Admin', 'Lawyer', 'consultant', 'delegate', 'User'];
const MODULE_KEYS = [
  'dashboard',
  'search',
  'cases',
  'documents',
  'notifications',
  'users',
  'reminders',
];

const PERMISSION_MATRIX = {
  Admin: {
    dashboard: 'full',
    search: 'full',
    cases: 'full',
    documents: 'full',
    notifications: 'full',
    users: 'full',
    reminders: 'full',
  },
  Lawyer: {
    dashboard: 'full',
    search: 'full',
    cases: 'full',
    documents: 'full',
    notifications: 'full',
    users: 'none',
    reminders: 'full',
  },
  consultant: {
    dashboard: 'full',
    search: 'edit',
    cases: 'limited',
    documents: 'edit',
    notifications: 'full',
    users: 'none',
    reminders: 'edit',
  },
  delegate: {
    dashboard: 'full',
    search: 'edit',
    cases: 'view',
    documents: 'edit',
    notifications: 'full',
    users: 'none',
    reminders: 'view',
  },
  User: {
    dashboard: 'limited',
    search: 'none',
    cases: 'own',
    documents: 'own',
    notifications: 'full',
    users: 'none',
    reminders: 'none',
  },
};

let selected = new Set();
let cachedUsers = [];

export function destroy() {
  selected = new Set();
}

export async function render(container, user) {
  const lang = getLang();

  container.innerHTML = `
    <div class="flex-between" style="margin-bottom:16px;">
      <h2 class="mt-0">${t('users_title')}</h2>
      <button class="btn btn-primary btn-sm" id="btn-new-user">${icon('user-plus')} ${t('create_user')}</button>
    </div>
    <div class="bulk-toolbar" id="bulk-toolbar">
      <span><span class="count" id="bulk-count">0</span> ${t('selected')}</span>
      <button class="btn btn-outline btn-sm" id="bulk-activate">${icon('toggle-on')} ${t('bulk_activate')}</button>
      <button class="btn btn-outline btn-sm" id="bulk-deactivate">${icon('toggle-off')} ${t('bulk_deactivate')}</button>
      <button class="btn btn-outline btn-sm" id="bulk-reset">${icon('key')} ${t('bulk_reset_password')}</button>
    </div>
    <div class="panel" style="margin-bottom:20px;">
      <div class="panel-body table-wrap" id="users-table"><p class="text-muted">${icon('spinner', 'fa-spin')}</p></div>
    </div>
    <div class="panel">
      <div class="panel-header"><h3>${t('permissions')}</h3></div>
      <div class="panel-body table-wrap">
        <table>
          <thead><tr><th>${t('role')}</th><th>${t('nav_dashboard')}</th><th>${t('nav_search')}</th><th>${t('nav_cases')}</th><th>${t('nav_documents')}</th><th>${t('nav_notifications')}</th><th>${t('nav_users')}</th><th>${t('nav_reminders')}</th></tr></thead>
          <tbody>
            ${Object.entries(PERMISSION_MATRIX)
              .map(
                ([role, perms]) => `<tr>
                <td><b>${t('role_' + role)}</b></td>
                ${MODULE_KEYS.map((m) => `<td>${permBadge(perms[m])}</td>`).join('')}
              </tr>`,
              )
              .join('')}
          </tbody>
        </table>
      </div>
    </div>
    ${
      user.role_code === 'Admin'
        ? `
    <div class="panel" style="margin-top:20px;">
      <div class="panel-header"><h3>${t('system_maintenance')}</h3></div>
      <div class="panel-body">
        <div class="hearing-row">
          <div class="hearing-info">
            <b>${t('reset_client_title')}</b>
            <div class="hearing-meta">${t('reset_client_desc')}</div>
          </div>
          <button class="btn btn-outline btn-sm" id="btn-reset-client">${icon('broom')} ${t('reset_client_title')}</button>
        </div>
        <div class="hearing-row">
          <div class="hearing-info">
            <b>${t('full_backup_title')}</b>
            <div class="hearing-meta">${t('full_backup_desc')}</div>
          </div>
          <button class="btn btn-outline btn-sm" id="btn-full-backup">${icon('download')} ${t('full_backup_title')}</button>
        </div>
        <div class="hearing-row" style="border-inline-start: 3px solid var(--color-danger);padding-inline-start: 0.5rem;">
          <div class="hearing-info">
            <b style="color:var(--color-danger);">${t('import_restore_title')}</b>
            <div class="hearing-meta">${t('import_restore_desc')}</div>
          </div>
          <button class="btn btn-danger btn-sm" id="btn-import-restore">${icon('upload')} ${t('import_restore_title')}</button>
        </div>
        <div class="hearing-row" style="border-inline-start: 3px solid var(--color-danger);padding-inline-start: 0.5rem;">
          <div class="hearing-info">
            <b style="color:var(--color-danger);">${t('factory_reset_title')}</b>
            <div class="hearing-meta">${t('factory_reset_desc')}</div>
          </div>
          <button class="btn btn-danger btn-sm" id="btn-factory-reset">${icon('triangle-exclamation')} ${t('factory_reset_title')}</button>
        </div>
      </div>
    </div>`
        : ''
    }
  `;

  selected = new Set();

  async function refreshUsers() {
    const tableEl = container.querySelector('#users-table');
    try {
      cachedUsers = await listUsers();
    } catch (err) {
      tableEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      return;
    }
    const userColLabel = lang === 'ar' ? 'المستخدم' : 'User';
    const statusColLabel = lang === 'ar' ? 'الحالة' : 'Status';
    tableEl.innerHTML = `
      <table class="data-table">
        <thead><tr>
          <th><input type="checkbox" class="select-all-checkbox" id="select-all" aria-label="${t('select_all')}"/></th>
          <th>${userColLabel}</th>
          <th>${t('role')}</th>
          <th>${statusColLabel}</th>
          <th></th>
        </tr></thead>
        <tbody>
          ${cachedUsers
            .map(
              (u) => `
            <tr>
              <td>${u.id === user.id ? '' : `<input type="checkbox" class="row-checkbox" name="selected-user" value="${u.id}" data-id="${u.id}" ${selected.has(u.id) ? 'checked' : ''} aria-label="${userColLabel}: ${escapeHtml(lang === 'ar' ? u.name_ar : u.name_en)}"/>`}</td>
              <td data-label="${userColLabel}" style="display:flex;align-items:center;gap:10px;">
                ${roleAvatar(u, 'width:32px;height:32px;font-size:11px;')}
                <div><b>${lang === 'ar' ? u.name_ar : u.name_en}</b><br><span class="text-muted" style="font-size:11.5px;">${u.username}</span></div>
              </td>
              <td data-label="${t('role')}"><span class="badge badge-info">${t('role_' + u.role_code)}</span> ${u.is_owner ? `<span class="badge badge-warning">${t('owner_badge')}</span>` : ''}</td>
              <td data-label="${statusColLabel}">${u.is_active ? `<span class="badge badge-success">${lang === 'ar' ? 'فعّال' : 'Active'}</span>` : `<span class="badge badge-muted">${lang === 'ar' ? 'معطّل' : 'Disabled'}</span>`}</td>
              <td style="white-space:nowrap;">
                <button class="btn btn-outline btn-sm" data-edit="${u.id}" title="${t('edit_user')}" aria-label="${t('edit_user')}">${icon('pen')}</button>
                <button class="btn btn-outline btn-sm" data-reset="${u.id}" title="${t('reset_password')}" aria-label="${t('reset_password')}">${icon('key')}</button>
                ${u.id === user.id ? '' : `<button class="btn btn-danger btn-sm" data-delete="${u.id}" title="${t('delete_user')}" aria-label="${t('delete_user')}">${icon('trash')}</button>`}
              </td>
            </tr>`,
            )
            .join('')}
        </tbody>
      </table>`;

    wireRowEvents(tableEl, refreshUsers, user);
    updateBulkToolbar(container);
  }

  await refreshUsers();

  container
    .querySelector('#btn-new-user')
    .addEventListener('click', () => openUserForm(null, refreshUsers));
  container
    .querySelector('#bulk-activate')
    .addEventListener('click', () => runBulk('activate', refreshUsers, container));
  container
    .querySelector('#bulk-deactivate')
    .addEventListener('click', () => runBulk('deactivate', refreshUsers, container));
  container
    .querySelector('#bulk-reset')
    .addEventListener('click', () => openBulkResetModal(refreshUsers, container));

  const resetClientBtn = container.querySelector('#btn-reset-client');
  if (resetClientBtn) resetClientBtn.addEventListener('click', openResetClientModal);
  const backupBtn = container.querySelector('#btn-full-backup');
  if (backupBtn) backupBtn.addEventListener('click', () => runFullBackup(backupBtn));
  const importRestoreBtn = container.querySelector('#btn-import-restore');
  if (importRestoreBtn) importRestoreBtn.addEventListener('click', openImportRestoreModal);
  const factoryResetBtn = container.querySelector('#btn-factory-reset');
  if (factoryResetBtn) factoryResetBtn.addEventListener('click', openFactoryResetModal);
}

function wireRowEvents(tableEl, refreshUsers, currentUser) {
  const selectAll = tableEl.querySelector('#select-all');
  selectAll.addEventListener('change', () => {
    tableEl.querySelectorAll('.row-checkbox').forEach((cb) => {
      cb.checked = selectAll.checked;
      const id = Number(cb.getAttribute('data-id'));
      if (selectAll.checked) selected.add(id);
      else selected.delete(id);
    });
    updateBulkToolbar();
  });

  tableEl.querySelectorAll('.row-checkbox').forEach((cb) => {
    cb.addEventListener('change', () => {
      const id = Number(cb.getAttribute('data-id'));
      if (cb.checked) selected.add(id);
      else selected.delete(id);
      updateBulkToolbar();
    });
  });

  tableEl.querySelectorAll('[data-edit]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const u = cachedUsers.find((x) => x.id === Number(btn.getAttribute('data-edit')));
      openUserForm(u, refreshUsers);
    });
  });

  tableEl.querySelectorAll('[data-reset]').forEach((btn) => {
    btn.addEventListener('click', () =>
      openResetModal(Number(btn.getAttribute('data-reset')), refreshUsers),
    );
  });

  tableEl.querySelectorAll('[data-delete]').forEach((btn) => {
    btn.addEventListener('click', () =>
      confirmDeleteUser(Number(btn.getAttribute('data-delete')), refreshUsers),
    );
  });
}

function updateBulkToolbar() {
  const toolbar = document.querySelector('#bulk-toolbar');
  const countEl = document.querySelector('#bulk-count');
  if (!toolbar || !countEl) return;
  countEl.textContent = selected.size;
  toolbar.classList.toggle('show', selected.size > 0);
}

async function runBulk(action, refreshUsers, container) {
  if (selected.size === 0) return;
  try {
    await bulkUserAction([...selected], action);
    toast(getLang() === 'ar' ? 'تم تنفيذ الإجراء الجماعي' : 'Bulk action applied', 'success');
    selected = new Set();
    await refreshUsers();
  } catch (err) {
    toast(err.message, 'error');
  }
}

function openBulkResetModal(refreshUsers, container) {
  if (selected.size === 0) return;
  const lang = getLang();
  const overlay = openModal(
    t('bulk_reset_password'),
    `
    <div class="form-group">
      <label class="required">${t('new_password')}</label>
      <input type="text" id="bulk-pw" minlength="6" aria-required="true"/>
    </div>
    <button class="btn btn-primary btn-block" id="bulk-pw-submit">${icon('key')} ${t('save')}</button>
  `,
  );
  overlay.querySelector('#bulk-pw-submit').addEventListener('click', async () => {
    const pw = overlay.querySelector('#bulk-pw').value;
    if (!pw || pw.length < 6) {
      toast(t('required'), 'error');
      return;
    }
    try {
      await bulkUserAction([...selected], 'reset_password', pw);
      toast(lang === 'ar' ? 'تم تحديث كلمات المرور' : 'Passwords updated', 'success');
      selected = new Set();
      closeModal();
      await refreshUsers();
    } catch (err) {
      toast(err.message, 'error');
    }
  });
}

function openResetModal(userId, refreshUsers) {
  const lang = getLang();
  const overlay = openModal(
    t('reset_password'),
    `
    <div class="form-group">
      <label class="required">${t('new_password')}</label>
      <input type="text" id="reset-pw" minlength="6" aria-required="true"/>
    </div>
    <button class="btn btn-primary btn-block" id="reset-pw-submit">${icon('key')} ${t('save')}</button>
  `,
  );
  overlay.querySelector('#reset-pw-submit').addEventListener('click', async () => {
    const pw = overlay.querySelector('#reset-pw').value;
    if (!pw || pw.length < 6) {
      toast(t('required'), 'error');
      return;
    }
    try {
      await resetUserPassword(userId, pw);
      toast(lang === 'ar' ? 'تم تحديث كلمة المرور' : 'Password updated', 'success');
      closeModal();
    } catch (err) {
      toast(err.message, 'error');
    }
  });
}

function confirmDeleteUser(userId, refreshUsers) {
  const overlay = openModal(
    t('delete_user'),
    `
    <p>${t('confirm_delete_user')}</p>
    <div style="display:flex;gap:8px;justify-content:flex-end;">
      <button class="btn btn-outline" id="cancel-delete">${t('cancel')}</button>
      <button class="btn btn-danger" id="confirm-delete">${icon('trash')} ${t('delete_user')}</button>
    </div>
  `,
  );
  overlay.querySelector('#cancel-delete').addEventListener('click', closeModal);
  overlay.querySelector('#confirm-delete').addEventListener('click', async () => {
    try {
      await deleteUser(userId);
      toast(getLang() === 'ar' ? 'تم حذف المستخدم' : 'User deleted', 'success');
      closeModal();
      await refreshUsers();
    } catch (err) {
      toast(err.message, 'error');
    }
  });
}

function openUserForm(existing, refreshUsers) {
  const lang = getLang();
  const isEdit = !!existing;
  const overlay = openModal(
    isEdit ? t('edit_user') : t('create_user'),
    `
    <div class="search-form-grid">
      <div class="form-group"><label class="required">${lang === 'ar' ? 'الاسم (عربي)' : 'Name (Arabic)'}</label><input id="f-name-ar" aria-required="true" value="${escapeHtml(existing?.name_ar || '')}"/></div>
      <div class="form-group"><label class="required">${lang === 'ar' ? 'الاسم (إنجليزي)' : 'Name (English)'}</label><input id="f-name-en" aria-required="true" value="${escapeHtml(existing?.name_en || '')}"/></div>
      <div class="form-group"><label class="required">${t('username')}</label><input id="f-username" aria-required="true" value="${escapeHtml(existing?.username || '')}" ${isEdit ? 'disabled' : ''}/></div>
      <div class="form-group"><label>${t('email')}</label><input id="f-email" value="${escapeHtml(existing?.email || '')}"/></div>
      <div class="form-group"><label>${t('occupation')}</label><input id="f-occupation" value="${escapeHtml(existing?.occupation || '')}"/></div>
      <div class="form-group"><label class="required">${t('role')}</label>
        <select id="f-role" aria-required="true">${ROLES.map((r) => `<option value="${r}" ${existing?.role_code === r ? 'selected' : ''}>${t('role_' + r)}</option>`).join('')}</select>
      </div>
      <div class="form-group"><label>${t('civil_id')}</label><input id="f-civil-id" value="${escapeHtml(existing?.civil_id || '')}"/></div>
      ${!isEdit ? `<div class="form-group"><label class="required">${t('password')}</label><input type="text" id="f-password" aria-required="true" placeholder="${lang === 'ar' ? 'اكتب كلمة مرور' : 'Enter a password'}"/></div>` : ''}
    </div>
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;margin-bottom:10px;">
      <input type="checkbox" id="f-is-owner" ${existing?.is_owner ? 'checked' : ''} style="width:16px;height:16px;"/>
      ${t('owner_flag_label')}
    </label>
    ${
      isEdit
        ? `
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:600;margin-bottom:18px;">
      <input type="checkbox" id="f-is-active" ${existing.is_active ? 'checked' : ''} style="width:16px;height:16px;"/>
      ${lang === 'ar' ? 'الحساب فعّال' : 'Account active'}
    </label>`
        : ''
    }
    ${requiredNote()}
    <button class="btn btn-primary btn-block" id="user-form-submit">${icon('floppy-disk')} ${t('save')}</button>
  `,
    { wide: true },
  );

  overlay.querySelector('#user-form-submit').addEventListener('click', async () => {
    const payload = {
      name_ar: overlay.querySelector('#f-name-ar').value.trim(),
      name_en: overlay.querySelector('#f-name-en').value.trim(),
      email: overlay.querySelector('#f-email').value.trim() || null,
      occupation: overlay.querySelector('#f-occupation').value.trim() || null,
      role_code: overlay.querySelector('#f-role').value,
      civil_id: overlay.querySelector('#f-civil-id').value.trim() || null,
      is_owner: overlay.querySelector('#f-is-owner').checked,
    };
    if (isEdit) payload.is_active = overlay.querySelector('#f-is-active').checked;
    if (!payload.name_ar || !payload.name_en) {
      toast(t('required'), 'error');
      return;
    }
    try {
      if (isEdit) {
        await updateUser(existing.id, payload);
      } else {
        const username = overlay.querySelector('#f-username').value.trim();
        const password = overlay.querySelector('#f-password').value;
        if (!username || !password) {
          toast(t('required'), 'error');
          return;
        }
        await createUser({ ...payload, username, password });
      }
      toast(getLang() === 'ar' ? 'تم الحفظ بنجاح' : 'Saved successfully', 'success');
      closeModal();
      await refreshUsers();
    } catch (err) {
      toast(err.message, 'error');
    }
  });
}

const FACTORY_RESET_PHRASE = 'RESET DATABASE';
const IMPORT_RESTORE_PHRASE = 'RESTORE DATABASE';

function openResetClientModal() {
  const overlay = openModal(
    t('reset_client_title'),
    `
    <p>${t('reset_client_confirm_body')}</p>
    <div style="display:flex;gap:8px;justify-content:flex-end;">
      <button class="btn btn-outline" id="cancel-reset-client">${t('cancel')}</button>
      <button class="btn btn-primary" id="confirm-reset-client">${icon('broom')} ${t('reset_client_confirm_btn')}</button>
    </div>
  `,
  );
  overlay.querySelector('#cancel-reset-client').addEventListener('click', closeModal);
  overlay.querySelector('#confirm-reset-client').addEventListener('click', () => {
    // Client-only: wipes this browser's ENTIRE localStorage/sessionStorage
    // (not just the app's own session key) and reloads. Deliberately never
    // calls the server — the server has no "reset this one device" concept,
    // and shouldn't need one. Safe by construction: nothing here can touch
    // another device's state or any server-side record.
    localStorage.clear();
    sessionStorage.clear();
    location.hash = '';
    location.reload();
  });
}

async function runFullBackup(btn) {
  btn.disabled = true;
  const original = btn.innerHTML;
  btn.innerHTML = `${icon('spinner', 'fa-spin')} ${t('full_backup_preparing')}`;
  try {
    const { blob, filename } = await downloadBackup();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast(t('full_backup_success'), 'success');
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = original;
  }
}

function openFactoryResetModal() {
  const overlay = openModal(
    t('factory_reset_title'),
    `
    <p style="color:var(--color-danger);font-weight:600;">${t('factory_reset_warning')}</p>
    <p>${t('factory_reset_type_prompt')}</p>
    <p style="font-family:monospace;font-weight:700;background:var(--color-danger-bg);color:var(--color-danger);padding:8px 12px;border-radius:6px;display:inline-block;">${FACTORY_RESET_PHRASE}</p>
    <div class="form-group" style="margin-top:12px;">
      <label class="required">${t('factory_reset_type_prompt')}</label>
      <input id="factory-reset-input" aria-required="true" placeholder="${t('factory_reset_input_placeholder')}" autocomplete="off"/>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end;">
      <button class="btn btn-outline" id="cancel-factory-reset">${t('cancel')}</button>
      <button class="btn btn-danger" id="confirm-factory-reset" disabled>${icon('triangle-exclamation')} ${t('factory_reset_confirm_btn')}</button>
    </div>
  `,
    { wide: true },
  );

  const input = overlay.querySelector('#factory-reset-input');
  const confirmBtn = overlay.querySelector('#confirm-factory-reset');
  input.addEventListener('input', () => {
    confirmBtn.disabled = input.value !== FACTORY_RESET_PHRASE;
  });
  overlay.querySelector('#cancel-factory-reset').addEventListener('click', closeModal);
  confirmBtn.addEventListener('click', async () => {
    if (input.value !== FACTORY_RESET_PHRASE) {
      toast(t('factory_reset_mismatch'), 'error');
      return;
    }
    confirmBtn.disabled = true;
    try {
      await resetDatabase(input.value);
      toast(t('factory_reset_success'), 'success');
      setTimeout(() => {
        clearSession();
        location.hash = '';
        location.reload();
      }, 1500);
    } catch (err) {
      toast(err.message, 'error');
      confirmBtn.disabled = false;
    }
  });
}

function openImportRestoreModal() {
  const overlay = openModal(
    t('import_restore_title'),
    `
    <p style="color:var(--color-danger);font-weight:600;">${t('import_restore_warning')}</p>
    <div class="form-group">
      <label class="required">${t('import_restore_select_file')}</label>
      <input type="file" id="restore-file-input" accept=".zip,application/zip"/>
    </div>
    <p>${t('import_restore_type_prompt')}</p>
    <p style="font-family:monospace;font-weight:700;background:var(--color-danger-bg);color:var(--color-danger);padding:8px 12px;border-radius:6px;display:inline-block;">${IMPORT_RESTORE_PHRASE}</p>
    <div class="form-group" style="margin-top:12px;">
      <label class="required">${t('import_restore_type_prompt')}</label>
      <input id="restore-confirm-input" aria-required="true" placeholder="${t('factory_reset_input_placeholder')}" autocomplete="off"/>
    </div>
    <div style="display:flex;gap:8px;justify-content:flex-end;">
      <button class="btn btn-outline" id="cancel-import-restore">${t('cancel')}</button>
      <button class="btn btn-danger" id="confirm-import-restore" disabled>${icon('upload')} ${t('import_restore_confirm_btn')}</button>
    </div>
  `,
    { wide: true },
  );

  const fileInput = overlay.querySelector('#restore-file-input');
  const phraseInput = overlay.querySelector('#restore-confirm-input');
  const confirmBtn = overlay.querySelector('#confirm-import-restore');

  function updateEnabled() {
    confirmBtn.disabled = phraseInput.value !== IMPORT_RESTORE_PHRASE || !fileInput.files.length;
  }
  fileInput.addEventListener('change', updateEnabled);
  phraseInput.addEventListener('input', updateEnabled);

  overlay.querySelector('#cancel-import-restore').addEventListener('click', closeModal);
  confirmBtn.addEventListener('click', async () => {
    if (!fileInput.files.length) {
      toast(t('import_restore_no_file'), 'error');
      return;
    }
    if (phraseInput.value !== IMPORT_RESTORE_PHRASE) {
      toast(t('import_restore_mismatch'), 'error');
      return;
    }
    confirmBtn.disabled = true;
    const original = confirmBtn.innerHTML;
    confirmBtn.innerHTML = `${icon('spinner', 'fa-spin')} ${t('import_restore_restoring')}`;
    try {
      await restoreDatabase(fileInput.files[0], phraseInput.value);
      toast(t('import_restore_success'), 'success');
      setTimeout(() => {
        clearSession();
        location.hash = '';
        location.reload();
      }, 1500);
    } catch (err) {
      toast(err.message, 'error');
      confirmBtn.disabled = false;
      confirmBtn.innerHTML = original;
    }
  });
}

function permBadge(level) {
  const map = {
    full: ['badge-success', 'check'],
    edit: ['badge-info', 'pen'],
    limited: ['badge-warning', 'circle-half-stroke'],
    view: ['badge-warning', 'eye'],
    own: ['badge-muted', 'user'],
    none: ['badge-danger', 'xmark'],
  };
  const [cls, iconName] = map[level] || ['badge-muted', 'minus'];
  return `<span class="badge ${cls}">${icon(iconName)}</span>`;
}
