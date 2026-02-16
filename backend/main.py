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

from config import CORS_ORIGINS
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


# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(knowledge_base.router, prefix="/knowledge-base", tags=["Knowledge Base"])
app.include_router(tickets.router, prefix="/tickets", tags=["Tickets"])
