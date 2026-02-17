/**
 * Force password change - required when must_change_password is true.
 */
import { getApiBaseUrl, getToken, setToken } from "./api.js";

(async function init() {
    const token = getToken();
    if (!token) {
        window.location.href = "login.html";
        return;
    }
    try {
        const res = await fetch(`${getApiBaseUrl()}/auth/me`, {
            headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) {
            window.location.href = "login.html";
            return;
        }
        const user = await res.json();
        if (!user.must_change_password) {
            const role = user.role || "";
            if (role === "admin" || role === "super_admin" || role === "support_admin") {
                window.location.href = "admin.html";
            } else {
                window.location.href = "submit-ticket.html";
            }
            return;
        }
    } catch (_) {
        window.location.href = "login.html";
    }
})();

document.getElementById("change-password-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const errorEl = document.getElementById("error-message");
    errorEl.style.display = "none";
    const current = document.getElementById("current-password").value;
    const newPwd = document.getElementById("new-password").value;
    if (!current || !newPwd || newPwd.length < 6) {
        errorEl.textContent = "New password must be at least 6 characters.";
        errorEl.style.display = "flex";
        return;
    }
    try {
        const res = await fetch(`${getApiBaseUrl()}/auth/change-password`, {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${getToken()}`,
            },
            body: JSON.stringify({ current_password: current, new_password: newPwd }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
            errorEl.textContent = data.detail || "Failed to change password.";
            errorEl.style.display = "flex";
            return;
        }
        const meRes = await fetch(`${getApiBaseUrl()}/auth/me`, {
            headers: { Authorization: `Bearer ${getToken()}` },
        });
        const user = await meRes.json().catch(() => ({}));
        const role = user.role || "";
        if (role === "admin" || role === "super_admin" || role === "support_admin") {
            window.location.href = "admin.html";
        } else {
            window.location.href = "submit-ticket.html";
        }
    } catch (err) {
        errorEl.textContent = err.message || "Failed to change password.";
        errorEl.style.display = "flex";
    }
});
