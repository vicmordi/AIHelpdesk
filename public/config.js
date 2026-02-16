/**
 * App config — set before loading api.js
 * Environment-aware: DEV backend on Firebase preview channel, PROD otherwise.
 */
const hostname = window.location.hostname;
const isDev =
  hostname.includes("--dev") ||
  (hostname.includes("firebaseapp.com") && hostname.includes("dev"));

const API_BASE_URL = isDev
  ? "https://aihelpdesk-dev.onrender.com"
  : "https://aihelpdesk-2ycg.onrender.com";

window.__APP_CONFIG__ = {
  apiBaseUrl: API_BASE_URL
};
