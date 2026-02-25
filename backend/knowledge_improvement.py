"""
Automatic Knowledge Improvement System.
Analyzes resolved tickets, clusters by semantic similarity, and generates KB draft suggestions.
Multi-tenant safe. Never auto-publishes. Uses only ticket content and resolution data.
"""

import hashlib
import logging
import os
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from openai import OpenAI
from firebase_admin import firestore

from config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

# Config
SIMILARITY_THRESHOLD = float(os.getenv("KB_SIMILARITY_THRESHOLD", "0.85"))
CLUSTER_MIN_SIZE = int(os.getenv("KB_CLUSTER_MIN_SIZE", "3"))
RESOLVED_DAYS_WINDOW = int(os.getenv("KB_RESOLVED_DAYS", "30"))
EMBEDDING_MODEL = "text-embedding-3-small"


def get_db():
    return firestore.client()


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors. Pure Python, no numpy."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _build_ticket_text(ticket: Dict[str, Any]) -> str:
    """Build searchable text from ticket: summary, message, resolution messages. No external knowledge."""
    parts = []
    if ticket.get("summary"):
        parts.append(str(ticket["summary"]))
    if ticket.get("message"):
        parts.append(str(ticket["message"]))
    messages = ticket.get("messages") or []
    for m in messages:
        msg = m.get("message", "")
        sender = (m.get("sender") or "").lower()
        if msg and sender in ("admin", "ai"):
            parts.append(msg)
    return "\n".join(parts).strip() or "No content"


def generate_embedding(text: str, client: Optional[OpenAI] = None) -> Optional[List[float]]:
    """Generate embedding for text using OpenAI. Returns None on error."""
    if not OPENAI_API_KEY or not text.strip():
        return None
    try:
        c = client or OpenAI(api_key=OPENAI_API_KEY)
        r = c.embeddings.create(
            input=text.strip()[:8000],
            model=EMBEDDING_MODEL,
        )
        return r.data[0].embedding
    except Exception as e:
        logger.warning("Embedding generation failed: %s", e)
        return None


def get_resolved_tickets(
    db,
    organization_id: str,
    days: int = RESOLVED_DAYS_WINDOW,
) -> List[Dict[str, Any]]:
    """Fetch resolved/closed tickets for org in last N days. Multi-tenant safe."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    ref = (
        db.collection("tickets")
        .where("organization_id", "==", organization_id)
        .where("status", "in", ["closed", "resolved", "auto_resolved"])
    )
    tickets = []
    for doc in ref.stream():
        d = doc.to_dict()
        created_str = d.get("createdAt") or d.get("created_at") or ""
        try:
            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00")) if created_str else datetime.min
        except Exception:
            created_dt = datetime.min
        if created_dt >= cutoff:
            d["id"] = doc.id
            tickets.append(d)
    tickets.sort(key=lambda t: (t.get("createdAt") or t.get("created_at") or ""), reverse=True)
    return tickets


def _extract_resolution_from_ticket(ticket: Dict[str, Any]) -> str:
    """Extract resolution steps from admin/AI messages. No external knowledge."""
    messages = ticket.get("messages") or []
    resolution_parts = []
    for m in messages:
        sender = (m.get("sender") or "").lower()
        msg = m.get("message", "")
        if sender in ("admin", "ai") and msg:
            resolution_parts.append(msg)
    return "\n\n".join(resolution_parts) if resolution_parts else ""


def cluster_tickets_by_similarity(
    tickets: List[Dict[str, Any]],
    threshold: float = SIMILARITY_THRESHOLD,
    min_size: int = CLUSTER_MIN_SIZE,
    openai_client: Optional[OpenAI] = None,
) -> List[List[Dict[str, Any]]]:
    """
    Cluster tickets by embedding cosine similarity.
    Returns list of clusters; each cluster is a list of tickets.
    """
    if len(tickets) < min_size:
        return []
    client = openai_client or OpenAI(api_key=OPENAI_API_KEY)
    # Generate embeddings for tickets that don't have one
    for t in tickets:
        if not t.get("ticket_embedding"):
            text = _build_ticket_text(t)
            emb = generate_embedding(text, client)
            if emb:
                t["ticket_embedding"] = emb
    # Filter tickets with embeddings
    with_emb = [t for t in tickets if t.get("ticket_embedding")]
    if len(with_emb) < min_size:
        return []
    # Simple clustering: group by similarity (greedy)
    clusters: List[List[Dict[str, Any]]] = []
    used = set()
    for i, t1 in enumerate(with_emb):
        if t1.get("id") in used:
            continue
        cluster = [t1]
        used.add(t1.get("id"))
        e1 = t1["ticket_embedding"]
        for j, t2 in enumerate(with_emb):
            if i == j or t2.get("id") in used:
                continue
            sim = _cosine_similarity(e1, t2["ticket_embedding"])
            if sim >= threshold:
                cluster.append(t2)
                used.add(t2.get("id"))
        if len(cluster) >= min_size:
            clusters.append(cluster)
    return clusters


def _generate_kb_article_from_cluster(
    cluster: List[Dict[str, Any]],
    openai_client: OpenAI,
) -> Dict[str, Any]:
    """Use OpenAI to generate structured KB article from ticket cluster. Uses only ticket content."""
    summaries = []
    resolutions = []
    for t in cluster[:10]:  # Cap for token limit
        s = t.get("summary") or t.get("message") or ""
        if s:
            summaries.append(s[:500])
        r = _extract_resolution_from_ticket(t)
        if r:
            resolutions.append(r[:800])
    combined = "---ISSUES---\n" + "\n".join(summaries) + "\n---RESOLUTIONS---\n" + "\n".join(resolutions)
    system = """You are a knowledge base writer. Generate a structured IT helpdesk article from resolved ticket data.
