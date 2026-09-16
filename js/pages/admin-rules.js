import { t, getLang } from "../i18n.js";
import { listProcedureRules, verifyProcedureRule, disableProcedureRule, getPermission } from "../api.js";
import { icon, toast, escapeHtml, openModal, closeModal } from "../ui.js";

/**
 * The Procedure Rule catalogue — "the brain, as data". Every rule ships
 * disabled with a legal citation and a source tier (see Phase 1 blueprint
 * section 2.3 and backend/app/routers/rules.py's module docstring).
 * Enabling one here asserts a legal fact, gated server-side on Admin or an
 * owner-Lawyer AND `confirm: true` AND `source_tier != 'unverified'` — this
 * page's own gating (hiding the button below 'full', or for a non-owner
 * Lawyer) is a UX convenience, never the real security boundary.
 */
export function destroy() {}

export async function render(container, user) {
  const perm = getPermission("rules_admin");
  const mayVerify = perm === "full" && (user.role_code === "Admin" || (user.role_code === "Lawyer" && user.is_owner));

  container.innerHTML = `
    <div class="flex-between" style="margin-bottom:16px;">
      <h2 class="mt-0">${t("rules_admin_title")}</h2>
    </div>
    <p class="text-muted">${t("rules_admin_intro")}</p>
    <div class="panel"><div class="panel-body" id="rules-list"><p class="text-muted">${icon("spinner", "fa-spin")}</p></div></div>
  `;

  async function refresh() {
    const listEl = container.querySelector("#rules-list");
    let rules;
    try {
      rules = await listProcedureRules();
    } catch (err) {
      listEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      return;
    }
    if (rules.length === 0) {
      listEl.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon("gavel")}</div>${t("rules_admin_empty")}</div>`;
      return;
    }
    const lang = getLang();
    listEl.innerHTML = `
      <div class="table-wrap">
        <table class="data-table">
          <thead><tr>
            <th>${t("rules_col_rule")}</th><th>${t("rules_col_days")}</th><th>${t("rules_col_tier")}</th>
            <th>${t("rules_col_citation")}</th><th>${t("rules_col_status")}</th><th></th>
          </tr></thead>
          <tbody>
            ${rules
              .map(
                (r) => `
              <tr>
                <td data-label="${t("rules_col_rule")}">
                  <b>${escapeHtml(r.code)}</b> (v${r.version})<br>
                  <span class="text-muted" style="font-size:11.5px;">${escapeHtml(r.trigger_procedure_code)} → ${escapeHtml(r.expected_procedure_code)}</span>
                </td>
                <td data-label="${t("rules_col_days")}">${r.deadline_days} (${r.day_basis})</td>
                <td data-label="${t("rules_col_tier")}"><span class="badge ${tierBadgeClass(r.source_tier)}">${t("proc_tier_" + r.source_tier)}</span></td>
                <td data-label="${t("rules_col_citation")}" style="max-width:260px;">
                  <span style="font-size:12px;">${escapeHtml(r.legal_citation || "—")}</span>
                  ${r.notes ? `<div class="text-muted" style="font-size:11px;margin-top:4px;">${escapeHtml(r.notes)}</div>` : ""}
                </td>
                <td data-label="${t("rules_col_status")}">
                  ${r.is_enabled
                    ? `<span class="badge badge-success">${t("rules_status_enabled")}</span><br><span class="text-muted" style="font-size:11px;">${t("rules_verified_by")}: ${escapeHtml((lang === "ar" ? r.verified_by_name_ar : r.verified_by_name_en) || "—")}</span>`
                    : `<span class="badge badge-muted">${t("rules_status_disabled")}</span>`}
                </td>
                <td data-label="">
                  ${mayVerify
                    ? r.is_enabled
                      ? `<button class="btn btn-outline btn-sm" data-disable="${r.id}">${icon("ban")} ${t("rules_disable")}</button>`
                      : `<button class="btn btn-accent btn-sm" data-verify="${r.id}">${icon("check")} ${t("rules_verify")}</button>`
                    : ""}
                </td>
              </tr>`,
              )
              .join("")}
          </tbody>
        </table>
      </div>
    `;

    listEl.querySelectorAll("[data-disable]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          await disableProcedureRule(Number(btn.getAttribute("data-disable")));
          toast(t("rules_disabled_success"), "success");
          await refresh();
        } catch (err) {
          toast(err.message, "error");
          btn.disabled = false;
        }
      });
    });
    listEl.querySelectorAll("[data-verify]").forEach((btn) => {
      btn.addEventListener("click", () => openVerifyDialog(Number(btn.getAttribute("data-verify")), refresh));
    });
  }

  await refresh();
}

function tierBadgeClass(tier) {
  const map = {
    official_verified: "badge-success",
    official_inferred: "badge-info",
    firm_entered: "badge-muted",
    ai_suggested: "badge-warning",
    unverified: "badge-warning",
  };
  return map[tier] || "badge-muted";
}

function openVerifyDialog(ruleId, onDone) {
  const overlay = openModal(t("rules_verify"), `
    <p class="text-muted">${t("rules_verify_warning")}</p>
    <div class="form-group" style="display:flex;align-items:center;gap:8px;">
      <input type="checkbox" id="verify-confirm" style="width:auto;"/>
      <label for="verify-confirm" style="margin:0;">${t("rules_verify_checkbox")}</label>
    </div>
    <div class="form-group">
      <label>${t("rules_verify_notes")}</label>
      <textarea id="verify-notes" rows="2"></textarea>
    </div>
    <button class="btn btn-accent btn-block" id="verify-submit">${icon("check")} ${t("rules_verify")}</button>
  `);
  overlay.querySelector("#verify-submit").addEventListener("click", async () => {
    const confirmed = overlay.querySelector("#verify-confirm").checked;
    const notes = overlay.querySelector("#verify-notes").value.trim() || null;
    if (!confirmed) { toast(t("rules_verify_must_check"), "error"); return; }
    try {
      await verifyProcedureRule(ruleId, true, notes);
      toast(t("rules_verified_success"), "success");
      closeModal();
      await onDone();
    } catch (err) {
      toast(err.message, "error");
    }
  });
}
