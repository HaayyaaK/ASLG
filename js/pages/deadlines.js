import { t, getLang } from "../i18n.js";
import { listDeadlines, syncDeadlines, confirmDeadline, waiveDeadline, getPermission } from "../api.js";
import { formatDate, icon, toast, escapeHtml, parseServerDate, openModal, closeModal } from "../ui.js";
import { openCaseDetail } from "./cases.js";
import { printRecord, printButton } from "../print.js";

/**
 * Procedural Intelligence — the Deadlines page.
 *   ... -> Deadline -> Reminder/Notification -> Completion
 *
 * This is a firm-wide (case-scoped, same as everywhere else) view of every
 * `CaseDeadline` row. A Client (`deadlines` permission level 'own') only
 * ever sees `confidence == 'confirmed'` rows — the server already filters
 * this (see backend/app/routers/deadlines.py), so nothing extra is needed
 * here for that isolation, but the confirm/waive actions are additionally
 * hidden client-side for anyone below 'edit', matching the server's own gate.
 */
export function destroy() {}

export async function render(container, user) {
  const canAct = ["full", "edit"].includes(getPermission("deadlines"));
  let statusFilter = "";

  container.innerHTML = `
    <div class="flex-between" style="margin-bottom:16px;">
      <h2 class="mt-0">${t("deadlines_title")}</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        ${printButton("deadlines-print")}
        <select id="deadline-status-filter" style="width:auto;">
          <option value="">${t("deadline_filter_all")}</option>
          <option value="open">${t("deadline_status_open")}</option>
          <option value="missed">${t("deadline_status_missed")}</option>
          <option value="met">${t("deadline_status_met")}</option>
          <option value="waived">${t("deadline_status_waived")}</option>
        </select>
      </div>
    </div>
    <div class="panel"><div class="panel-body" id="deadlines-list"><p class="text-muted">${icon("spinner", "fa-spin")}</p></div></div>
  `;

  let visible = [];

  container.querySelector("#deadlines-print").addEventListener("click", () => {
    if (visible.length === 0) {
      toast(t("print_nothing_to_print"), "info");
      return;
    }
    const lang = getLang();
    printRecord({
      title: t("print_deadlines_title"),
      subtitle: t("deadlines_title"),
      sections: [{
        heading: t("deadlines_title"),
        table: {
          columns: [t("case_number"), t("deadline_type"), t("due_date"), t("assign_to"), t("proc_confidence"), t("print_status")],
          rows: visible.map((d) => [
            `${d.case_number}/${d.case_year}`,
            d.deadline_type_code,
            formatDate(d.due_at, { time: true }),
            lang === "ar" ? d.responsible_user_name_ar : d.responsible_user_name_en,
            t("proc_confidence_" + d.confidence),
            t("deadline_status_" + d.status),
          ]),
        },
      }],
    });
  });

  container.querySelector("#deadline-status-filter").addEventListener("change", (e) => {
    statusFilter = e.target.value;
    refresh();
  });

  async function refresh() {
    const listEl = container.querySelector("#deadlines-list");
    listEl.innerHTML = `<p class="text-muted">${icon("spinner", "fa-spin")}</p>`;
    // Idempotent refresh, mirroring escalation's own on-request contract —
    // safe (and cheap) to call on every page load.
    try { await syncDeadlines(); } catch { /* non-fatal: list still loads */ }

    let rows;
    try {
      rows = await listDeadlines(statusFilter ? { status_filter: statusFilter } : {});
    } catch (err) {
      listEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      return;
    }
    visible = rows;
    if (rows.length === 0) {
      listEl.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon("hourglass-half")}</div>${t("no_deadlines")}</div>`;
      return;
    }
    const lang = getLang();
    const now = Date.now();
    listEl.innerHTML = rows
      .map((d) => {
        const overdue = d.status === "open" && parseServerDate(d.due_at).getTime() < now;
        const statusBadge = d.status === "open"
          ? `<span class="badge ${overdue ? "badge-danger" : "badge-info"}">${overdue ? t("overdue") : t("deadline_status_open")}</span>`
          : d.status === "met" ? `<span class="badge badge-success">${t("deadline_status_met")}</span>`
          : d.status === "waived" ? `<span class="badge badge-muted">${t("deadline_status_waived")}</span>`
          : `<span class="badge badge-danger">${t("deadline_status_missed")}</span>`;
        const confidenceBadge = d.confidence === "confirmed"
          ? `<span class="badge badge-success">${t("proc_confidence_confirmed")}</span>`
          : `<span class="badge badge-warning" title="${t("proc_confidence_provisional_hint")}">${t("proc_confidence_provisional")}</span>`;
        return `
        <div class="reminder-item ${overdue ? "overdue" : ""}">
          <div>
            <div class="r-note">${d.case_number}/${d.case_year} — ${escapeHtml(d.deadline_type_code)} ${statusBadge} ${confidenceBadge}</div>
            <div class="r-meta">
              ${t("due_date")}: ${formatDate(d.due_at, { time: true })} • ${t("assign_to")}: ${escapeHtml((lang === "ar" ? d.responsible_user_name_ar : d.responsible_user_name_en) || "—")}
              ${d.legal_citation ? `<br>${t("proc_legal_basis")}: ${escapeHtml(d.legal_citation)}` : ""}
            </div>
          </div>
          <div class="reminder-actions">
            <button class="btn btn-outline btn-sm" data-open-case="${d.case_id}" title="${t("open_case")}">${icon("folder-open")} ${t("open_case")}</button>
            ${canAct && d.status === "open" && d.confidence === "provisional" ? `<button class="btn btn-outline btn-sm" data-confirm="${d.id}">${icon("check")} ${t("deadline_confirm")}</button>` : ""}
            ${canAct && d.status === "open" ? `<button class="btn btn-outline btn-sm" data-waive="${d.id}">${icon("ban")} ${t("deadline_waive")}</button>` : ""}
          </div>
        </div>`;
      })
      .join("");

    listEl.querySelectorAll("[data-open-case]").forEach((btn) => {
      btn.addEventListener("click", () => openCaseDetail(Number(btn.getAttribute("data-open-case")), user));
    });
    listEl.querySelectorAll("[data-confirm]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await confirmDeadline(Number(btn.getAttribute("data-confirm")));
          toast(t("deadline_confirmed_success"), "success");
          await refresh();
        } catch (err) {
          toast(err.message, "error");
          btn.disabled = false;
        }
      });
    });
    listEl.querySelectorAll("[data-waive]").forEach((btn) => {
      btn.addEventListener("click", () => openWaiveDialog(Number(btn.getAttribute("data-waive")), refresh));
    });
  }

  await refresh();
}

function openWaiveDialog(deadlineId, onDone) {
  const overlay = openModal(t("deadline_waive"), `
    <div class="form-group">
      <label class="required">${t("deadline_waive_reason")}</label>
      <textarea id="waive-reason" rows="3" aria-required="true"></textarea>
    </div>
    <button class="btn btn-accent btn-block" id="waive-submit">${icon("ban")} ${t("deadline_waive")}</button>
  `);
  overlay.querySelector("#waive-submit").addEventListener("click", async () => {
    const reason = overlay.querySelector("#waive-reason").value.trim();
    if (!reason) { toast(t("required"), "error"); return; }
    try {
      await waiveDeadline(deadlineId, reason);
      toast(t("deadline_waived_success"), "success");
      closeModal();
      await onDone();
    } catch (err) {
      toast(err.message, "error");
    }
  });
}
