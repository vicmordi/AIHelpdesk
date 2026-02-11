# Environment Variables

Use these in your backend `.env` (never commit `.env`). Copy to `.env` and set real values.

## Backend (.env)

```env
# Required: OpenAI (backend only)
OPENAI_API_KEY=sk-your-openai-key

# Required: Firebase Admin (JSON string of service account; no file path)
GOOGLE_APPLICATION_CREDENTIALS={"type":"service_account",...}

# Required for /api/config: public URL of this backend
API_BASE_URL=https://your-app.onrender.com

# Admin registration
ADMIN_ACCESS_CODE=your-secret-admin-code

# Optional: CORS origins (comma-separated)
CORS_ORIGINS=https://your-app.web.app,https://your-app.firebaseapp.com

# Optional: Firebase client config (for GET /api/config if you use it)
FIREBASE_PUBLIC_API_KEY=your-firebase-api-key
FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
FIREBASE_PROJECT_ID=your-project-id
FIREBASE_STORAGE_BUCKET=your-project.firebasestorage.app
FIREBASE_MESSAGING_SENDER_ID=123456789
FIREBASE_APP_ID=1:123456789:web:abc
FIREBASE_MEASUREMENT_ID=G-XXXXXXXXXX
```

## Frontend

- The app reads `window.__APP_CONFIG__` from `public/config.js`.
- For production, you can generate `config.js` from env (apiBaseUrl + firebase client config).
- Never put OpenAI keys or Firebase admin secrets in frontend config.
