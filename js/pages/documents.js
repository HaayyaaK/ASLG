import { t, getLang } from "../i18n.js";
import {
  listCases, listDocuments, uploadDocument, deleteDocument, reviewDocument, fetchDocumentBlobUrl,
  grantUploadAccess, myUploadAccess, getPermission,
} from "../api.js";
import { formatBytes, formatDate, openModal, closeModal, toast, escapeHtml, icon, routeFilter } from "../ui.js";
import { printRecord, printButton } from "../print.js";

const ALLOWED_TYPES = ["pdf", "docx", "doc", "jpg", "jpeg", "png"];
const MAX_SIZE = 25 * 1024 * 1024;

// Which case accordion sections are expanded, keyed by case id. Set once
// (lazily, to collapsed) the first time a case is rendered, then only ever
// changed by an explicit user toggle — a later refreshAccordion() (e.g.
// after an upload/delete) must never silently re-open or re-close a section
// the user already decided about. Cleared in destroy(), so each visit to the
// page starts with every section collapsed.
let caseOpenState = new Map();

export function destroy() {
  caseOpenState = new Map();
}

export async function render(container, user) {
  const perm = getPermission("documents");
  const isStaffUploader = perm === "full" || perm === "edit";
  // Reviewing is deliberately narrower than uploading/deleting: only Admin and
  // Lawyer hold documents="full". The server enforces the same rule
  // independently (require_module("documents", "full")); this only decides
  // whether the buttons render.
  const canReview = perm === "full";
  const isClient = perm === "own";
  const lang = getLang();

  container.innerHTML = `
    <div class="flex-between" style="margin-bottom:8px;">
      <h2 class="mt-0">${t("documents_title")}</h2>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        ${printButton("docs-print")}
        ${isStaffUploader ? `<button class="btn btn-accent btn-sm" id="grant-access-btn" title="${t("grant_upload_access")}">${icon("unlock-keyhole")} ${t("grant_upload_access")}</button>` : ""}
      </div>
    </div>
    <div id="client-access-banner"></div>
    <div class="panel">
      <div class="panel-header"><h3>${t("nav_documents")}</h3></div>
      <div class="panel-body" id="docs-accordion"><p class="text-muted">${icon("spinner", "fa-spin")}</p></div>
    </div>
  `;

  let cases = [];

  // The rows currently on screen, so Print composes the register from exactly
  // what is displayed — including the Dashboard "pending" filter if the user
  // arrived through that card.
  let visibleDocs = [];

  // Wired before the first `await` below, so the button is live as soon as it
  // is visible; it closes over `cases`/`visibleDocs` and therefore always
  // prints whatever has loaded by the time it is clicked.
  //
  // The register, not the files: a printed index of what exists, who it
  // belongs to and where each item stands in review. Printing a document's
  // *contents* is the browser's job from Preview, and is not duplicated here.
  container.querySelector("#docs-print").addEventListener("click", () => {
    if (visibleDocs.length === 0) {
      toast(t("print_nothing_to_print"), "info");
      return;
    }
    const caseLabel = new Map(cases.map((c) => [c.id, `${c.case_number}/${c.case_year}`]));
    const statusLabel = { pending: "doc_status_pending", approved: "doc_status_approved", rejected: "doc_status_rejected" };
    printRecord({
      title: t("print_documents_register"),
      subtitle: t("documents_title"),
      meta: [
        { label: t("print_filters_applied"), value: routeFilter() === "pending" ? t("doc_status_pending") : t("print_none") },
      ],
      sections: [
        {
          heading: t("nav_documents"),
          table: {
            columns: [t("linked_case"), t("file_name"), t("file_size"), t("print_status"), t("uploaded_at")],
            rows: visibleDocs.map((d) => [
              caseLabel.get(d.case_id) || "—",
              d.file_name,
              formatBytes(d.file_size),
              t(statusLabel[d.status] || "doc_status_pending"),
              formatDate(d.uploaded_at, { time: true }),
            ]),
          },
        },
      ],
    });
  });

  try {
    cases = await listCases();
  } catch {
    // fall through with an empty case list; the accordion will just show none
  }

  if (isClient) {
    await renderClientAccessBanner();
  }

  async function renderClientAccessBanner() {
    const bannerEl = container.querySelector("#client-access-banner");
    let grants = [];
    try {
      grants = await myUploadAccess();
    } catch {
      grants = [];
    }

    if (grants.length > 0) {
      // A client can hold upload access to more than one case at once (a
      // temporary grant on one, a standing link on another, or several of
      // either) — one banner + dropzone per grant, not just the first.
      bannerEl.innerHTML = grants
        .map(
          (g, idx) => `
        <div class="upload-grant-banner">
          ${icon("unlock-keyhole")}
          <div>
            <div><b>${t("upload_access_granted")}</b> — ${g.case_number}</div>
            <div class="ug-expiry">${
              g.source === "link" && !g.expires_at
                ? t("standing_upload_access")
                : `${t("expires_at")}: ${formatDate(g.expires_at, { time: true })}`
            }</div>
          </div>
        </div>
        <div class="dropzone" id="client-dropzone-${idx}">
          <div class="dz-icon">${icon("cloud-arrow-up")}</div>
          <div style="font-weight:700;">${t("drag_drop")}</div>
          <div class="text-muted" style="font-size:12.5px;margin-top:6px;">${t("supported_formats")}</div>
          <input type="file" id="client-file-input-${idx}" hidden accept=".pdf,.docx,.doc,.jpg,.jpeg,.png"/>
        </div>
        <div id="client-upload-progress-${idx}" style="margin-bottom:20px;"></div>`,
        )
        .join("");
      grants.forEach((g, idx) => wireClientUpload(g.case_id, idx));
    } else {
      bannerEl.innerHTML = `
        <div class="upload-blocked-banner">
          ${icon("lock")}
          <div>${t("upload_blocked_default")}</div>
        </div>
      `;
    }
  }

  function wireClientUpload(caseId, idx) {
    const dropzone = container.querySelector(`#client-dropzone-${idx}`);
    const fileInput = container.querySelector(`#client-file-input-${idx}`);
    const progressList = container.querySelector(`#client-upload-progress-${idx}`);
    if (!dropzone) return;

    const onDone = async () => {
      await refreshAccordion();
      await renderClientAccessBanner();
    };
    dropzone.addEventListener("click", () => fileInput.click());
    dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", (e) => {
      e.preventDefault();
      dropzone.classList.remove("dragover");
      if (e.dataTransfer.files[0]) startUpload(e.dataTransfer.files[0], caseId, progressList, onDone);
    });
    fileInput.addEventListener("change", () => {
      if (fileInput.files[0]) startUpload(fileInput.files[0], caseId, progressList, onDone);
      fileInput.value = "";
    });
  }

  async function refreshAccordion() {
    const accEl = container.querySelector("#docs-accordion");
    // Gone if the user navigated away while listDocuments() was in flight.
    if (!accEl) return;
    let docs;
    try {
      docs = await listDocuments();
    } catch (err) {
      accEl.innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
      return;
    }

    // Arriving from the Dashboard's "Pending documents" card: show only the
    // documents that card counted, so the list matches the number clicked.
    if (routeFilter() === "pending") docs = docs.filter((d) => d.status === "pending");
    visibleDocs = docs;

    const docsByCase = new Map();
    docs.forEach((d) => {
      if (!docsByCase.has(d.case_id)) docsByCase.set(d.case_id, []);
      docsByCase.get(d.case_id).push(d);
    });

    // Every case the user can see gets a section — including ones with zero
    // documents yet, since that's exactly where "Add New Document" needs to
    // be discoverable. Cases with documents already sort first (more useful
    // by default); every section starts collapsed.
    const casesWithDocs = cases.filter((c) => docsByCase.has(c.id));
    const casesWithoutDocs = cases.filter((c) => !docsByCase.has(c.id));
    const orderedCases = [...casesWithDocs, ...casesWithoutDocs];

    if (orderedCases.length === 0) {
      accEl.innerHTML = `<div class="empty-state"><div class="empty-icon">${icon("file-lines")}</div>${t("no_results")}</div>`;
      return;
    }

    accEl.innerHTML = orderedCases.map((c) => renderCaseGroup(c, docsByCase.get(c.id) || [], lang, isStaffUploader)).join("");
    wireAccordionEvents(accEl, docsByCase);
  }

  function wireAccordionEvents(accEl, docsByCase) {
    accEl.querySelectorAll("[data-toggle-case]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const caseId = Number(btn.getAttribute("data-toggle-case"));
        const group = accEl.querySelector(`[data-case-group="${caseId}"]`);
        const body = accEl.querySelector(`#doc-case-body-${caseId}`);
        const willOpen = body.hasAttribute("hidden");
        body.toggleAttribute("hidden", !willOpen);
        btn.setAttribute("aria-expanded", String(willOpen));
        group.classList.toggle("open", willOpen);
        caseOpenState.set(caseId, willOpen);
      });
    });

    accEl.querySelectorAll("[data-add-case]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const caseId = Number(btn.getAttribute("data-add-case"));
        const c = cases.find((x) => x.id === caseId);
        const label = c ? `${c.case_number}/${c.case_year}` : "";
        openUploadModal(caseId, label, refreshAccordion);
      });
    });

    accEl.querySelectorAll("[data-preview]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const caseId = Number(btn.getAttribute("data-case-id"));
        const doc = (docsByCase.get(caseId) || []).find((d) => d.id === Number(btn.getAttribute("data-preview")));
        previewDocument(doc);
      });
    });
    accEl.querySelectorAll("[data-approve]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        // Guard against a double-click firing two requests: the second would
        // be a no-op server-side anyway, but disabling makes that visible.
        btn.disabled = true;
        try {
          await reviewDocument(Number(btn.getAttribute("data-approve")), "approved");
          toast(t("doc_approved_msg"), "success");
          refreshAccordion();
        } catch (err) {
          btn.disabled = false;
          toast(err.message, "error");
        }
      });
    });
    accEl.querySelectorAll("[data-reject]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        openRejectModal(
          Number(btn.getAttribute("data-reject")),
          btn.getAttribute("data-name") || "",
          refreshAccordion
        );
      });
    });
    accEl.querySelectorAll("[data-delete]").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        try {
          await deleteDocument(Number(btn.getAttribute("data-delete")));
          toast(getLang() === "ar" ? "تم حذف المستند" : "Document deleted", "success");
          refreshAccordion();
        } catch (err) {
          toast(err.message, "error");
        }
      });
    });
  }

  function renderCaseGroup(c, docs, lang, canAdd) {
    // Collapsed by default: every section starts closed and the user opens
    // what they need. A section they toggle keeps that state for the rest of
    // this visit (caseOpenState, see its comment at the top of this file).
    if (!caseOpenState.has(c.id)) caseOpenState.set(c.id, false);
    const isOpen = caseOpenState.get(c.id);
    const parties = (lang === "ar" ? c.parties_ar : c.parties_en) || c.parties_ar || "";
    const caseNumber = `${c.case_number}/${c.case_year}`;
    const countLabel = docs.length === 1 ? t("documents_count_one") : `${docs.length} ${t("documents_count_other")}`;
    // The header shows only the case number (the compact, scannable
    // identifier); the parties moved into the body. The accessible name
    // keeps both, starting with the visible number (WCAG 2.5.3 label in
    // name), so a collapsed row is never announced as a bare number.
    const toggleName = parties ? `${caseNumber} — ${parties}` : caseNumber;

    return `
      <div class="doc-case-group${isOpen ? " open" : ""}" data-case-group="${c.id}">
        <div class="doc-case-header">
          <button type="button" class="doc-case-toggle" data-toggle-case="${c.id}" aria-expanded="${isOpen}" aria-controls="doc-case-body-${c.id}"
                  aria-label="${escapeHtml(toggleName)}" title="${escapeHtml(toggleName)}">
            <span class="doc-case-chevron" aria-hidden="true">${icon("chevron-right")}</span>
            <span class="doc-case-number">${caseNumber}</span>
          </button>
          <span class="badge badge-muted doc-case-count" title="${countLabel}" aria-label="${countLabel}">${docs.length}</span>
          ${canAdd ? `<button type="button" class="btn btn-outline btn-sm" data-add-case="${c.id}" title="${t("documents_add_to_case")}" aria-label="${t("documents_add_to_case")}">${icon("plus")}</button>` : ""}
        </div>
        <div class="doc-case-body" id="doc-case-body-${c.id}" ${isOpen ? "" : "hidden"}>
          ${parties ? `<p class="doc-case-title">${escapeHtml(parties)}</p>` : ""}
          ${docs.length === 0 ? renderEmptyCase(c, canAdd) : docs.map((d) => renderDocItem(d, c.id, canAdd)).join("")}
        </div>
      </div>`;
  }

  function renderEmptyCase(c, canAdd) {
    return `
      <div class="empty-state" style="padding:20px;">
        <div class="empty-icon">${icon("folder-open")}</div>
        ${t("documents_no_documents_yet")}
        ${canAdd ? `<div style="margin-top:12px;"><button type="button" class="btn btn-primary btn-sm" data-add-case="${c.id}">${icon("plus")} ${t("documents_add_new")}</button></div>` : ""}
      </div>`;
  }

  // Three real states, not two. The previous version was an if/else that
  // rendered anything not "pending" as "Approved" — so a rejected document
  // would have displayed as approved, which is the worst possible way to be
  // wrong about a document.
  function statusBadge(status) {
    const map = {
      pending: ["badge-warning", "doc_status_pending"],
      approved: ["badge-success", "doc_status_approved"],
      rejected: ["badge-danger", "doc_status_rejected"],
    };
    const [cls, key] = map[status] || map.pending;
    return `<span class="badge ${cls}">${t(key)}</span>`;
  }

  function renderDocItem(d, caseId, canDelete) {
    // Reviewers only ever see the action that would change something: no
    // "Approve" on an already-approved document, so a click always means a
    // real state change and can never produce a duplicate notification.
    const reviewBtns = canReview
      ? `${d.status !== "approved" ? `<button type="button" class="btn btn-outline btn-sm doc-approve" data-approve="${d.id}" title="${t("doc_approve")}" aria-label="${t("doc_approve")}">${icon("check")}</button>` : ""}
         ${d.status !== "rejected" ? `<button type="button" class="btn btn-outline btn-sm doc-reject" data-reject="${d.id}" data-name="${escapeHtml(d.file_name)}" title="${t("doc_reject")}" aria-label="${t("doc_reject")}">${icon("xmark")}</button>` : ""}`
      : "";
    return `
      <div class="hearing-row doc-item">
        <div class="hearing-info">
          <div class="doc-item-name">${icon("paperclip")} ${escapeHtml(d.file_name)} ${statusBadge(d.status)}</div>
          <div class="hearing-meta">${formatBytes(d.file_size)} • ${formatDate(d.uploaded_at)}</div>
        </div>
        <div class="doc-item-actions">
          <button type="button" class="btn btn-outline btn-sm" data-preview="${d.id}" data-case-id="${caseId}" title="${t("preview")}" aria-label="${t("preview")}">${icon("eye")}</button>
          ${reviewBtns}
          ${canDelete ? `<button type="button" class="btn btn-danger btn-sm" data-delete="${d.id}" title="${t("delete")}" aria-label="${t("delete")}">${icon("trash")}</button>` : ""}
        </div>
      </div>`;
  }

  await refreshAccordion();

  const grantBtn = container.querySelector("#grant-access-btn");
  if (grantBtn) {
    grantBtn.addEventListener("click", () => openGrantModal(cases));
  }
}

