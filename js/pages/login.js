import { t } from "../i18n.js";
import { login, getCurrentUser } from "../auth.js";
import { icon, brandMark } from "../ui.js";

/**
 * The login screen's background photograph is preloaded only when the login
 * screen is what will render. It used to be a static <link rel="preload">
 * in index.html, i.e. on every page -- so every signed-in page logged the
 * browser warning "preloaded ... but not used within a few seconds".
 * Removed again once the app shell renders (app.js::renderShell).
 */
const BG_PRELOAD_ID = "login-bg-preload";

export function ensureBackgroundPreload() {
  if (document.getElementById(BG_PRELOAD_ID)) return;
  const link = document.createElement("link");
  link.id = BG_PRELOAD_ID;
  link.rel = "preload";
  link.as = "image";
  link.href = "/assets/background.jpg";
  link.fetchPriority = "high";
  document.head.appendChild(link);
}

export function removeBackgroundPreload() {
  document.getElementById(BG_PRELOAD_ID)?.remove();
}

// Runs when app.js first imports this module, before boot() renders
// anything: the earliest point this module can know the login screen is
// coming (no signed-in user).
if (!getCurrentUser()) ensureBackgroundPreload();

export async function render(root, onSuccess) {
  // Also covers reaching the login screen later: logout, idle sign-out.
  ensureBackgroundPreload();
  root.innerHTML = `
    <div class="login-screen">
      <div class="login-orb orb-1"></div>
      <div class="login-orb orb-2"></div>
      <div class="login-orb orb-3"></div>
      <div class="login-card">
        <div class="login-brand">
          <div>
            ${brandMark()}
            <h1>${t("app_name")}</h1>
            <p>${t("firm_name")}</p>
          </div>
          <div>
            <p style="font-size:12.5px;">© ${new Date().getFullYear()} ASLG — ${t("login_subtitle")}</p>
          </div>
        </div>
        <div class="login-form-wrap">
          <h2 class="mt-0">${t("login_title")}</h2>
          <p class="text-muted" style="margin-top:-6px;">${t("login_subtitle")}</p>
          <div class="login-error-box" id="login-error">${t("login_error")}</div>
          <form id="login-form">
            <div class="form-group" id="fg-username">
              <label>${t("username")}</label>
              <input id="username" autocomplete="username"/>
              <div class="field-error">${t("required")}</div>
            </div>
            <div class="form-group" id="fg-password">
              <label>${t("password")}</label>
              <input id="password" type="password" autocomplete="current-password"/>
              <div class="field-error">${t("required")}</div>
            </div>
            <button class="btn btn-primary btn-block" type="submit">${icon("right-to-bracket")} ${t("login_btn")}</button>
          </form>
        </div>
      </div>
    </div>
  `;

  const errorBox = root.querySelector("#login-error");
  const form = root.querySelector("#login-form");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const usernameEl = root.querySelector("#username");
    const passwordEl = root.querySelector("#password");
    let valid = true;
    [usernameEl, passwordEl].forEach((el) => {
      const fg = el.closest(".form-group");
      if (!el.value.trim()) { fg.classList.add("invalid"); valid = false; }
      else fg.classList.remove("invalid");
    });
    if (!valid) return;

    errorBox.classList.remove("show");
    try {
      const user = await login(usernameEl.value.trim(), passwordEl.value);
      onSuccess(user);
    } catch {
      errorBox.classList.add("show");
    }
  });
}
