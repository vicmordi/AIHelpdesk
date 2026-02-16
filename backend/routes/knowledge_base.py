"""
Knowledge Base routes (Admin only)
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from firebase_admin import firestore
from middleware import require_admin_or_above

router = APIRouter()


def get_db():
    """Lazy initialization of Firestore client"""
    return firestore.client()


class KnowledgeBaseArticle(BaseModel):
    title: str
    content: str


class KnowledgeBaseResponse(BaseModel):
    id: str
    title: str
    content: str
    createdAt: str


@router.post("")
async def create_article(
    article: KnowledgeBaseArticle,
    current_user: dict = Depends(require_admin_or_above)
):
    """
    Create a new knowledge base article. Scoped to current user's organization.
    """
    try:
        db = get_db()
        organization_id = current_user.get("organization_id")
        if organization_id is None:
            raise HTTPException(status_code=400, detail="Organization required to create articles")
        uid = current_user["uid"]
        article_data = {
            "title": article.title,
            "content": article.content,
            "organization_id": organization_id,
            "created_by": uid,
            "createdAt": datetime.utcnow().isoformat(),
        }
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
                "createdAt": article_data.get("createdAt")
            })
        result.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return {"articles": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching articles: {str(e)}")


@router.put("/{article_id}")
async def update_article(
    article_id: str,
    article: KnowledgeBaseArticle,
    current_user: dict = Depends(require_admin_or_above)
):
    """
    Update a knowledge base article. Must belong to current user's organization.
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
        article_ref.update({
            "title": article.title,
            "content": article.content,
            "updatedAt": datetime.utcnow().isoformat(),
            "createdAt": existing_data.get("createdAt", datetime.utcnow().isoformat())
        })
        return {"message": "Article updated successfully", "id": article_id, "title": article.title, "content": article.content}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating article: {str(e)}")


@router.delete("/{article_id}")
async def delete_article(
    article_id: str,
    current_user: dict = Depends(require_admin_or_above)
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
