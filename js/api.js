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

async function request(path, { method = "GET", body, isForm = false, rawResponse = false } = {}) {
  const session = getSession();
  const headers = {};
  if (!isForm) headers["Content-Type"] = "application/json";
  if (session?.token) headers["Authorization"] = `Bearer ${session.token}`;

  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : isForm ? body : JSON.stringify(body),
  });

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

// ---------------- Auth ----------------
export const loginRequest = (username, password) => request("/auth/login", { method: "POST", body: { username, password } });
export const logoutRequest = () => request("/auth/logout", { method: "POST" });

// ---------------- Users (Admin) ----------------
export const listUsers = () => request("/users");
export const createUser = (payload) => request("/users", { method: "POST", body: payload });
export const updateUser = (id, payload) => request(`/users/${id}`, { method: "PUT", body: payload });
export const deleteUser = (id) => request(`/users/${id}`, { method: "DELETE" });
export const resetUserPassword = (id, newPassword) => request(`/users/${id}/reset-password`, { method: "POST", body: { new_password: newPassword } });
export const bulkUserAction = (userIds, action, newPassword) => request("/users/bulk", { method: "POST", body: { user_ids: userIds, action, new_password: newPassword } });

// ---------------- Cases ----------------
export const listCases = () => request("/cases");
export const getCase = (id) => request(`/cases/${id}`);
export const createCase = (payload) => request("/cases", { method: "POST", body: payload });
export const listCourts = () => request("/cases/courts");
export const listCaseLawyers = () => request("/cases/assignable-lawyers");
export const addCaseNote = (id, noteText) => request(`/cases/${id}/notes`, { method: "POST", body: { note_text: noteText } });
export const updateCaseStage = (id, stage) => request(`/cases/${id}/stage`, { method: "PUT", body: { stage } });
export const watchCase = (id) => request(`/cases/${id}/watch`, { method: "POST" });
export const unwatchCase = (id) => request(`/cases/${id}/watch`, { method: "DELETE" });
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
  request("/search/import", { method: "POST", body: { source_type: sourceType, source_ref_id: sourceRefId, watch } });
export const listTracked = () => request("/search/tracked");
export const untrackCase = (caseId) => request(`/search/track/${caseId}`, { method: "DELETE" });
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
