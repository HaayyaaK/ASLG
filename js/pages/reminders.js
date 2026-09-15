import { t, getLang } from "../i18n.js";
import { listReminders, resolveReminder, listCases, createReminder, listAssignableUsers, getPermission } from "../api.js";
import { formatDate, icon, toast, escapeHtml, openModal, closeModal, routeFilter, parseServerDate, requiredNote } from "../ui.js";
import { printRecord, printButton } from "../print.js";

const STAGES = ["new", "prep", "pleading", "judgment", "execution", "closed"];

/**
 * Filters the Dashboard's task cards can arrive with. Each one mirrors exactly
 * what the corresponding card counted on the server (see
 * backend/app/routers/dashboard.py::task_stats), so the list a user lands on
 * matches the number they clicked.
 */
const FILTERS = {
  "mine-open": { label: "stat_my_open_tasks", match: (r, user) => r.assigned_to === user.id && r.status === "open" },
  overdue: {
    label: "stat_overdue_tasks",
    match: (r, user) => r.assigned_to === user.id && r.status === "open" && parseServerDate(r.due_at).getTime() < Date.now(),
  },
  "status-requests": {
    label: "stat_pending_status_requests",
    match: (r, user) => r.assigned_to === user.id && r.status === "open" && r.type === "status_update_request",
  },
  "assigned-by-me": { label: "stat_tasks_i_assigned", match: (r, user) => r.created_by === user.id && r.status === "open" },
};

export function destroy() {}

