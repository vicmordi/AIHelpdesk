"""
Knowledge Base routes (Admin only)
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from firebase_admin import firestore
from middleware import verify_admin

# Get Firestore client
db = firestore.client()

router = APIRouter()


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
    decoded_token: dict = Depends(verify_admin)
):
    """
    Create a new knowledge base article (Admin only)
    """
    try:
        article_data = {
            "title": article.title,
            "content": article.content,
            "createdAt": datetime.utcnow().isoformat()
        }
        
        # Add to Firestore
        doc_ref = db.collection("knowledge_base").add(article_data)
        article_id = doc_ref[1].id
        
        return {
            "message": "Article created successfully",
            "id": article_id,
            **article_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating article: {str(e)}")


@router.get("")
async def get_articles(decoded_token: dict = Depends(verify_admin)):
    """
    Get all knowledge base articles (Admin only)
    """
    try:
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
        
        # Sort by createdAt descending (newest first)
        result.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        
        return {"articles": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching articles: {str(e)}")


@router.put("/{article_id}")
async def update_article(
    article_id: str,
    article: KnowledgeBaseArticle,
    decoded_token: dict = Depends(verify_admin)
):
    """
    Update a knowledge base article (Admin only)
    """
    try:
        article_ref = db.collection("knowledge_base").document(article_id)
        article_doc = article_ref.get()
        
        if not article_doc.exists:
            raise HTTPException(status_code=404, detail="Article not found")
        
        # Get existing data to preserve createdAt
        existing_data = article_doc.to_dict()
        
        # Update article with new data and add updatedAt
        article_ref.update({
            "title": article.title,
            "content": article.content,
            "updatedAt": datetime.utcnow().isoformat(),
            "createdAt": existing_data.get("createdAt", datetime.utcnow().isoformat())
        })
        
        return {
            "message": "Article updated successfully",
            "id": article_id,
            "title": article.title,
            "content": article.content
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating article: {str(e)}")


@router.delete("/{article_id}")
async def delete_article(
    article_id: str,
    decoded_token: dict = Depends(verify_admin)
):
    """
    Delete a knowledge base article (Admin only)
    """
    try:
        article_ref = db.collection("knowledge_base").document(article_id)
        article_doc = article_ref.get()
        
        if not article_doc.exists:
            raise HTTPException(status_code=404, detail="Article not found")
        
        article_ref.delete()
        return {"message": "Article deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting article: {str(e)}")
