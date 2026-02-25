# Environment Variables

Use these in your backend `.env` (never commit `.env`). Copy to `.env` and set real values.

## Backend (.env)

```env
# Required: OpenAI (backend only; never in frontend)
OPENAI_API_KEY=sk-your-openai-key

# Required: Firebase Admin (JSON string of service account)
GOOGLE_APPLICATION_CREDENTIALS={"type":"service_account",...}

# Required: Firebase Web API Key (for Auth REST API: login/register)
FIREBASE_WEB_API_KEY=your-firebase-web-api-key

# Admin registration
ADMIN_ACCESS_CODE=your-secret-admin-code

# Optional: CORS origins (comma-separated)
CORS_ORIGINS=https://your-app.web.app,https://your-app.firebaseapp.com

# Optional: rate limit default (e.g. "200/minute")
RATE_LIMIT_DEFAULT=200/minute
```

## Key rotation and security (OWASP)

- **Rotate keys periodically**: Regenerate OpenAI key, Firebase Web API key, and Admin access code on a schedule (e.g. quarterly). Update `.env` and redeploy; no code change required.
- **No keys client-side**: `public/config.js` must only contain `apiBaseUrl`. Never put `OPENAI_API_KEY`, `FIREBASE_WEB_API_KEY`, or service account JSON in frontend or in HTML/JS sent to the browser.
- **Secrets in CI**: Use your platform’s secret store (e.g. GitHub Actions secrets, Render env) and never log or echo secrets.

## Frontend

- The app reads `window.__APP_CONFIG__` from `public/config.js` (only `apiBaseUrl`).
- No Firebase config or secrets in the frontend. Auth is handled by the backend.
- Never put OpenAI keys or Firebase admin secrets in frontend config.
