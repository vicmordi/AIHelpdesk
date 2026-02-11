/**
 * App config - set by this script before loading firebase-config.js
 * Copy this file to config.js and set real values (config.js is gitignored).
 * In production, generate config.js from environment variables at deploy time.
 */
window.__APP_CONFIG__ = {
  apiBaseUrl: "YOUR_API_BASE_URL",
  firebase: {
    apiKey: "YOUR_FIREBASE_API_KEY",
    authDomain: "YOUR_PROJECT_ID.firebaseapp.com",
    projectId: "YOUR_PROJECT_ID",
    storageBucket: "YOUR_PROJECT_ID.firebasestorage.app",
    messagingSenderId: "YOUR_MESSAGING_SENDER_ID",
    appId: "1:YOUR_MESSAGING_SENDER_ID:web:YOUR_APP_ID",
    measurementId: "G-XXXXXXXXXX"
  }
};
