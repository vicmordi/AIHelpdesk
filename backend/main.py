"""
AI Helpdesk Backend - FastAPI Application
Main entry point for the helpdesk API
"""

import json
import os

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import HTTPException
from starlette.responses import Response

import firebase_admin
from firebase_admin import credentials

from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from config import CORS_ORIGINS, CORS_ORIGIN_REGEX, ENVIRONMENT
from cors_ensure import CorsEnsureMiddleware, cors_headers_for_origin
from rate_limit import limiter, rate_limit_exceeded_handler
from routes import auth, knowledge_base, tickets, admin, organization, messages, notifications
from routes import knowledge_improvement as knowledge_improvement_routes


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

# Rate limiting: IP-based, applies to all routes. Graceful 429 with Retry-After (OWASP).
# RateLimitExceeded is handled first (returns 429); then generic Exception handler.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
# Middleware order (last added = outermost): CorsEnsure -> CORS -> SlowAPI -> app.
# SlowAPI runs before app so rate limits are checked; 429 from handler when exceeded.
app.add_middleware(SlowAPIMiddleware)

# CORS: environment-driven. CORS_ORIGINS from env (comma-separated), or default list.
# allow_origin_regex permits any Firebase Hosting origin (*.web.app) for preview channels.
if ENVIRONMENT == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_origin_regex=CORS_ORIGIN_REGEX,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Ensure CORS on every response (including 500/429) so Firebase preview origins never get blocked
app.add_middleware(CorsEnsureMiddleware)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Return error with CORS headers. Preserve HTTPException status and detail."""
    origin = request.headers.get("origin") if request else None
    headers = cors_headers_for_origin(origin)
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=headers,
        )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"}, headers=headers)


@app.on_event("startup")
async def startup_event():
    """
    Runs once when the app starts.
    Keeps startup fast and avoids Render timeouts.
    """
    init_firebase()
    # Start Knowledge Improvement background scheduler (24h interval)
    try:
        from background_scheduler import start_scheduler
        start_scheduler()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("KI scheduler not started: %s", e)


# Health check / readiness endpoint (exempt from rate limit so load balancers don't get 429)
@app.get("/")
@limiter.exempt
async def health(request: Request, response: Response):
    return JSONResponse(content={"status": "ok"})


# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(knowledge_base.router, prefix="/knowledge-base", tags=["Knowledge Base"])
app.include_router(tickets.router, prefix="/tickets", tags=["Tickets"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])
app.include_router(organization.router, prefix="/organization", tags=["Organization"])
app.include_router(messages.router, prefix="/messages", tags=["Messages"])
app.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
app.include_router(
    knowledge_improvement_routes.router,
    prefix="/admin/knowledge-improvement",
    tags=["Knowledge Improvement"],
)
