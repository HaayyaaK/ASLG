import { t, getLang } from "../i18n.js";
import { listActivityLog, exportActivityLogCsv } from "../api.js";
import { formatDate, escapeHtml, icon, toast } from "../ui.js";
import { printRecord, printButton } from "../print.js";

const ACTION_BADGE = {
  login_success: "badge-success",
  login_failed: "badge-danger",
  logout: "badge-muted",
  user_create: "badge-success",
  user_update: "badge-info",
  user_delete: "badge-danger",
  password_reset: "badge-warning",
  user_bulk_activate: "badge-success",
  user_bulk_deactivate: "badge-warning",
  user_bulk_reset_password: "badge-warning",
  document_upload: "badge-success",
  document_delete: "badge-danger",
  document_download: "badge-info",
  document_grant_access: "badge-warning",
  case_stage_update: "badge-info",
  case_note_add: "badge-info",
  case_create: "badge-success",
  status_update_requested: "badge-warning",
  database_backup_download: "badge-info",
  database_restore: "badge-danger",
  database_reset: "badge-danger",
  reminder_create: "badge-info",
  reminder_resolve: "badge-success",
  case_track: "badge-info",
  case_untrack: "badge-muted",
  case_watch: "badge-info",
  case_unwatch: "badge-muted",
};

const ENTITY_LABEL = {
  user: { ar: "مستخدم", en: "User" },
  document: { ar: "مستند", en: "Document" },
  case: { ar: "قضية", en: "Case" },
  reminder: { ar: "تذكير", en: "Reminder" },
};

export function destroy() {}

export async function render(container, user) {
  container.innerHTML = `
    <div class="flex-between" style="margin-bottom:16px;">
      <h2 class="mt-0">${t("activity_log_title")}</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        ${printButton("al-print")}
        <button class="btn btn-accent btn-sm" id="al-export" title="${t("activity_log_export")}">${icon("file-arrow-down")} ${t("activity_log_export")}</button>
      </div>
    </div>
    <div class="panel">
      <div class="panel-body table-wrap" id="al-table"><p class="text-muted">${icon("spinner", "fa-spin")}</p></div>
    </div>
  `;

  const lang = getLang();
  const tableEl = container.querySelector("#al-table");

  let auditRows = [];

  // Wired before the first `await`, so the button is live as soon as it is
  // visible; it closes over `auditRows`.
  //
  // A paper copy of the audit trail. Export CSV remains the machine-readable
  // route; this is the one an auditor signs and files.
  container.querySelector("#al-print").addEventListener("click", () => {
    if (auditRows.length === 0) {
      toast(t("print_nothing_to_print"), "info");
      return;
    }
    printRecord({
      title: t("print_activity_title"),
      subtitle: t("activity_log_title"),
      sections: [
        {
          heading: t("activity_log_title"),
          table: {
            columns: [t("al_timestamp"), t("al_user"), t("al_action"), t("al_entity"), t("al_reference"), t("al_ip")],
            rows: auditRows.map((r) => {
              const actionLabel = t("al_action_" + r.action) === "al_action_" + r.action ? r.action : t("al_action_" + r.action);
              const entityLabel = r.entity_type ? (ENTITY_LABEL[r.entity_type]?.[lang] || r.entity_type) : "—";
              return [
                formatDate(r.created_at, { time: true }),
                r.user_id ? (lang === "ar" ? r.user_name_ar || r.user_name_en : r.user_name_en || r.user_name_ar) || `#${r.user_id}` : "—",
                actionLabel,
                entityLabel,
                r.entity_type && r.entity_id ? `${entityLabel} #${r.entity_id}` : "—",
                r.ip_address || "—",
              ];
            }),
          },
        },
      ],
    });
  });

  try {
    const rows = await listActivityLog();
    auditRows = rows;
    if (rows.length === 0) {
      tableEl.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon("clipboard-list")}</div>${t("activity_log_empty")}</div>`;
    } else {
      tableEl.innerHTML = `
        <table class="data-table">
          <thead><tr>
            <th>${t("al_timestamp")}</th><th>${t("al_user")}</th><th>${t("al_action")}</th>
            <th>${t("al_entity")}</th><th>${t("al_reference")}</th><th>${t("al_ip")}</th>
          </tr></thead>
          <tbody>
            ${rows.map((r) => renderRow(r, lang)).join("")}
          </tbody>
        </table>`;
    }
  } catch (err) {
    tableEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
  }

  // Optional call: defence in depth alongside the per-render container in
  // app.js, so a late resume can never dereference null.
  container.querySelector("#al-export")?.addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    try {
      const blob = await exportActivityLogCsv();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "activity-log.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast(err.message, "error");
    } finally {
      btn.disabled = false;
    }
  });
}

function renderRow(r, lang) {
  const userLabel = r.user_id
    ? escapeHtml(lang === "ar" ? r.user_name_ar || r.user_name_en : r.user_name_en || r.user_name_ar) || `#${r.user_id}`
    : "—";
  const actionLabel = t("al_action_" + r.action) === "al_action_" + r.action ? r.action : t("al_action_" + r.action);
  const badgeClass = ACTION_BADGE[r.action] || "badge-muted";
  const entityLabel = r.entity_type ? (ENTITY_LABEL[r.entity_type]?.[lang] || r.entity_type) : "—";
  const reference = r.entity_type && r.entity_id ? `${entityLabel} #${r.entity_id}` : "—";
  return `<tr>
    <td data-label="${t("al_timestamp")}">${formatDate(r.created_at, { time: true })}</td>
    <td data-label="${t("al_user")}">${userLabel}</td>
    <td data-label="${t("al_action")}"><span class="badge ${badgeClass}">${actionLabel}</span></td>
    <td data-label="${t("al_entity")}">${entityLabel}</td>
    <td data-label="${t("al_reference")}">${reference}</td>
    <td data-label="${t("al_ip")}">${r.ip_address ? escapeHtml(r.ip_address) : "—"}</td>
  </tr>`;
}
