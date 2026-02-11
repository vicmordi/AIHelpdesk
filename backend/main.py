"""
AI Helpdesk Backend - FastAPI Application
Main entry point for the helpdesk API
"""

import json
import os

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials

from config import (
    API_BASE_URL,
    CORS_ORIGINS,
    FIREBASE_APP_ID,
    FIREBASE_AUTH_DOMAIN,
    FIREBASE_MEASUREMENT_ID,
    FIREBASE_MESSAGING_SENDER_ID,
    FIREBASE_PROJECT_ID,
    FIREBASE_PUBLIC_API_KEY,
    FIREBASE_STORAGE_BUCKET,
)
from routes import auth, knowledge_base, tickets


def init_firebase():
    """
    Initialize Firebase Admin SDK exactly once.
    Uses GOOGLE_APPLICATION_CREDENTIALS env var containing the full service account JSON.
    No file reads; compatible with Render deployment.
    """
    if firebase_admin._apps:
        return

    cred_dict = json.loads(os.environ["GOOGLE_APPLICATION_CREDENTIALS"])
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)


app = FastAPI(
    title="AI Helpdesk API",
    description="AI-powered helpdesk with knowledge base and ticket management",
    version="1.0.0"
)

# CORS middleware — allow origins from env (CORS_ORIGINS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_event():
    """
    Runs once when the app starts.
    Keeps startup fast and avoids Render timeouts.
    """
    init_firebase()


# Health check / readiness endpoint
@app.get("/")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def get_config():
    """Return API base URL and Firebase client config from env. Safe to expose."""
    return {
        "apiBaseUrl": API_BASE_URL or None,
        "firebase": {
            "apiKey": FIREBASE_PUBLIC_API_KEY or None,
            "authDomain": FIREBASE_AUTH_DOMAIN or None,
            "projectId": FIREBASE_PROJECT_ID or None,
            "storageBucket": FIREBASE_STORAGE_BUCKET or None,
            "messagingSenderId": FIREBASE_MESSAGING_SENDER_ID or None,
            "appId": FIREBASE_APP_ID or None,
            "measurementId": FIREBASE_MEASUREMENT_ID or None,
        },
    }


# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(knowledge_base.router, prefix="/knowledge-base", tags=["Knowledge Base"])
app.include_router(tickets.router, prefix="/tickets", tags=["Tickets"])