/**
 * Rejection asks for a reason; approval does not.
 *
 * The reason is optional and is not stored on the document row — the app's
 * database account cannot add a column — so it goes where it is actually
 * retrievable: the uploader's notification and the Activity Log entry.
 */
function openRejectModal(docId, fileName, onDone) {
  const overlay = openModal(`${t("doc_review_title")} — ${escapeHtml(fileName)}`, `
    <p class="text-muted mt-0">${t("doc_review_hint")}</p>
    <div class="form-group">
      <label>${t("doc_reject_reason")}</label>
      <textarea id="reject-reason" rows="3" maxlength="300"
        style="width:100%;padding:11px 14px;border:1px solid var(--color-border);border-radius:6px;"
        placeholder="${t("doc_reject_reason_placeholder")}"></textarea>
    </div>
    <button class="btn btn-danger btn-block" id="reject-submit">${icon("xmark")} ${t("doc_reject")}</button>
  `);

  const submit = overlay.querySelector("#reject-submit");
  submit.addEventListener("click", async () => {
    submit.disabled = true;
    try {
      const reason = overlay.querySelector("#reject-reason").value.trim();
      await reviewDocument(docId, "rejected", reason || null);
      closeModal(overlay);
      toast(t("doc_rejected_msg"), "success");
      onDone();
    } catch (err) {
      submit.disabled = false;
      toast(err.message, "error");
    }
  });
}

