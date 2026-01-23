"""
AI Helpdesk Backend - FastAPI Application
Main entry point for the helpdesk API
"""

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import os
from dotenv import load_dotenv

from routes import auth, knowledge_base, tickets

# Load environment variables
load_dotenv()

app = FastAPI(
    title="AI Helpdesk API",
    description="AI-powered helpdesk with knowledge base and ticket management",
    version="1.0.0"
)

# CORS middleware - allow frontend to make requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/auth", tags=["Authentication"])
app.include_router(knowledge_base.router, prefix="/knowledge-base", tags=["Knowledge Base"])
app.include_router(tickets.router, prefix="/tickets", tags=["Tickets"])


@app.get("/")
async def root():
    """Health check endpoint"""
    return {"message": "AI Helpdesk API is running", "status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

@app.get("/")
def root():
    return {"status": "ok"}

