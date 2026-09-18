const API_BASE = "/api";
const SESSION_KEY = "aslg_session";

function getSession() {
  const raw = sessionStorage.getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function setSession(token, user, permissions) {
  sessionStorage.setItem(SESSION_KEY, JSON.stringify({ token, user, permissions }));
}

export function clearSession() {
  sessionStorage.removeItem(SESSION_KEY);
}

export function getCurrentUser() {
  return getSession()?.user ?? null;
}

export function getPermissions() {
  return getSession()?.permissions ?? {};
}

export function getPermission(module) {
  return getPermissions()[module] ?? "none";
}

/**
 * Request timeouts.
 *
 * `fetch` has NO default timeout: a request that never gets a response waits
 * forever, and because every page renders a spinner first and fills it in
 * afterwards, "waits forever" looks exactly like the application has frozen.
 * That is the shape of the freeze this app was reported to have (see
 * `js/idle.js` and the router's error handling in `js/app.js` for the other
 * two halves of the same fix).
 *
 * The trigger is ordinary operation, not a bug: this site's IIS application
 * pool is configured `idleTimeout: 00:20:00` with `idleTimeoutAction: Terminate`,
 * and the Windows event log records the ASLG worker being "shutdown due to
 * inactivity" ten or more times a day. The next request after that has to
 * cold-start Python + uvicorn + SQLAlchemy — measured at ~1.4s just to import
 * the app module, so roughly 2-4s in practice before the first byte.
 *
 * Uploads get their own, far longer budget: MAX_UPLOAD_MB is 25, and a large
 * file on a slow connection legitimately takes minutes. Applying the normal
 * timeout to those would abort perfectly healthy uploads.
 */
const REQUEST_TIMEOUT_MS = 20000;
const UPLOAD_TIMEOUT_MS = 180000;
const COLD_START_RETRY_DELAY_MS = 1200;

/** Error thrown when a request exceeded its own timeout. Typed so callers
 *  (and the router's error state) can tell "the server is slow/unreachable"
 *  apart from "the server said no". */
export class RequestTimeoutError extends Error {
  constructor(message) {
    super(message);
    this.name = "RequestTimeoutError";
    this.isTimeout = true;
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(path, { method = "GET", body, isForm = false, rawResponse = false } = {}) {
  const session = getSession();
  const headers = {};
  if (!isForm) headers["Content-Type"] = "application/json";
  if (session?.token) headers["Authorization"] = `Bearer ${session.token}`;

  const init = {
    method,
    headers,
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  };
  const timeoutMs = isForm ? UPLOAD_TIMEOUT_MS : REQUEST_TIMEOUT_MS;

  let res;
  try {
    res = await fetchWithTimeout(path, init, timeoutMs);
  } catch (err) {
    // Retry ONCE, and ONLY when `fetch` itself rejected rather than timed
    // out. That distinction carries two separate guarantees:
    //
    //   Safety — a rejected `fetch` means no response was ever received, so
    //   the request cannot have been applied server-side and replaying it is
    //   safe for any method, POST included. A request that TIMED OUT may
    //   well have reached the server and been applied; replaying it could
    //   create a duplicate case or a duplicate note, so it never is.
    //
    //   Speed — a refused connection fails in milliseconds, so this retry
    //   costs nothing. Retrying after a timeout was measured end-to-end at
    //   43s before the user saw anything (20s + delay + 20s), and bought
    //   almost nothing: a server that did not answer within 20s is very
    //   unlikely to answer within the next 20s. One timeout, then the error
    //   state with its Retry button, puts the user back in control sooner.
    //
    // This is exactly the cold-start window: IIS tears the worker down after
    // 20 minutes idle, and the connection is refused until uvicorn is
    // listening again.
    if (err.isTimeout) throw err;
    await sleep(COLD_START_RETRY_DELAY_MS);
    res = await fetchWithTimeout(path, init, timeoutMs);
  }

  if (res.status === 401) {
    clearSession();
    location.hash = "";
    location.reload();
    throw new Error("Session expired");
  }

  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      message = data.detail || message;
    } catch {
      // ignore parse failure, keep default message
    }
    throw new Error(message);
  }

  if (rawResponse) return res;
  if (res.status === 204) return null;
  return res.json();
}

/**
 * `fetch` plus an AbortController-backed deadline.
 *
 * The timer is always cleared in `finally`, including on success — leaving it
 * pending would fire an abort against an already-settled controller (harmless)
 * but would also keep a timer alive per request, which on a page that polls
 * would accumulate.
 *
 * An abort surfaces as a DOMException named "AbortError"; it is re-thrown as
 * a RequestTimeoutError so callers never have to know that detail, and so a
 * genuine network failure (fetch's own TypeError) stays distinguishable from
 * a timeout — the retry rule above depends on telling those two apart.
 */
async function fetchWithTimeout(path, init, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal });
  } catch (err) {
    if (err.name === "AbortError") {
      throw new RequestTimeoutError(`Request timed out after ${Math.round(timeoutMs / 1000)}s`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

// ---------------- Auth ----------------
export const loginRequest = (username, password) => request("/auth/login", { method: "POST", body: { username, password } });
export const logoutRequest = () => request("/auth/logout", { method: "POST" });
/**
 * Re-issues the caller's token with a fresh expiry and returns the current
 * user + permissions alongside it (backend/app/routers/auth.py `me`).
 *
 * This is what "Stay logged in" calls, so extending a session is a real
 * server-side extension rather than a client-side timer reset that would
 * leave the JWT quietly expiring underneath the user. Unlike /auth/login it
 * does not touch `last_login_at` and writes no activity-log row, so keeping a
 * session alive never looks like a fresh sign-in in the audit trail. It also
 * returns permissions, so a role change made by an admin takes effect at the
 * next renewal instead of requiring the user to log out and back in.
 */
export const refreshSession = () => request("/auth/me");

// ---------------- Users (Admin) ----------------
export const listUsers = () => request("/users");
export const createUser = (payload) => request("/users", { method: "POST", body: payload });
export const updateUser = (id, payload) => request(`/users/${id}`, { method: "PUT", body: payload });
export const deleteUser = (id) => request(`/users/${id}`, { method: "DELETE" });
export const resetUserPassword = (id, newPassword) => request(`/users/${id}/reset-password`, { method: "POST", body: { new_password: newPassword } });
export const bulkUserAction = (userIds, action, newPassword) => request("/users/bulk", { method: "POST", body: { user_ids: userIds, action, new_password: newPassword } });

// ---------------- Cases ----------------
export const listCases = () => request("/cases");

/**
 * Short shared caches for the lists the hub pages' tabs load (cases,
 * notifications, reminders).
 *
 * Callers of the same list share one in-flight promise and reuse a result
 * younger than 60s -- e.g. the Cases page's two tabs both need the case list,
 * and the search tab used to re-request it on every one of its five sub-tab
 * clicks. Clicking a hub tab invalidates its lists explicitly (see
 * js/hub.js), so the cache only ever serves programmatic navigation.
 *
 * Staleness is bounded two ways: the age limit, and invalidation on every
 * call below that changes a cached list -- so a user never sees a stale
 * result of their own action, only up to 60s of other people's. A failed
 * request is dropped from the cache so the next caller retries instead of
 * inheriting the error.
 */
const LIST_CACHE_MAX_AGE_MS = 60000;
const listCaches = new Map();

function cachedList(key, fetcher) {
  const entry = listCaches.get(key);
  if (entry && Date.now() - entry.at <= LIST_CACHE_MAX_AGE_MS) return entry.promise;
  const promise = fetcher();
  listCaches.set(key, { at: Date.now(), promise });
  promise.catch(() => {
    if (listCaches.get(key)?.promise === promise) listCaches.delete(key);
  });
  return promise;
}

export function invalidateListCache(...keys) {
  keys.forEach((k) => listCaches.delete(k));
}

async function invalidating(keys, promise) {
  const result = await promise;
  invalidateListCache(...keys);
  return result;
}

export const listCasesCached = () => cachedList("cases", listCases);
const invalidatingCases = (promise) => invalidating(["cases"], promise);

export const getCase = (id) => request(`/cases/${id}`);
export const createCase = (payload) => invalidatingCases(request("/cases", { method: "POST", body: payload }));
export const listCourts = () => request("/cases/courts");
export const listCaseLawyers = () => request("/cases/assignable-lawyers");
export const addCaseNote = (id, noteText) => request(`/cases/${id}/notes`, { method: "POST", body: { note_text: noteText } });
export const updateCaseStage = (id, stage) => invalidatingCases(request(`/cases/${id}/stage`, { method: "PUT", body: { stage } }));
export const watchCase = (id) => invalidatingCases(request(`/cases/${id}/watch`, { method: "POST" }));
export const unwatchCase = (id) => invalidatingCases(request(`/cases/${id}/watch`, { method: "DELETE" }));
export const listLinkableClients = () => request("/cases/linkable-clients");
export const listCaseLinks = (caseId) => request(`/cases/${caseId}/links`);
export const linkUserToCase = (caseId, userId, canUpload) =>
  request(`/cases/${caseId}/links`, { method: "POST", body: { user_id: userId, can_upload: canUpload } });
export const unlinkCaseUser = (caseId, linkId) => request(`/cases/${caseId}/links/${linkId}`, { method: "DELETE" });

// ---------------- Search ----------------
function qs(params) {
  const usp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") usp.set(k, v); });
  const s = usp.toString();
  return s ? `?${s}` : "";
}
export const searchCaseNumber = (params) => request(`/search/case-number${qs(params)}`);
export const searchSessions = (params) => request(`/search/sessions${qs(params)}`);
export const searchExperts = (params) => request(`/search/experts${qs(params)}`);
export const searchExecution = (params) => request(`/search/execution${qs(params)}`);
export const searchInternal = (q) => request(`/search/internal${qs({ q })}`);
export const importRecord = (sourceType, sourceRefId, watch = true) =>
  invalidatingCases(request("/search/import", { method: "POST", body: { source_type: sourceType, source_ref_id: sourceRefId, watch } }));
export const listTracked = () => request("/search/tracked");
export const untrackCase = (caseId) => invalidatingCases(request(`/search/track/${caseId}`, { method: "DELETE" }));
export const listAssignableStaff = () => request("/search/assignable-staff");
export const requestStatusUpdate = (payload) => request("/search/request-update", { method: "POST", body: payload });

// ---------------- Documents ----------------
export const listDocuments = () => request("/documents");
export const uploadDocument = (caseId, file) => {
  const form = new FormData();
  form.append("case_id", caseId);
  form.append("file", file);
  return request("/documents", { method: "POST", body: form, isForm: true });
};
export const deleteDocument = (id) => request(`/documents/${id}`, { method: "DELETE" });
export const reviewDocument = (id, status, reason = null) =>
  request(`/documents/${id}/status`, { method: "PUT", body: { status, reason } });
export async function fetchDocumentBlobUrl(id) {
  const res = await request(`/documents/${id}/download`, { rawResponse: true });
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}
export const grantUploadAccess = (caseId, durationMinutes = 60) =>
  request("/documents/grants", { method: "POST", body: { case_id: caseId, duration_minutes: durationMinutes } });
export const listUploadGrants = (caseId) => request(`/documents/grants${qs({ case_id: caseId })}`);
export const myUploadAccess = () => request("/documents/my-upload-access");

// ---------------- Notifications ----------------
export const listNotifications = () => request("/notifications");
export const markNotificationRead = (id) => request(`/notifications/${id}/read`, { method: "PUT" });
export const markAllNotificationsRead = () => request("/notifications/read-all", { method: "PUT" });

// ---------------- Reminders ----------------
export const listReminders = () => request("/reminders");
export const createReminder = (payload) => request("/reminders", { method: "POST", body: payload });
export const resolveReminder = (id, status) => request(`/reminders/${id}/resolve`, { method: "PUT", body: { status } });
export const listAssignableUsers = () => request("/reminders/assignable-users");

// ---------------- Dashboard ----------------
export const getDashboardStats = () => request("/dashboard/stats");
export const getUpcomingHearings = () => request("/dashboard/upcoming-hearings");
export const getDashboardTaskStats = () => request("/dashboard/task-stats");

// ---------------- Activity log (Admin only — also enforced server-side) ----------------
export const listActivityLog = () => request("/activity-log");
export async function exportActivityLogCsv() {
  const res = await request("/activity-log/export", { rawResponse: true });
  return res.blob();
}

// ---------------- Procedural Intelligence ----------------
// Current Status -> Latest Event -> Required Next Procedure ->
// Responsible User -> Deadline -> Reminder/Notification -> Completion
export const listProcedureTypes = () => request("/procedures/types");
export const listCaseTypes = () => request("/procedures/case-types");
export const listCaseProcedures = (caseId) => request(`/procedures/${caseId}`);
export const previewNextActions = (caseId) => request(`/procedures/${caseId}/next-actions`);
export const recordProcedure = (caseId, payload) => request(`/procedures/${caseId}`, { method: "POST", body: payload });

export const listDeadlines = (params = {}) => request(`/deadlines${qs(params)}`);
export const syncDeadlines = () => request("/deadlines/sync", { method: "POST" });
export const confirmDeadline = (id, dueAt = null) => request(`/deadlines/${id}/confirm`, { method: "PUT", body: { due_at: dueAt } });
export const waiveDeadline = (id, reason) => request(`/deadlines/${id}/waive`, { method: "PUT", body: { reason } });

export const listOfficialSources = () => request("/official-sync/sources");
export const listOfficialChecks = (caseId) => request(`/official-sync/case/${caseId}/checks`);
export const recordOfficialCheck = (caseId, payload) => request(`/official-sync/case/${caseId}/check`, { method: "POST", body: payload });
export const listStaleOfficialSync = () => request("/official-sync/stale");

export const listProcedureRules = () => request("/rules");
export const verifyProcedureRule = (id, confirm, notes = null) => request(`/rules/${id}/verify`, { method: "POST", body: { confirm, notes } });
export const disableProcedureRule = (id) => request(`/rules/${id}/disable`, { method: "POST" });

// ---------------- System maintenance (Admin only — also enforced server-side) ----------------
export const resetDatabase = (confirmPhrase) => request("/admin/reset-database", { method: "POST", body: { confirm_phrase: confirmPhrase } });
export async function downloadBackup() {
  const res = await request("/admin/backup", { rawResponse: true });
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename=([^;]+)/);
  return { blob, filename: match ? match[1].trim() : "aslg-backup.zip" };
}
export function restoreDatabase(file, confirmPhrase) {
  const form = new FormData();
  form.append("file", file);
  form.append("confirm_phrase", confirmPhrase);
  return request("/admin/restore-database", { method: "POST", body: form, isForm: true });
}