function openUploadModal(caseId, caseLabel, onDone) {
  const overlay = openModal(`${t("documents_add_to_case")} — ${escapeHtml(caseLabel)}`, `
    <div class="dropzone" id="modal-dropzone">
      <div class="dz-icon">${icon("cloud-arrow-up")}</div>
      <div style="font-weight:700;">${t("drag_drop")}</div>
      <div class="text-muted" style="font-size:12.5px;margin-top:6px;">${t("supported_formats")}</div>
      <input type="file" id="modal-file-input" multiple hidden accept=".pdf,.docx,.doc,.jpg,.jpeg,.png"/>
    </div>
    <div id="modal-upload-progress"></div>
  `);

  const dropzone = overlay.querySelector("#modal-dropzone");
  const fileInput = overlay.querySelector("#modal-file-input");
  const progressList = overlay.querySelector("#modal-upload-progress");

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("dragover");
    Array.from(e.dataTransfer.files).forEach((file) => startUpload(file, caseId, progressList, onDone));
  });
  fileInput.addEventListener("change", () => {
    Array.from(fileInput.files).forEach((file) => startUpload(file, caseId, progressList, onDone));
    fileInput.value = "";
  });
}

function startUpload(file, caseId, progressList, onDone) {
  const ext = file.name.split(".").pop().toLowerCase();
  if (!ALLOWED_TYPES.includes(ext) || file.size > MAX_SIZE) {
    toast(t("invalid_file"), "error");
    return;
  }

  const row = document.createElement("div");
  row.className = "upload-item";
  row.innerHTML = `
    <span>${icon("file")}</span>
    <div style="flex:1;">
      <div style="font-size:13px;font-weight:600;">${escapeHtml(file.name)}</div>
      <div style="display:flex;align-items:center;gap:8px;margin-top:4px;">
        <div class="progress-bar"><div class="progress-bar-fill"></div></div>
        <span class="pct text-muted" style="font-size:11.5px;">0%</span>
      </div>
    </div>`;
  progressList.appendChild(row);
  const fill = row.querySelector(".progress-bar-fill");
  const pctLabel = row.querySelector(".pct");

  let pct = 0;
  const tick = setInterval(() => {
    pct = Math.min(pct + Math.random() * 20 + 10, 90);
    fill.style.width = pct + "%";
    pctLabel.textContent = Math.round(pct) + "%";
  }, 150);

  uploadDocument(caseId, file)
    .then(() => {
      clearInterval(tick);
      fill.style.width = "100%";
      pctLabel.textContent = "100%";
      toast(getLang() === "ar" ? "تم رفع الملف بنجاح" : "File uploaded successfully", "success");
      setTimeout(async () => { row.remove(); await onDone(); }, 500);
    })
    .catch((err) => {
      clearInterval(tick);
      toast(err.message, "error");
      row.remove();
    });
}

