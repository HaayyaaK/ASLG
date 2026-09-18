import { t, getLang } from "./i18n.js";
import { icon, escapeHtml } from "./ui.js";

/**
 * Official Kuwait government portals a lawyer actually needs day to day.
 *
 * Moved here from js/pages/search.js in Sub-phase 3.3 (Sept 2026 overhaul,
 * Task 3): the panel now renders on the Dashboard, not the Official Search
 * Engine page, so its data and render function needed a home neither page
 * module owns -- this file is that home, imported by dashboard.js only.
 *
 * These are the real published domains -- nothing here is invented, and each
 * opens the genuine site in a new tab so the user never loses their place in
 * the case they were working on.
 */
export const KUWAIT_WEBSITES = [
  {
    url: "https://www.moj.gov.kw",
    name_en: "Ministry of Justice", name_ar: "وزارة العدل",
    services_en: "Cases, hearings, real-estate registration, lawyer services",
    services_ar: "القضايا والجلسات والتسجيل العقاري وخدمات المحامين",
    benefit_en: "Follow up on cases and complete judicial transactions",
    benefit_ar: "متابعة القضايا وإنجاز المعاملات القضائية",
    icon: "scale-balanced",
  },
  {
    // The commonly-quoted host "tawtheeq.moj.gov.kw" does not resolve (DNS
    // NXDOMAIN as of this build), so linking it would give lawyers a dead
    // link. Tawtheeq's power-of-attorney services are reached through the
    // Ministry of Justice's e-services portal, which is verified reachable.
    url: "https://eservices.moj.gov.kw",
    name_en: "E-Services of MOJ", name_ar: "الخدمات الإلكترونية للعدل",
    services_en: "Issuing and cancelling powers of attorney, verifying validity",
    services_ar: "إصدار وإلغاء الوكالات والتحقق من صلاحيتها",
    benefit_en: "Handle power-of-attorney procedures electronically",
    benefit_ar: "تسهيل إجراءات الوكالات إلكترونياً",
    icon: "file-signature",
  },
  {
    url: "https://www.paci.gov.kw",
    name_en: "Public Authority for Civil Information", name_ar: "الهيئة العامة للمعلومات المدنية",
    services_en: "Civil ID data",
    services_ar: "بيانات البطاقة المدنية",
    benefit_en: "Verify a client's identity",
    benefit_ar: "التحقق من هوية العملاء",
    icon: "id-card",
  },
  {
    url: "https://www.csc.gov.kw",
    name_en: "Civil Service Commission", name_ar: "ديوان الخدمة المدنية",
    services_en: "Regulations and government jobs",
    services_ar: "اللوائح والوظائف الحكومية",
    benefit_en: "Administrative and legal reference",
    benefit_ar: "مرجع إداري وقانوني",
    icon: "building-columns",
  },
];

/**
 * Button layout (Sub-phase 3.4 correction, superseding 3.3's cover-image
 * card): reuses `.qa-action-btn` -- the exact class the Dashboard's Quick
 * Actions row above this panel already uses -- rather than a parallel style,
 * so the two rows can't visually drift apart later. Each site's service
 * description becomes the button's `title` tooltip rather than visible body
 * text, since a qa-action-btn is icon + label only; the destination URL is
 * unchanged and still opens in a new tab.
 */
export function usefulWebsitesPanel() {
  const lang = getLang();
  return `
    <div class="panel" id="kuwait-websites-panel">
      <div class="panel-header"><h3>${icon("link")} ${t("useful_websites")}</h3></div>
      <div class="panel-body">
        <p class="text-muted mt-0">${t("useful_websites_hint")}</p>
        <div class="qa-actions-row">
          ${KUWAIT_WEBSITES.map((s) => {
            const name = lang === "ar" ? s.name_ar : s.name_en;
            const desc = lang === "ar" ? s.services_ar : s.services_en;
            return `
            <a class="qa-action-btn" href="${s.url}" target="_blank" rel="noopener noreferrer"
               aria-label="${escapeHtml(name)}" title="${escapeHtml(`${name} — ${desc}`)}">
              ${icon(s.icon)}<span class="btn-label">${escapeHtml(name)}</span>
            </a>`;
          }).join("")}
        </div>
      </div>
    </div>`;
}
