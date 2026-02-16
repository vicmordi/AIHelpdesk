"""
Configuration - Environment variables only.
Firebase Admin SDK is initialized in main.py via GOOGLE_APPLICATION_CREDENTIALS (JSON string).
"""

import os

# OpenAI API Key (backend only; never exposed to frontend)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Admin Access Code - Required for admin role assignment during registration
ADMIN_ACCESS_CODE = os.getenv("ADMIN_ACCESS_CODE", "")

# Firebase Web API Key - used by backend only for Auth REST API (signIn/signUp)
FIREBASE_WEB_API_KEY = os.getenv("FIREBASE_WEB_API_KEY", "")

# Public config for frontend (no secrets) - used by GET /api/config
API_BASE_URL = os.getenv("API_BASE_URL", "").rstrip("/")
FIREBASE_PUBLIC_API_KEY = os.getenv("FIREBASE_PUBLIC_API_KEY", "")
FIREBASE_AUTH_DOMAIN = os.getenv("FIREBASE_AUTH_DOMAIN", "")
FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID", "")
FIREBASE_STORAGE_BUCKET = os.getenv("FIREBASE_STORAGE_BUCKET", "")
FIREBASE_MESSAGING_SENDER_ID = os.getenv("FIREBASE_MESSAGING_SENDER_ID", "")
FIREBASE_APP_ID = os.getenv("FIREBASE_APP_ID", "")
FIREBASE_MEASUREMENT_ID = os.getenv("FIREBASE_MEASUREMENT_ID", "")

# CORS allowed origins (comma-separated list)
_cors = os.getenv("CORS_ORIGINS", "https://aihelpdesk-21060.web.app,https://aihelpdesk-21060.firebaseapp.com")
CORS_ORIGINS = [s.strip() for s in _cors.split(",") if s.strip()]
