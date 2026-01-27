/**
 * Login Page JavaScript
 */
import { auth, API_BASE_URL } from "./firebase-config.js";
import { signInWithEmailAndPassword, onAuthStateChanged } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js";

function getErrorMessage(errorCode) {
    const errorMessages = {
        "auth/user-not-found": "No account found with this email.",
        "auth/wrong-password": "Incorrect password.",
        "auth/email-already-in-use": "This email is already registered.",
        "auth/weak-password": "Password should be at least 6 characters.",
        "auth/invalid-email": "Invalid email address.",
        "auth/network-request-failed": "Network error. Please check your connection."
    };
    return errorMessages[errorCode] || `Error: ${errorCode || "Unknown error"}`;
}

async function checkUserRoleAndRedirect(user) {
    try {
        const token = await user.getIdToken();
        const response = await fetch(`${API_BASE_URL}/auth/me`, {
            headers: { "Authorization": `Bearer ${token}` }
        });
        if (response.ok) {
            const userData = await response.json();
            if (userData.role === "admin") {
                window.location.href = "admin.html";
            } else {
                window.location.href = "submit-ticket.html";
            }
        }
    } catch (error) {
        console.error("Error checking user role:", error);
    }
}

onAuthStateChanged(auth, (user) => {
    if (user) {
        checkUserRoleAndRedirect(user);
    }
});

document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = document.getElementById("email").value;
    const password = document.getElementById("password").value;
    const errorMessage = document.getElementById("error-message");
    const successMessage = document.getElementById("success-message");
    errorMessage.style.display = "none";
    successMessage.style.display = "none";

    try {
        const userCredential = await signInWithEmailAndPassword(auth, email, password);
        await checkUserRoleAndRedirect(userCredential.user);
    } catch (error) {
        errorMessage.textContent = getErrorMessage(error.code);
        errorMessage.style.display = "flex";
    }
});
