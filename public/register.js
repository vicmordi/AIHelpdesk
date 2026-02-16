/**
 * Register — backend POST /auth/register, store token, redirect by role.
 */
import { getApiBaseUrl, setToken } from "./api.js";

function getErrorMessage(detail) {
  const map = {
    "Email already registered": "This email is already registered.",
    "Invalid admin access code.": "Invalid admin access code.",
  };
  return map[detail] || detail || "Registration failed.";
}

const adminCodeGroup = document.getElementById("admin-code-group");
const adminCodeInput = document.getElementById("admin-code");
const registerRole = document.getElementById("register-role");
if (registerRole && adminCodeGroup && adminCodeInput) {
  registerRole.addEventListener("change", (e) => {
    if (e.target.value === "admin") {
      adminCodeGroup.style.display = "block";
      adminCodeInput.required = true;
    } else {
      adminCodeGroup.style.display = "none";
      adminCodeInput.required = false;
      adminCodeInput.value = "";
    }
  });
}

document.getElementById("register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const email = document.getElementById("register-email").value;
  const password = document.getElementById("register-password").value;
  const role = document.getElementById("register-role").value;
  const adminCode = document.getElementById("admin-code").value;
  const errorMessage = document.getElementById("error-message");
  const successMessage = document.getElementById("success-message");
  errorMessage.style.display = "none";
  successMessage.style.display = "none";

  if (role === "admin" && !adminCode) {
    errorMessage.textContent = "Admin access code is required for administrator accounts.";
    errorMessage.style.display = "flex";
    return;
  }

  try {
    const res = await fetch(`${getApiBaseUrl()}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email,
        password,
        role,
        admin_code: role === "admin" ? adminCode : null,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      errorMessage.textContent = getErrorMessage(data.detail);
      errorMessage.style.display = "flex";
      return;
    }
    setToken(data.token);
    successMessage.textContent = `Account created successfully as ${data.role}! Redirecting...`;
    successMessage.style.display = "flex";
    setTimeout(() => {
      if (data.role === "admin") {
        window.location.href = "admin.html";
      } else {
        window.location.href = "submit-ticket.html";
      }
    }, 1500);
  } catch (err) {
    errorMessage.textContent = err.message || "Registration failed.";
    errorMessage.style.display = "flex";
  }
});
