/**
 * Shared "Request Update" dialog.
 *
 * Used from two places that ask the same question of the same backend —
 * an Official Search result, and the last point on a Case Timeline — so the
 * dialog, its validation and its success/failure handling live here once
 * rather than being written twice and drifting apart.
 *
 * Deliberately small: one person, one date, one optional message. The brief
 * was explicitly "do not add a complicated workflow if a simple one is
 * sufficient", and everything else the underlying task model supports
 * (stage pre-selection, follow-up vs. request type) is noise for a lawyer who
 * just wants to ask "where are we on this?".
 *
 * It never changes case status or the timeline — asking for an update is not
 * itself legal progress. The server enforces that too.
 */

import { t, getLang } from "./i18n.js";
import { listAssignableStaff, requestStatusUpdate } from "./api.js";
import { openModal, closeModal, toast, icon, escapeHtml, requiredNote } from "./ui.js";

/** Only these roles may hand work to another person (mirrors the server's
 *  require_roles("Admin", "Lawyer") on /api/search/request-update). */
export function canRequestUpdate(user) {
  return user?.role_code === "Admin" || user?.role_code === "Lawyer";
}

function defaultDueLocal(daysAhead = 3) {
  const d = new Date();
  d.setDate(d.getDate() + daysAhead);
  d.setHours(12, 0, 0, 0);
  // datetime-local wants a local-time string with no timezone suffix.
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * @param {object} opts
 * @param {string} opts.sourceType  "case" | "session" | "expert" | "execution"
 * @param {number} opts.sourceRefId id of that record
 * @param {string} [opts.contextLabel] e.g. "1123/2024" — shown so the user can
 *                                     see what they are asking about
 * @param {function} [opts.onDone]  called after a successful request
 */
export async function openRequestUpdateDialog({ sourceType, sourceRefId, contextLabel = "", onDone }) {
  const lang = getLang();
  const overlay = openModal(t("request_update"), `<p class="text-muted">${icon("spinner", "fa-spin")}</p>`);

  let staff = [];
  try {
    staff = await listAssignableStaff();
  } catch (err) {
    overlay.querySelector(".modal-body").innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
    return;
  }
  if (staff.length === 0) {
    overlay.querySelector(".modal-body").innerHTML = `<p class="text-muted">${t("no_staff_to_ask")}</p>`;
    return;
  }

  overlay.querySelector(".modal-body").innerHTML = `
    ${contextLabel ? `<p class="text-muted mt-0">${t("about_label")}: <b>${escapeHtml(contextLabel)}</b></p>` : ""}
    <div class="form-group">
      <label class="required">${t("ask_person")}</label>
      <select id="ru-person" aria-required="true">
        ${staff.map((u) => `<option value="${u.id}">${escapeHtml(lang === "ar" ? u.name_ar : u.name_en)} — ${t("role_" + u.role_code)}</option>`).join("")}
      </select>
    </div>
    <div class="form-group">
      <label class="required">${t("reply_by")}</label>
      <input type="datetime-local" id="ru-due" aria-required="true" value="${defaultDueLocal()}"/>
    </div>
    <div class="form-group">
      <label>${t("message_optional")}</label>
      <textarea id="ru-message" rows="3" maxlength="500"
        style="width:100%;padding:11px 14px;border:1px solid var(--color-border);border-radius:6px;"
        placeholder="${t("request_update_placeholder")}"></textarea>
    </div>
    <p class="text-muted" style="font-size:12px;">${t("request_update_hint")}</p>
    ${requiredNote()}
    <div style="display:flex;gap:8px;justify-content:flex-end;">
      <button class="btn btn-outline" id="ru-cancel">${t("cancel")}</button>
      <button class="btn btn-accent" id="ru-send">${icon("paper-plane")} ${t("send_request")}</button>
    </div>
  `;

  overlay.querySelector("#ru-cancel").addEventListener("click", closeModal);

  const sendBtn = overlay.querySelector("#ru-send");
  sendBtn.addEventListener("click", async () => {
    const due = overlay.querySelector("#ru-due").value;
    if (!due) {
      toast(t("pick_reply_date"), "error");
      return;
    }
    if (new Date(due).getTime() <= Date.now()) {
      toast(t("reply_date_must_be_future"), "error");
      return;
    }
    const original = sendBtn.innerHTML;
    sendBtn.disabled = true;
    sendBtn.innerHTML = `${icon("spinner", "fa-spin")} ${t("sending")}`;
    try {
      await requestStatusUpdate({
        source_type: sourceType,
        source_ref_id: sourceRefId,
        assigned_to: Number(overlay.querySelector("#ru-person").value),
        due_at: new Date(due).toISOString(),
        message: overlay.querySelector("#ru-message").value.trim() || null,
        also_track: true,
      });
      toast(t("request_update_sent"), "success");
      closeModal();
      if (onDone) await onDone();
    } catch (err) {
      // Never fail silently — the whole point of this rework.
      toast(err.message, "error");
      sendBtn.disabled = false;
      sendBtn.innerHTML = original;
    }
  });
}
