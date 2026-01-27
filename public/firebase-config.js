/**
 * Firebase Configuration
 * Replace these values with your Firebase project configuration
 */

// Initialize Firebase
const firebaseConfig = {
    apiKey: "AIzaSyDf27ycSvzefI94EQwXqQ7FIMekT4JiOGA",
    authDomain: "aihelpdesk-21060.firebaseapp.com",
    projectId: "aihelpdesk-21060",
    storageBucket: "aihelpdesk-21060.firebasestorage.app",
    messagingSenderId: "966712569424",
    appId: "1:966712569424:web:f907a4b894c197db336b55",
    measurementId: "G-XJ1D6W1ZNQ"
  };

// Initialize Firebase
firebase.initializeApp(firebaseConfig);

// Get Auth instance
const auth = firebase.auth();

// API_BASE_URL is provided by /js/config.js (must be loaded before this file)

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
 * Make an authenticated API request
 */
async function apiRequest(endpoint, options = {}) {
    const token = await getIdToken();
    
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
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