function openGrantModal(cases) {
  const lang = getLang();
  const overlay = openModal(t("grant_upload_access"), `
    <p class="text-muted mt-0">${t("grant_upload_access_hint")}</p>
    <div class="form-group">
      <label class="required">${t("linked_case")}</label>
      <select id="grant-case" aria-required="true">
        ${cases.map((c) => `<option value="${c.id}">${c.case_number}/${c.case_year} — ${lang === "ar" ? c.parties_ar : c.parties_en}</option>`).join("")}
      </select>
    </div>
    <div class="form-group">
      <label class="required">${t("grant_duration")}</label>
      <select id="grant-duration" aria-required="true">
        <option value="15">15 ${t("minutes")}</option>
        <option value="30">30 ${t("minutes")}</option>
        <option value="60" selected>60 ${t("minutes")}</option>
        <option value="240">4 ${t("hours")}</option>
        <option value="1440">24 ${t("hours")}</option>
      </select>
    </div>
    <button class="btn btn-primary btn-block" id="grant-submit">${icon("unlock-keyhole")} ${t("grant_upload_access")}</button>
  `);

  overlay.querySelector("#grant-submit").addEventListener("click", async () => {
    const caseId = Number(overlay.querySelector("#grant-case").value);
    const minutes = Number(overlay.querySelector("#grant-duration").value);
    try {
      const grant = await grantUploadAccess(caseId, minutes);
      toast(
        `${t("grant_created_msg")} ${lang === "ar" ? grant.client_name_ar : grant.client_name_en} — ${formatDate(grant.expires_at, { time: true })}`,
        "success"
      );
      closeModal();
    } catch (err) {
      toast(err.message, "error");
    }
  });
}

