# AI Helpdesk Application

An MVP AI-powered helpdesk application with automatic ticket resolution using OpenAI and Firebase.

## Features

- **Role-based Authentication**: Admin and User roles with Firebase Authentication
- **Knowledge Base Management**: Admins can create and manage knowledge base articles
- **AI-Powered Ticket Resolution**: Automatic ticket analysis and resolution using OpenAI
- **Smart Escalation**: Tickets are escalated when AI confidence is low or no solution is found
- **Real-time Ticket Tracking**: Users can view their tickets and responses

## Configuration

- **Backend:** Set environment variables as in `ENV_TEMPLATE.md` (include `FIREBASE_WEB_API_KEY` for login/register). Never commit `.env`.
- **Frontend:** App reads `window.__APP_CONFIG__` from `public/config.js` (only `apiBaseUrl`). No Firebase config in the frontend.

## Security (OWASP-oriented)

- **Rate limiting:** All public endpoints are rate-limited by IP (default 200/min). Auth endpoints (login, register, register-org) have a stricter limit (15/min). Responses return 429 with a JSON body and Retry-After header. Configure via `RATE_LIMIT_DEFAULT` in `.env`.
- **Input validation:** Request bodies use strict Pydantic schemas: extra fields are rejected, and string length/type checks apply. See `backend/schemas.py` and the Request models in each route module.
- **API keys:** No hard-coded secrets. All keys come from environment variables and are never sent to the frontend. See `ENV_TEMPLATE.md` for key rotation guidance.

## Architecture

- **Browser → FastAPI → Firebase Admin SDK.** Frontend has no Firebase client SDK; all auth and data go through the backend.
- Login and register use `POST /auth/login` and `POST /auth/register`; the backend calls Firebase Auth REST API and returns an ID token. The frontend stores the token and sends it as `Authorization: Bearer` on each request.
- Backend verifies tokens with Firebase Admin and uses Firestore for user roles and ticket data.

## Development Notes

- Firebase Admin SDK is used for token verification and Firestore only on the backend
- All API requests require a Bearer token (obtained via backend login/register)
- OpenAI and all privileged operations are backend-only
- Confidence threshold is set to 0.7 for auto-resolution

## License

This is an MVP project for demonstration purposes.
