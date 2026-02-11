/**
 * Firebase Configuration — single source of truth.
 * ES module: import { auth, API_BASE_URL, apiRequest } from "./firebase-config.js";
 * Requires window.__APP_CONFIG__ to be set before this script loads (e.g. via config.js).
 * Copy config.example.js to config.js and set apiBaseUrl + firebase. For production, generate config.js from env.
 */
import { initializeApp, getApps, getApp } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js";

const CONFIG = window.__APP_CONFIG__;
if (!CONFIG || !CONFIG.apiBaseUrl || !CONFIG.firebase || !CONFIG.firebase.apiKey) {
  throw new Error(
    "App config missing. Copy config.example.js to config.js and set apiBaseUrl and firebase, or set window.__APP_CONFIG__ before loading this script."
  );
}

const firebaseConfig = CONFIG.firebase;
export const API_BASE_URL = CONFIG.apiBaseUrl.replace(/\/$/, "");

export const app = getApps().length === 0 ? initializeApp(firebaseConfig) : getApp();
export const auth = getAuth(app);

/**
 * Get the current user's ID token for API authentication
 */
async function getIdToken() {
  const user = auth.currentUser;
  if (!user) {
    throw new Error("User not authenticated");
  }
  return await user.getIdToken();
}

/**
 * Make an authenticated API request to the backend
 */
export async function apiRequest(endpoint, options = {}) {
  const token = await getIdToken();
  const defaultOptions = {
    headers: {
      "Content-Type": "application/json",
      "Authorization": `Bearer ${token}`
    }
  };
  const mergedOptions = {
    ...defaultOptions,
    ...options,
    headers: {
      ...defaultOptions.headers,
      ...(options.headers || {})
    }
  };
  const response = await fetch(`${API_BASE_URL}${endpoint}`, mergedOptions);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `HTTP error! status: ${response.status}`);
  }
  return await response.json();
}
