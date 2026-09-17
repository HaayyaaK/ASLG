/**
 * Idle session handling.
 *
 * Two separate goals, deliberately not conflated:
 *
 *   1. A user who walks away from an unlocked machine should not leave a
 *      live legal-case session open on screen. This firm's data includes
 *      client civil IDs, case strategy notes and documents.
 *   2. A user who is actively working must NEVER be interrupted. That rules
 *      out a fixed "log out N minutes after login" rule — the timer has to
 *      measure real inactivity.
 *
 * Lives here rather than in a page module because "idle" means *no user
 * input*, not *no navigation*. A per-page timer would reset on every route
 * change (so someone clicking between pages for hours is never idle, which is
 * right) but would also restart from zero when a page re-renders, and would
 * have to be duplicated in all eleven page modules. `js/app.js` owns the
 * session lifecycle, so it starts and stops this.
 */

import { refreshSession, setSession } from "./api.js";
import { t } from "./i18n.js";
import { escapeHtml, icon } from "./ui.js";

/** Log the user out after this much continuous inactivity. */
export const IDLE_LOGOUT_MS = 15 * 60 * 1000;
/** Show the "you're about to be signed out" warning this long after the last
 *  activity — i.e. two minutes before the logout above. */
export const IDLE_WARNING_MS = 13 * 60 * 1000;
/**
 * How often the deadline is checked.
 *
 * The check is a wall-clock comparison against `lastActivity` rather than a
 * single long `setTimeout`, because a laptop that sleeps does not reliably
 * fire pending timers on wake: a `setTimeout(15min)` armed before a two-hour
 * sleep can resolve immediately, late, or at the wrong moment depending on
 * the browser. Polling and comparing `Date.now()` gives the correct answer in
 * every one of those cases, and at this interval costs nothing.
 */
const TICK_MS = 15 * 1000;

/** Activity is cheap to observe but expensive to act on, so a burst of
 *  mousemove/scroll events only updates a timestamp. `pointerdown` rather
 *  than `mousemove` for the primary signal: a mouse nudged by a passing
 *  cable is not a person working. */
const ACTIVITY_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart", "visibilitychange"];

let lastActivity = Date.now();
let tickId = null;
let warningEl = null;
let onLogout = null;
let listening = false;

function markActive() {
  // Ignored while the warning is up — see showWarning() for why this guard
  // is what makes the whole feature work rather than silently cancel itself.
  if (warningEl) return;
  lastActivity = Date.now();
}

function addActivityListeners() {
  if (listening) return;
  // `capture: true` so events are seen even when a modal stops propagation,
  // and `passive: true` so observing scroll/touch never delays it.
  ACTIVITY_EVENTS.forEach((evt) =>
    document.addEventListener(evt, markActive, { capture: true, passive: true })
  );
  listening = true;
}

function removeActivityListeners() {
  if (!listening) return;
  ACTIVITY_EVENTS.forEach((evt) =>
    document.removeEventListener(evt, markActive, { capture: true })
  );
  listening = false;
}

/**
 * Starts (or restarts) idle tracking for a signed-in session.
 *
 * @param {() => void} logoutFn called when the idle limit is reached; the
 *   caller owns what logging out actually means (app.js passes its own
 *   doLogout so the audit-trail call and page teardown still happen).
 */
export function startIdleTimer(logoutFn) {
  stopIdleTimer();
  onLogout = logoutFn;
  lastActivity = Date.now();
  addActivityListeners();
  tickId = setInterval(tick, TICK_MS);
}

export function stopIdleTimer() {
  if (tickId) clearInterval(tickId);
  tickId = null;
  removeActivityListeners();
  dismissWarning();
  onLogout = null;
}

function tick() {
  const idleFor = Date.now() - lastActivity;
  if (idleFor >= IDLE_LOGOUT_MS) {
    const logoutFn = onLogout;
    stopIdleTimer();
    if (logoutFn) logoutFn({ reason: "idle" });
    return;
  }
  if (idleFor >= IDLE_WARNING_MS && !warningEl) showWarning();
  if (warningEl) updateCountdown(idleFor);
}

/**
 * The warning dialog.
 *
 * Built directly rather than through ui.js's openModal() for two reasons:
 * openModal() closes on Escape and on a backdrop click, and it replaces any
 * modal already on screen. Neither is right here — this must not be
 * dismissable by an accidental keypress, and it must not destroy a form the
 * user has half-filled in a modal behind it.
 *
 * Crucially, `markActive` is inert while this is showing. Without that, the
 * very act of moving the mouse toward the "Stay signed in" button would reset
 * the idle clock and dismiss the warning before it could be answered — the
 * feature would appear to work and in fact never log anyone out.
 */
function showWarning() {
  warningEl = document.createElement("div");
  warningEl.className = "idle-warning-overlay";
  warningEl.setAttribute("role", "alertdialog");
  warningEl.setAttribute("aria-modal", "true");
  warningEl.setAttribute("aria-labelledby", "idle-warning-title");
  warningEl.innerHTML = `
    <div class="idle-warning-box">
      <div class="idle-warning-icon">${icon("clock")}</div>
      <h3 id="idle-warning-title">${escapeHtml(t("idle_warning_title"))}</h3>
      <p class="text-muted">${escapeHtml(t("idle_warning_body"))}</p>
      <p class="idle-warning-countdown"><span id="idle-countdown">2:00</span></p>
      <div class="idle-warning-actions">
        <button class="btn btn-primary" id="idle-stay">${escapeHtml(t("idle_stay_signed_in"))}</button>
        <button class="btn btn-outline" id="idle-logout-now">${escapeHtml(t("idle_sign_out_now"))}</button>
      </div>
    </div>`;
  document.body.appendChild(warningEl);

  warningEl.querySelector("#idle-stay").addEventListener("click", staySignedIn);
  warningEl.querySelector("#idle-logout-now").addEventListener("click", () => {
    const logoutFn = onLogout;
    stopIdleTimer();
    if (logoutFn) logoutFn({ reason: "manual" });
  });
  // Focus the safe action so Enter/Space keeps the session rather than ending
  // it, and so a keyboard user is not stranded outside the dialog.
  warningEl.querySelector("#idle-stay").focus();
}

function updateCountdown(idleFor) {
  const el = warningEl?.querySelector("#idle-countdown");
  if (!el) return;
  const remaining = Math.max(0, IDLE_LOGOUT_MS - idleFor);
  const mins = Math.floor(remaining / 60000);
  const secs = Math.floor((remaining % 60000) / 1000);
  el.textContent = `${mins}:${String(secs).padStart(2, "0")}`;
}

function dismissWarning() {
  if (warningEl) warningEl.remove();
  warningEl = null;
}

/**
 * Extends the session for real, not just on the client.
 *
 * GET /api/auth/me re-issues the JWT with a fresh expiry (see
 * backend/app/routers/auth.py). Resetting only the local timer would leave
 * the user working against a token that still expires on its original
 * schedule, and they would be bounced to the login screen mid-task — the
 * exact failure this whole change exists to remove.
 *
 * If the renewal call fails the timer is still reset: the network being
 * briefly unavailable is not a reason to throw away the user's work. The
 * existing 401 handling in api.js remains the backstop if the token really
 * has expired.
 */
async function staySignedIn() {
  dismissWarning();
  lastActivity = Date.now();
  try {
    const data = await refreshSession();
    setSession(data.access_token, data.user, data.permissions);
  } catch {
    // Non-fatal by design — see the note above.
  }
}
