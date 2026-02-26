"""
Knowledge Base routes (Admin only)
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any  # noqa: F401
from datetime import datetime
from firebase_admin import firestore
from middleware import require_admin_or_above, require_super_admin
from flow_engine import normalize_article_to_flow, convert_legacy_content_to_flow
from schemas import STRICT_REQUEST_CONFIG
from activity_logging import log_activity, ACTION_KNOWLEDGE_BASE_VIEW

router = APIRouter()


def get_db():
    """Lazy initialization of Firestore client"""
    return firestore.client()


class KnowledgeBaseArticle(BaseModel):
    """Strict validation: known fields only, length limits (OWASP)."""
    model_config = STRICT_REQUEST_CONFIG
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1, max_length=100_000)
    category: Optional[str] = Field(None, max_length=128)
    type: Optional[str] = Field(None, max_length=64)
    article_type: Optional[str] = Field(None, max_length=64)
    trigger_phrases: Optional[List[str]] = Field(None, max_length=200)
    flow: Optional[List[Dict[str, Any]]] = Field(None, max_length=500)
    guided_flow: Optional[bool] = False
    guided_branches: Optional[Dict[str, Any]] = None
    branches: Optional[Dict[str, Any]] = None


class KnowledgeBaseResponse(BaseModel):
    id: str
    title: str
    content: str
    createdAt: str


@router.post("")
async def create_article(
    article: KnowledgeBaseArticle,
    current_user: dict = Depends(require_super_admin)
):
    """
    Create a new knowledge base article. Super_admin only. Scoped to organization.
    """
    try:
        db = get_db()
        organization_id = current_user.get("organization_id")
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization required to create articles")
        uid = current_user["uid"]
        # Resolve author display name from user doc
        user_doc = db.collection("users").document(uid).get()
        created_by_name = (user_doc.to_dict() or {}).get("full_name") or (user_doc.to_dict() or {}).get("email") or ""
        article_data = {
            "title": article.title,
            "content": article.content,
            "category": (article.category or "").strip() or None,
            "organization_id": organization_id,
            "created_by": uid,
            "created_by_name": created_by_name,
            "createdAt": datetime.utcnow().isoformat(),
        }
        if getattr(article, "type", None):
            article_data["type"] = article.type
        if getattr(article, "article_type", None):
            article_data["article_type"] = article.article_type
        if getattr(article, "trigger_phrases", None) is not None:
            article_data["trigger_phrases"] = article.trigger_phrases
        if getattr(article, "flow", None) is not None:
            article_data["flow"] = article.flow
        if article.guided_flow:
            article_data["guided_flow"] = True
            if article.guided_branches:
                article_data["guided_branches"] = article.guided_branches
            if article.branches:
                article_data["branches"] = article.branches
        doc_ref = db.collection("knowledge_base").add(article_data)
        article_id = doc_ref[1].id
        return {"message": "Article created successfully", "id": article_id, **article_data}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating article: {str(e)}")


@router.get("")
async def get_articles(current_user: dict = Depends(require_admin_or_above)):
    """
    Get knowledge base articles for the current organization (or all if legacy user).
    """
    try:
        db = get_db()
        organization_id = current_user.get("organization_id")
        if organization_id is not None:
            articles_ref = db.collection("knowledge_base").where("organization_id", "==", organization_id)
        else:
            articles_ref = db.collection("knowledge_base")
        articles = articles_ref.stream()
        result = []
        for doc in articles:
            article_data = doc.to_dict()
            result.append({
                "id": doc.id,
                "title": article_data.get("title"),
                "content": article_data.get("content"),
                "category": article_data.get("category"),
                "createdAt": article_data.get("createdAt"),
                "created_by": article_data.get("created_by"),
                "created_by_name": article_data.get("created_by_name") or "",
                "guided_flow": article_data.get("guided_flow", False),
                "guided_branches": article_data.get("guided_branches"),
                "branches": article_data.get("branches"),
                "type": article_data.get("type"),
                "article_type": article_data.get("article_type"),
                "trigger_phrases": article_data.get("trigger_phrases"),
                "flow": article_data.get("flow"),
            })
        result.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        if organization_id:
            try:
                log_activity(db, organization_id=organization_id, user_id=current_user["uid"], user_role=current_user.get("role") or "employee", action_type=ACTION_KNOWLEDGE_BASE_VIEW, action_label="Knowledge base view", metadata={"section": "list"})
            except Exception:
                pass
        return {"articles": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching articles: {str(e)}")


@router.put("/{article_id}")
async def update_article(
    article_id: str,
    article: KnowledgeBaseArticle,
    current_user: dict = Depends(require_super_admin)
):
    """
    Update a knowledge base article. Super_admin only. Must belong to current user's organization.
    """
    try:
        db = get_db()
        organization_id = current_user.get("organization_id")
        article_ref = db.collection("knowledge_base").document(article_id)
        article_doc = article_ref.get()
        if not article_doc.exists:
            raise HTTPException(status_code=404, detail="Article not found")
        existing_data = article_doc.to_dict()
        if organization_id is not None and existing_data.get("organization_id") != organization_id:
            raise HTTPException(status_code=403, detail="Article not in your organization")
        updates = {
            "title": article.title,
            "content": article.content,
            "updatedAt": datetime.utcnow().isoformat(),
            "createdAt": existing_data.get("createdAt", datetime.utcnow().isoformat()),
        }
        if article.category is not None:
            updates["category"] = (article.category or "").strip() or None
        if hasattr(article, "guided_flow") and article.guided_flow is not None:
            updates["guided_flow"] = article.guided_flow
        if hasattr(article, "guided_branches") and article.guided_branches is not None:
            updates["guided_branches"] = article.guided_branches
        if hasattr(article, "branches") and article.branches is not None:
            updates["branches"] = article.branches
        if hasattr(article, "type") and article.type is not None:
            updates["type"] = article.type
        if hasattr(article, "article_type") and article.article_type is not None:
            updates["article_type"] = article.article_type
        if hasattr(article, "trigger_phrases") and article.trigger_phrases is not None:
            updates["trigger_phrases"] = article.trigger_phrases
        if hasattr(article, "flow") and article.flow is not None:
            updates["flow"] = article.flow
        article_ref.update(updates)
        return {"message": "Article updated successfully", "id": article_id, "title": article.title, "content": article.content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating article: {str(e)}")


@router.post("/audit-and-convert")
async def audit_and_convert_articles(current_user: dict = Depends(require_super_admin)):
    """
    Part 1: Scan all KB articles; convert legacy/static content to guided flow format.
    Sets type=guided, trigger_phrases, flow on articles that were missing type or had type=static.
    """
    try:
        db = get_db()
        organization_id = current_user.get("organization_id")
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization required")
        ref = db.collection("knowledge_base").where("organization_id", "==", organization_id)
        converted = 0
        for doc in ref.stream():
            data = doc.to_dict()
            art_type = (data.get("type") or "").strip().lower()
            if art_type not in ("guided",) or not data.get("flow"):
                title = data.get("title", "")
                content = data.get("content", "")
                category = data.get("category", "")
                result = convert_legacy_content_to_flow(title, content, category)
                doc.reference.update({
                    "type": "guided",
                    "trigger_phrases": result.get("trigger_phrases", []),
                    "flow": result.get("flow", []),
                })
                converted += 1
        return {"message": "Audit complete", "converted_count": converted}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{article_id}")
async def delete_article(
    article_id: str,
    current_user: dict = Depends(require_super_admin)
):
    """
    Delete a knowledge base article. Must belong to current user's organization.
    """
    try:
        db = get_db()
        organization_id = current_user.get("organization_id")
        article_ref = db.collection("knowledge_base").document(article_id)
        article_doc = article_ref.get()
        if not article_doc.exists:
            raise HTTPException(status_code=404, detail="Article not found")
        if organization_id is not None and article_doc.to_dict().get("organization_id") != organization_id:
            raise HTTPException(status_code=403, detail="Article not in your organization")
        article_ref.delete()
        return {"message": "Article deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting article: {str(e)}")