export async function render(container, user) {
  const canCreate = ["full", "edit"].includes(getPermission("reminders"));

  const activeFilter = FILTERS[routeFilter()] ? routeFilter() : "";

  container.innerHTML = `
    <div class="flex-between" style="margin-bottom:16px;">
      <h2 class="mt-0">${t("reminders_title")}</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        ${printButton("reminders-print")}
        ${canCreate ? `<button class="btn btn-accent btn-sm" id="new-reminder-btn">${icon("plus")} ${t("create_reminder")}</button>` : ""}
      </div>
    </div>
    ${activeFilter ? `
    <div class="filter-chip-row">
      <span class="filter-chip">${icon("filter")} ${t(FILTERS[activeFilter].label)}
        <button class="filter-chip-clear" id="clear-filter" title="${t("show_all")}" aria-label="${t("show_all")}">${icon("xmark")}</button>
      </span>
    </div>` : ""}
    <div class="panel"><div class="panel-body" id="reminders-list"><p class="text-muted">${icon("spinner", "fa-spin")}</p></div></div>
  `;

  container.querySelector("#clear-filter")?.addEventListener("click", () => { location.hash = "#/reminders"; });

  // The task list exactly as filtered on screen, kept for Print.
  let visibleReminders = [];

  // Wired before the first `await`, so the button is live as soon as it is
  // visible; it closes over `visibleReminders` and therefore always prints
  // whatever the list currently holds.
  container.querySelector("#reminders-print").addEventListener("click", () => {
    if (visibleReminders.length === 0) {
      toast(t("print_nothing_to_print"), "info");
      return;
    }
    const lang = getLang();
    const now = Date.now();
    printRecord({
      title: t("print_tasks_title"),
      subtitle: t("reminders_title"),
      meta: [
        { label: t("print_filters_applied"), value: activeFilter ? t(FILTERS[activeFilter].label) : t("print_none") },
      ],
      sections: [
        {
          heading: t("reminders_title"),
          table: {
            columns: [t("linked_case"), t("print_task"), t("print_type"), t("due_date"), t("assign_to"), t("created_by"), t("print_status")],
            rows: visibleReminders.map((r) => {
              const overdue = r.status === "open" && parseServerDate(r.due_at).getTime() < now;
              return [
                r.case_number,
                r.note,
                r.type === "status_update_request"
                  ? `${t("reminder_type_status_update")}${r.requested_stage ? ` → ${t("stage_" + r.requested_stage)}` : ""}`
                  : t("reminder_type_follow_up"),
                formatDate(r.due_at, { time: true }),
                lang === "ar" ? r.assigned_to_name_ar : r.assigned_to_name_en,
                lang === "ar" ? r.created_by_name_ar : r.created_by_name_en,
                r.status === "open"
                  ? overdue ? t("overdue") : t("status_open")
                  : r.status === "done" ? t("status_done_reminder") : t("status_dismissed"),
              ];
            }),
          },
        },
      ],
    });
  });

  async function refresh() {
    const listEl = container.querySelector("#reminders-list");
    let reminders;
    try {
      reminders = await listReminders();
    } catch (err) {
      listEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      return;
    }
    if (activeFilter) reminders = reminders.filter((r) => FILTERS[activeFilter].match(r, user));
    visibleReminders = reminders;
    if (reminders.length === 0) {
      listEl.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon("clock-rotate-left")}</div>${activeFilter ? t("no_reminders_for_filter") : t("no_reminders")}</div>`;
      return;
    }
    const now = Date.now();
    listEl.innerHTML = reminders
      .map((r) => {
        const overdue = r.status === "open" && parseServerDate(r.due_at).getTime() < now;
        const typeLabel = r.type === "status_update_request" ? t("reminder_type_status_update") : t("reminder_type_follow_up");
        const statusBadge = r.status === "open"
          ? `<span class="badge ${overdue ? "badge-danger" : "badge-info"}">${overdue ? t("overdue") : t("status_open")}</span>`
          : r.status === "done"
          ? `<span class="badge badge-success">${t("status_done_reminder")}</span>`
          : `<span class="badge badge-muted">${t("status_dismissed")}</span>`;
        return `
        <div class="reminder-item ${overdue ? "overdue" : ""}">
          <div>
            <div class="r-note">${escapeHtml(r.note)} ${statusBadge}</div>
            <div class="r-meta">
              ${r.case_number} • ${typeLabel}${r.requested_stage ? ` → ${t("stage_" + r.requested_stage)}` : ""}<br>
              ${t("due_date")}: ${formatDate(r.due_at, { time: true })} • ${t("created_by")}: ${getLang() === "ar" ? r.created_by_name_ar : r.created_by_name_en} • ${t("assign_to")}: ${getLang() === "ar" ? r.assigned_to_name_ar : r.assigned_to_name_en}
            </div>
          </div>
          ${r.status === "open" && r.assigned_to === user.id ? `
          <div class="reminder-actions">
            <button class="btn btn-outline btn-sm" data-resolve="${r.id}" data-status="done">${icon("check")} ${t("mark_done")}</button>
            <button class="btn btn-outline btn-sm" data-resolve="${r.id}" data-status="dismissed">${icon("xmark")} ${t("dismiss")}</button>
          </div>` : ""}
        </div>`;
      })
      .join("");

    listEl.querySelectorAll("[data-resolve]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        try {
          await resolveReminder(Number(btn.getAttribute("data-resolve")), btn.getAttribute("data-status"));
          refresh();
        } catch (err) {
          toast(err.message, "error");
        }
      });
    });
  }

  await refresh();

  const newBtn = container.querySelector("#new-reminder-btn");
  if (newBtn) {
    newBtn.addEventListener("click", async () => {
      newBtn.disabled = true;
      try {
        // Only cases with an assigned lawyer are eligible — same
        // precondition the case-detail "Schedule Reminder" form already
        // requires, since every reminder needs a real assignee and a
        // non-free-assign creator can only target the case's own lawyer.
        const cases = (await listCases()).filter((c) => c.assigned_lawyer_id);
        openCreateReminderModal(cases, user, refresh);
      } catch (err) {
        toast(err.message, "error");
      } finally {
        newBtn.disabled = false;
      }
    });
  }
}


function lawyerName(c) {
  return (getLang() === "ar" ? c.assigned_lawyer_name_ar : c.assigned_lawyer_name_en) || "—";
}

async function openCreateReminderModal(cases, user, onDone) {
  const lang = getLang();
  const canAssignFreely = user.role_code === "Admin" || (user.role_code === "Lawyer" && user.is_owner);

  if (cases.length === 0) {
    toast(lang === "ar" ? "لا توجد قضايا مؤهلة (بمحامٍ معيّن) لإنشاء تذكير لها" : "No eligible cases (with an assigned lawyer) to create a reminder for", "error");
    return;
  }

  let assignableUsers = [];
  if (canAssignFreely) {
    try {
      assignableUsers = await listAssignableUsers();
    } catch {
      assignableUsers = [];
    }
  }

  const overlay = openModal(t("create_reminder"), `
    <div class="form-group">
      <label class="required">${t("linked_case")}</label>
      <select id="reminder-case" aria-required="true">
        ${cases.map((c) => `<option value="${c.id}">${c.case_number}/${c.case_year} — ${escapeHtml(lang === "ar" ? c.parties_ar : c.parties_en)}</option>`).join("")}
      </select>
    </div>
    <div class="search-form-grid">
      <div class="form-group">
        <label>${t("reminder_type")}</label>
        <select id="reminder-type">
          <option value="follow_up">${t("reminder_type_follow_up")}</option>
          <option value="status_update_request">${t("reminder_type_status_update")}</option>
        </select>
      </div>
      <div class="form-group" id="fg-requested-stage" style="display:none;">
        <label>${t("requested_stage")}</label>
        <select id="reminder-stage">
          ${STAGES.map((s) => `<option value="${s}">${t("stage_" + s)}</option>`).join("")}
        </select>
      </div>
      <div class="form-group">
        <label class="required">${t("due_date")}</label>
        <input type="datetime-local" id="reminder-due" aria-required="true"/>
      </div>
      <div class="form-group">
        <label class="required">${t("assign_to")}</label>
        ${
          canAssignFreely
            ? `<select id="reminder-assignee">
                ${assignableUsers
                  .map((u) => `<option value="${u.id}" ${u.id === cases[0].assigned_lawyer_id ? "selected" : ""}>${escapeHtml(lang === "ar" ? u.name_ar : u.name_en)} — ${t("role_" + u.role_code)}</option>`)
                  .join("")}
              </select>`
            : `<input id="reminder-assignee-display" value="${escapeHtml(lawyerName(cases[0]))}" disabled/>`
        }
      </div>
    </div>
    <div class="form-group">
      <label class="required">${t("notes")}</label>
      <textarea id="reminder-note" rows="2" aria-required="true" style="width:100%;padding:11px 14px;border:1px solid var(--color-border);border-radius:6px;" placeholder="${t("note_optional_stage")}" maxlength="500"></textarea>
    </div>
    ${requiredNote()}
    <button class="btn btn-accent btn-block" id="reminder-submit">${icon("clock-rotate-left")} ${t("create_reminder")}</button>
  `, { wide: true });

  const caseSelect = overlay.querySelector("#reminder-case");
  const assigneeDisplay = overlay.querySelector("#reminder-assignee-display");
  if (assigneeDisplay) {
    // Non-free-assign creators (Consultants) can only target the selected
    // case's own lawyer, so that display must track the case dropdown.
    caseSelect.addEventListener("change", () => {
      const c = cases.find((x) => x.id === Number(caseSelect.value));
      assigneeDisplay.value = lawyerName(c);
    });
  }

  const reminderType = overlay.querySelector("#reminder-type");
  const stageGroup = overlay.querySelector("#fg-requested-stage");
  reminderType.addEventListener("change", () => {
    stageGroup.style.display = reminderType.value === "status_update_request" ? "" : "none";
  });

  overlay.querySelector("#reminder-submit").addEventListener("click", async () => {
    const caseId = Number(caseSelect.value);
    const c = cases.find((x) => x.id === caseId);
    const due = overlay.querySelector("#reminder-due").value;
    const note = overlay.querySelector("#reminder-note").value.trim();
    if (!due || !note) {
      toast(t("required"), "error");
      return;
    }
    try {
      await createReminder({
        case_id: caseId,
        type: reminderType.value,
        requested_stage: reminderType.value === "status_update_request" ? overlay.querySelector("#reminder-stage").value : null,
        due_at: new Date(due).toISOString(),
        note,
        assigned_to: canAssignFreely ? Number(overlay.querySelector("#reminder-assignee").value) : c.assigned_lawyer_id,
      });
      toast(getLang() === "ar" ? "تم إنشاء التذكير" : "Reminder created", "success");
      closeModal();
      await onDone();
    } catch (err) {
      toast(err.message, "error");
    }
  });
}
