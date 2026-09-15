import { loginRequest, logoutRequest, setSession, clearSession, getCurrentUser as _getCurrentUser, getPermissions } from "./api.js";

export async function login(username, password) {
  const data = await loginRequest(username, password);
  setSession(data.access_token, data.user, data.permissions);
  return data.user;
}

export function logout() {
  // Best-effort audit trail entry — fired while the token is still present,
  // but never allowed to block or fail the actual logout (stateless JWTs
  // mean there's nothing server-side that needs to succeed for logout to
  // be real; clearSession() below is what actually logs the user out).
  logoutRequest().catch(() => {});
  clearSession();
}

export function getCurrentUser() {
  return _getCurrentUser();
}

export function isAuthenticated() {
  return getCurrentUser() !== null;
}

export { getPermissions };
