# Environment Variables

Use these in your backend `.env` (never commit `.env`). Copy to `.env` and set real values.

## Backend (.env)

```env
# Required: OpenAI (backend only)
OPENAI_API_KEY=sk-your-openai-key

# Required: Firebase Admin (JSON string of service account)
GOOGLE_APPLICATION_CREDENTIALS={"type":"service_account",...}

# Required: Firebase Web API Key (for Auth REST API: login/register)
FIREBASE_WEB_API_KEY=your-firebase-web-api-key

# Admin registration
ADMIN_ACCESS_CODE=your-secret-admin-code

# Optional: CORS origins (comma-separated)
CORS_ORIGINS=https://your-app.web.app,https://your-app.firebaseapp.com
```

## Frontend

- The app reads `window.__APP_CONFIG__` from `public/config.js` (only `apiBaseUrl`).
- No Firebase config or secrets in the frontend. Auth is handled by the backend.
- Never put OpenAI keys or Firebase admin secrets in frontend config.