export async function previewDocument(doc) {
  if (!doc) return;
  const isImage = ["jpg", "jpeg", "png"].includes(doc.file_type);
  const body = `<div style="text-align:center;background:#f0f2f5;border-radius:8px;padding:20px;" id="preview-body">
      <div style="font-size:40px;">${icon("spinner", "fa-spin")}</div>
    </div>
    <div style="margin-top:16px;display:flex;gap:8px;justify-content:flex-end;">
      <a class="btn btn-primary btn-sm" id="download-link" style="display:none;">${icon("download")} ${t("download")}</a>
    </div>`;
  const overlay = openModal(`${t("preview")} — ${escapeHtml(doc.file_name)}`, body, { wide: true });

  try {
    const blobUrl = await fetchDocumentBlobUrl(doc.id);
    const previewBody = overlay.querySelector("#preview-body");
    previewBody.innerHTML = isImage
      ? `<img src="${blobUrl}" style="max-width:100%;max-height:60vh;border-radius:6px;" alt="${escapeHtml(doc.file_name)}"/>`
      : `<embed src="${blobUrl}" type="application/pdf" style="width:100%;height:60vh;border-radius:6px;" />`;
    const link = overlay.querySelector("#download-link");
    link.href = blobUrl;
    link.download = doc.file_name;
    link.style.display = "";
  } catch (err) {
    overlay.querySelector("#preview-body").innerHTML = `<p class="text-muted">${escapeHtml(err.message)}</p>`;
  }
}
