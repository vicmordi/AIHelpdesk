/**
 * Nav logo — conditional href based on auth state.
 * Employee → submit-ticket.html | Admin → admin.html | Unauthenticated → index.html
 */
import { getToken, getApiBaseUrl } from "../api.js";

/** Get the dashboard URL for authenticated users by role */
export async function getLogoHref() {
  const token = getToken();
  if (!token) return "index.html";
  try {
    const res = await fetch(
      getApiBaseUrl() + "/auth/me",
      { headers: { Authorization: `Bearer ${token}` } }
    );
    if (!res.ok) return "index.html";
    const user = await res.json();
    const role = user.role || "";
    if (["admin", "super_admin", "support_admin"].includes(role)) {
      return "admin.html#dashboard";
    }
    return "submit-ticket.html";
  } catch {
    return "index.html";
  }
}

/** SVG chat bubble icon with gradient fill (for nav and sidebar) */
export const LOGO_ICON_SVG = `<svg class="nav-logo-svg" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
  <defs>
    <linearGradient id="nav-logo-grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#4f46e5"/>
      <stop offset="100%" style="stop-color:#06b6d4"/>
    </linearGradient>
  </defs>
  <path fill="url(#nav-logo-grad)" d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
</svg>`;
