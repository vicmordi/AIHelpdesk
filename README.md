# AI Helpdesk Application

An MVP AI-powered helpdesk application with automatic ticket resolution using OpenAI and Firebase.

## Features

- **Role-based Authentication**: Admin and User roles with Firebase Authentication
- **Knowledge Base Management**: Admins can create and manage knowledge base articles
- **AI-Powered Ticket Resolution**: Automatic ticket analysis and resolution using OpenAI
- **Smart Escalation**: Tickets are escalated when AI confidence is low or no solution is found
- **Real-time Ticket Tracking**: Users can view their tickets and responses

## Configuration

- **Backend:** Set environment variables as in `ENV_TEMPLATE.md`. Never commit `.env`.
- **Frontend:** App reads `window.__APP_CONFIG__` from `public/config.js`. For production, generate `config.js` from env (apiBaseUrl + Firebase client config only; no API secrets).

## Development Notes

- The application uses Firebase Admin SDK for backend operations
- Frontend uses Firebase Auth SDK for user authentication
- All API requests require a Bearer token (Firebase ID token)
- Frontend talks only to the backend API; OpenAI and privileged operations are backend-only
- The AI prompt is designed to prevent hallucination and force JSON output
- Confidence threshold is set to 0.7 for auto-resolution

## License

This is an MVP project for demonstration purposes.