Use ONLY the provided ticket content. Do not add external knowledge.
Output valid JSON with keys: title (clean, concise), content (step-by-step solution), category (single word), tags (array of 3-5 strings)."""
    try:
        r = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": combined[:6000]},
            ],
            temperature=0.3,
            max_tokens=1500,
        )
        import json
        raw = (r.choices[0].message.content or "").strip()
        # Extract JSON from markdown code block if present
        if "```" in raw:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            raw = raw[start:end] if start >= 0 and end > start else raw
        data = json.loads(raw)
        return {
            "title": (data.get("title") or "Untitled")[:200],
            "content": (data.get("content") or "")[:50000],
            "category": (data.get("category") or "General")[:128],
            "tags": data.get("tags") or [],
        }
    except Exception as e:
        logger.warning("KB article generation failed: %s", e)
        return {
            "title": "Draft from resolved tickets",
            "content": "Review and edit this article. Generated from ticket patterns.",
            "category": "General",
            "tags": [],
        }


def check_cluster_already_suggested(db, organization_id: str, cluster_id: str) -> bool:
    """Return True if we already have a suggestion for this cluster (draft or approved)."""
    ref = (
        db.collection("knowledge_suggestions")
        .where("organization_id", "==", organization_id)
        .where("cluster_id", "==", cluster_id)
    )
    for doc in ref.limit(1).stream():
        d = doc.to_dict()
        if d.get("status") in ("draft", "approved"):
            return True
    return False


def run_analysis_for_organization(
    organization_id: str,
    openai_client: Optional[OpenAI] = None,
) -> Dict[str, Any]:
    """
    Main entry: analyze resolved tickets, cluster, generate drafts.
    Multi-tenant safe. Never auto-publishes.
    Returns { created: int, clusters_processed: int, suggestions: [...] }.
    """
    db = get_db()
    client = openai_client or OpenAI(api_key=OPENAI_API_KEY)
    tickets = get_resolved_tickets(db, organization_id, RESOLVED_DAYS_WINDOW)
    logger.info("Knowledge improvement: org=%s, resolved tickets=%d", organization_id, len(tickets))
    clusters = cluster_tickets_by_similarity(tickets, SIMILARITY_THRESHOLD, CLUSTER_MIN_SIZE, client)
    created = 0
    suggestions = []
    for cluster in clusters:
        ticket_ids = sorted([t.get("id") for t in cluster if t.get("id")])
        cluster_id = hashlib.sha256("|".join(ticket_ids).encode()).hexdigest()[:24]
        if check_cluster_already_suggested(db, organization_id, cluster_id):
            continue
        article = _generate_kb_article_from_cluster(cluster, client)
        doc_data = {
            "organization_id": organization_id,
            "cluster_id": cluster_id,
            "ticket_ids": ticket_ids,
            "ticket_count": len(ticket_ids),
            "title": article["title"],
            "content": article["content"],
            "category": article["category"],
            "tags": article.get("tags") or [],
            "status": "draft",
            "created_at": datetime.utcnow().isoformat(),
            "reviewed_at": None,
            "reviewed_by": None,
        }
        db.collection("knowledge_suggestions").add(doc_data)
        created += 1
        suggestions.append({**doc_data, "ticket_ids": ticket_ids})
        logger.info("Created KB suggestion: title=%s, cluster_size=%d", article["title"], len(cluster))
    return {
        "created": created,
        "clusters_processed": len(clusters),
        "suggestions": suggestions,
    }


def get_suggestions(db, organization_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
    """List knowledge suggestions for org. status: draft|approved|rejected|all."""
    ref = db.collection("knowledge_suggestions").where("organization_id", "==", organization_id)
    if status and status != "all":
        ref = ref.where("status", "==", status)
    out = []
    for doc in ref.stream():
        d = doc.to_dict()
        d["id"] = doc.id
        out.append(d)
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out[:50]


def approve_suggestion(db, suggestion_id: str, organization_id: str, reviewer_uid: str) -> Dict[str, Any]:
    """Approve suggestion: publish to knowledge_base, mark as approved."""
    ref = db.collection("knowledge_suggestions").document(suggestion_id)
    doc = ref.get()
    if not doc.exists:
        return {"ok": False, "error": "Suggestion not found"}
    d = doc.to_dict()
    if d.get("organization_id") != organization_id:
        return {"ok": False, "error": "Not your organization"}
    if d.get("status") != "draft":
        return {"ok": False, "error": f"Suggestion already {d.get('status')}"}
    # Create KB article
    article_data = {
        "title": d.get("title") or "Untitled",
        "content": d.get("content") or "",
        "category": d.get("category"),
        "organization_id": organization_id,
        "created_by": reviewer_uid,
        "created_by_name": "KB Improvement (auto)",
        "createdAt": datetime.utcnow().isoformat(),
        "source": "knowledge_improvement",
        "source_suggestion_id": suggestion_id,
    }
    _, kb_ref = db.collection("knowledge_base").add(article_data)
    ref.update({
        "status": "approved",
        "reviewed_at": datetime.utcnow().isoformat(),
        "reviewed_by": reviewer_uid,
        "published_article_id": kb_ref.id,
    })
    return {"ok": True, "article_id": kb_ref.id}


def reject_suggestion(db, suggestion_id: str, organization_id: str, reviewer_uid: str) -> Dict[str, Any]:
    """Reject suggestion."""
    ref = db.collection("knowledge_suggestions").document(suggestion_id)
    doc = ref.get()
    if not doc.exists:
        return {"ok": False, "error": "Suggestion not found"}
    d = doc.to_dict()
    if d.get("organization_id") != organization_id:
        return {"ok": False, "error": "Not your organization"}
    if d.get("status") != "draft":
        return {"ok": False, "error": f"Suggestion already {d.get('status')}"}
    ref.update({
        "status": "rejected",
        "reviewed_at": datetime.utcnow().isoformat(),
        "reviewed_by": reviewer_uid,
    })
    return {"ok": True}


def get_analytics(db, organization_id: str) -> Dict[str, Any]:
    """Dashboard widgets: recurring issues (30 days), suggested articles pending."""
    cutoff = datetime.utcnow() - timedelta(days=RESOLVED_DAYS_WINDOW)
    resolved_ref = (
        db.collection("tickets")
        .where("organization_id", "==", organization_id)
        .where("status", "in", ["closed", "resolved", "auto_resolved"])
    )
    resolved_count = 0
    for doc in resolved_ref.stream():
        d = doc.to_dict()
        created_str = d.get("createdAt") or d.get("created_at") or ""
        try:
            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00")) if created_str else datetime.min
        except Exception:
            created_dt = datetime.min
        if created_dt >= cutoff:
            resolved_count += 1
    suggestions_ref = (
        db.collection("knowledge_suggestions")
        .where("organization_id", "==", organization_id)
        .where("status", "==", "draft")
    )
    draft_count = sum(1 for _ in suggestions_ref.stream())
    return {
        "recurring_issues_this_month": resolved_count,
        "suggested_articles_pending": draft_count,
    }
