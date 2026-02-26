/**
 * Backend API client — no Firebase. Token stored in localStorage.
 * Load config.js before this script so window.__APP_CONFIG__ is set.
 */
const CONFIG = window.__APP_CONFIG__;
if (!CONFIG || !CONFIG.apiBaseUrl) {
  throw new Error("App config missing. Load config.js first and set window.__APP_CONFIG__.apiBaseUrl");
}

const API_BASE_URL = CONFIG.apiBaseUrl.replace(/\/$/, "");
const TOKEN_KEY = "auth_token";

export function getApiBaseUrl() {
  return API_BASE_URL;
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

/**
 * Authenticated request to backend. Uses stored token.
 */
export async function apiRequest(endpoint, options = {}) {
  const token = getToken();
  if (!token) {
    throw new Error("Not authenticated");
  }
  const defaultOptions = {
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`,
    },
  };
  const merged = {
    ...defaultOptions,
    ...options,
    headers: { ...defaultOptions.headers, ...(options.headers || {}) },
  };
  const response = await fetch(`${API_BASE_URL}${endpoint}`, merged);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

/**
 * Check if user is logged in (has token).
 */
export function isAuthenticated() {
  return !!getToken();
}

/**
 * Format an ISO timestamp (UTC with Z) in the user's local timezone.
 * Uses browser locale and timezone so times display correctly for the viewer.
 */
export function formatLocalTime(isoString) {
  if (!isoString) return "";
  const d = new Date(isoString);
  if (Number.isNaN(d.getTime())) return String(isoString);
  return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
}

/**
 * Format last_analysis_run from API: Firestore { seconds, nanoseconds } or legacy ISO string.
 * Ensures correct local time display with timezone consistency.
 */
export function formatLastAnalysisRun(value) {
  if (value == null || value === "") return "";
  if (typeof value === "object" && typeof value.seconds === "number") {
    const d = new Date(value.seconds * 1000);
    return d.toLocaleString(undefined, { dateStyle: "short", timeStyle: "short" });
  }
  return formatLocalTime(value);
}
