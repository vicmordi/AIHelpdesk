/**
 * Login — backend POST /auth/login, store token, redirect by role.
 */
import { getApiBaseUrl, setToken, getToken } from "./api.js";

function getErrorMessage(detail) {
  const map = {
    "Invalid email or password": "Invalid email or password.",
    "Invalid email or password.": "Invalid email or password.",
    "EMAIL_NOT_FOUND": "No account found with this email.",
    "INVALID_PASSWORD": "Incorrect password.",
    "Invalid organization code": "Invalid organization code.",
    "User not found for this organization": "No user found for this organization.",
    "User does not belong to this organization": "User does not belong to this organization.",
  };
  return map[detail] || detail || "Login failed.";
}

async function checkTokenAndRedirect() {
  const token = getToken();
  if (!token) return;
  try {
    const res = await fetch(`${getApiBaseUrl()}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;
    const userData = await res.json();
    const role = userData.role || "";
    if (role === "admin" || role === "super_admin" || role === "support_admin") {
      window.location.href = "admin.html";
    } else {
      window.location.href = "submit-ticket.html";
    }
  } catch (_) {}
}

checkTokenAndRedirect();

document.getElementById("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const organizationCodeEl = document.getElementById("organization-code-login");
  const organizationCode = organizationCodeEl ? organizationCodeEl.value.trim() : "";
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;
  const errorMessage = document.getElementById("error-message");
  const successMessage = document.getElementById("success-message");
  errorMessage.style.display = "none";
  successMessage.style.display = "none";

  try {
    const body = { email, password };
    if (organizationCode) body.organization_code = organizationCode;
    const res = await fetch(`${getApiBaseUrl()}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      errorMessage.textContent = getErrorMessage(data.detail);
      errorMessage.style.display = "flex";
      return;
    }
    setToken(data.token);
    const meRes = await fetch(`${getApiBaseUrl()}/auth/me`, {
      headers: { Authorization: `Bearer ${data.token}` },
    });
    if (meRes.ok) {
      const userData = await meRes.json();
      const role = userData.role || "";
      if (role === "admin" || role === "super_admin" || role === "support_admin") {
        window.location.href = "admin.html";
        return;
      }
    }
    window.location.href = "submit-ticket.html";
  } catch (err) {
    errorMessage.textContent = err.message || "Login failed.";
    errorMessage.style.display = "flex";
  }
});
