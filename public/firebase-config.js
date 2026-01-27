/**
 * Firebase Configuration — single source of truth.
 * ES module: import { auth, API_BASE_URL, apiRequest } from "./firebase-config.js";
 * Firebase is initialized exactly once (guard with getApps).
 */
import { initializeApp, getApps, getApp } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-app.js";
import { getAuth } from "https://www.gstatic.com/firebasejs/10.7.1/firebase-auth.js";

const firebaseConfig = {
    apiKey: "AIzaSyDf27ycSvzefI94EQwXqQ7FIMekT4JiOGA",
    authDomain: "aihelpdesk-21060.firebaseapp.com",
    projectId: "aihelpdesk-21060",
    storageBucket: "aihelpdesk-21060.firebasestorage.app",
    messagingSenderId: "966712569424",
    appId: "1:966712569424:web:f907a4b894c197db336b55",
    measurementId: "G-XJ1D6W1ZNQ"
};

export const app = getApps().length === 0 ? initializeApp(firebaseConfig) : getApp();
export const auth = getAuth(app);
export const API_BASE_URL = "https://aihelpdesk-2ycg.onrender.com";

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
