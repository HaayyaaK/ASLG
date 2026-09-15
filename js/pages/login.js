import { t } from "../i18n.js";
import { login } from "../auth.js";
import { icon, brandMark } from "../ui.js";

export async function render(root, onSuccess) {
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
