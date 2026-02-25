"""
Knowledge Improvement API — automatic KB draft generation from resolved tickets.
Super_admin only. Multi-tenant safe.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import Optional, List
from firebase_admin import firestore

from middleware import require_super_admin
from schemas import STRICT_REQUEST_CONFIG
from knowledge_improvement import (
    get_db,
    run_analysis_for_organization,
    get_suggestions,
    approve_suggestion,
    reject_suggestion,
    get_analytics as _get_analytics,
)
from config import OPENAI_API_KEY
from openai import OpenAI

router = APIRouter()


@router.post("/run")
async def trigger_analysis(current_user: dict = Depends(require_super_admin)):
    """
    Run knowledge improvement analysis for the organization.
    Analyzes resolved tickets, clusters by similarity, creates draft suggestions.
    Never auto-publishes.
    """
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="Organization required")
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OpenAI not configured")
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
        result = run_analysis_for_organization(organization_id, client)
        return {
            "message": f"Analysis complete. Created {result['created']} new suggestion(s).",
            "created": result["created"],
            "clusters_processed": result["clusters_processed"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/suggestions")
async def list_suggestions(
    status: Optional[str] = None,
    current_user: dict = Depends(require_super_admin),
):
    """
    List knowledge suggestions (draft, approved, rejected).
    status: draft | approved | rejected | all (default: draft)
    """
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="Organization required")
    db = get_db()
    suggestions = get_suggestions(db, organization_id, status or "draft")
    return {"suggestions": suggestions}


class ApproveRejectBody(BaseModel):
    model_config = STRICT_REQUEST_CONFIG


@router.post("/suggestions/{suggestion_id}/approve")
async def approve_suggestion_route(
    suggestion_id: str,
    current_user: dict = Depends(require_super_admin),
):
    """Approve suggestion: publish to knowledge base, mark as approved."""
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="Organization required")
    db = get_db()
    result = approve_suggestion(db, suggestion_id, organization_id, current_user["uid"])
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Approve failed"))
    return {"message": "Suggestion approved and published", "article_id": result.get("article_id")}


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_suggestion_route(
    suggestion_id: str,
    current_user: dict = Depends(require_super_admin),
):
    """Reject suggestion."""
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="Organization required")
    db = get_db()
    result = reject_suggestion(db, suggestion_id, organization_id, current_user["uid"])
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Reject failed"))
    return {"message": "Suggestion rejected"}


@router.get("/analytics")
async def analytics(current_user: dict = Depends(require_super_admin)):
    """
    Dashboard widgets: recurring issues, suggested articles pending.
    """
    organization_id = current_user.get("organization_id")
    if not organization_id:
        raise HTTPException(status_code=400, detail="Organization required")
    db = get_db()
    data = _get_analytics(db, organization_id)
    return data
