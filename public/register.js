/**
 * Register — org-only. Creates organization + super_admin. No employee self sign-up.
 */
import { getApiBaseUrl, setToken } from "./api.js";

function getErrorMessage(detail) {
  const map = {
    "Email already registered": "This email is already registered.",
    "Organization code already in use": "That organization code is already in use.",
  };
  return map[detail] || detail || "Registration failed.";
}

document.getElementById("register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const organizationName = (document.getElementById("organization-name")?.value || "").trim();
  const superAdminName = (document.getElementById("super-admin-name")?.value || "").trim();
  const organizationCode = (document.getElementById("organization-code")?.value || "").trim();
  const email = document.getElementById("register-email").value;
  const password = document.getElementById("register-password").value;
  const errorMessage = document.getElementById("error-message");
  const successMessage = document.getElementById("success-message");
  errorMessage.style.display = "none";
  successMessage.style.display = "none";

  if (!organizationName || !organizationCode || !superAdminName || !email || !password) {
    errorMessage.textContent = "All fields are required.";
    errorMessage.style.display = "flex";
    return;
  }

  try {
    const res = await fetch(`${getApiBaseUrl()}/auth/register-org`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        organization_name: organizationName,
        organization_code: organizationCode,
        super_admin_name: superAdminName,
        email,
        password,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      errorMessage.textContent = getErrorMessage(data.detail);
      errorMessage.style.display = "flex";
      return;
    }
    setToken(data.token);
    successMessage.textContent = "Organization created. Redirecting...";
    successMessage.style.display = "flex";
    setTimeout(() => {
      window.location.href = "admin.html";
    }, 1500);
  } catch (err) {
    errorMessage.textContent = err.message || "Registration failed.";
    errorMessage.style.display = "flex";
  }
});
