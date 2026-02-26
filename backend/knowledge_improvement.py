"""
Automatic Knowledge Improvement System.
Analyzes resolved tickets, clusters by semantic similarity, and generates KB draft suggestions.
Decision-aware: does not regenerate rejected or already-covered topics.
Multi-tenant safe. Never auto-publishes. Uses only ticket content and resolution data.
"""

import hashlib
import logging
import os
import math
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

from openai import OpenAI
from firebase_admin import firestore
from firebase_admin.firestore import SERVER_TIMESTAMP

from config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

# Config
SIMILARITY_THRESHOLD = float(os.getenv("KB_SIMILARITY_THRESHOLD", "0.85"))
CLUSTER_MIN_SIZE = int(os.getenv("KB_CLUSTER_MIN_SIZE", "3"))
RESOLVED_DAYS_WINDOW = int(os.getenv("KB_RESOLVED_DAYS", "30"))
KB_EXISTING_SIMILARITY_THRESHOLD = float(os.getenv("KB_EXISTING_SIMILARITY_THRESHOLD", "0.88"))
EMBEDDING_MODEL = "text-embedding-3-small"

# Stopwords for topic normalization (lowercase)
_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "by", "from", "as", "is", "was", "are", "were", "been", "be", "have", "has", "had",
    "do", "does", "did", "will", "would", "could", "should", "may", "might", "must",
    "can", "this", "that", "these", "those", "it", "its", "i", "me", "my", "we", "our",
    "you", "your", "he", "she", "they", "them", "not", "no", "yes", "so", "if", "then",
})


def get_db():
    return firestore.client()


def _normalize_topic(raw: str) -> str:
    """
    Normalize a topic string for deterministic cluster_signature.
    Lowercase, remove punctuation, remove stopwords, basic stem (strip common suffixes).
    """
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    words = s.split()
    out = []
    for w in words:
        if not w or w in _STOPWORDS:
            continue
        # Basic stem: strip trailing s, ed, ing
        if len(w) > 3 and w.endswith("ing"):
            w = w[:-3]
        elif len(w) > 2 and w.endswith("ed"):
            w = w[:-2]
        elif len(w) > 1 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return " ".join(sorted(set(out)))  # sort for determinism


def _build_cluster_topic(cluster: List[Dict[str, Any]]) -> str:
    """Build a raw topic string from cluster ticket summaries (for normalization)."""
    parts = []
    for t in cluster[:5]:
        s = (t.get("summary") or t.get("message") or "")[:300]
        if s:
            parts.append(s)
    return " ".join(parts) if parts else "unknown"


def _cluster_signature(normalized_topic: str) -> str:
    """Deterministic fingerprint for a cluster topic. SHA256 of normalized_topic."""
    if not normalized_topic:
        return hashlib.sha256(b"unknown").hexdigest()[:32]
    return hashlib.sha256(normalized_topic.encode("utf-8")).hexdigest()[:32]


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
) -> List[Tuple[List[Dict[str, Any]], float]]:
    """
    Cluster tickets by embedding cosine similarity.
    Returns list of (cluster, avg_similarity) tuples. avg_similarity used as confidence_score.
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
    # Simple clustering: group by similarity (greedy), compute avg similarity per cluster
    clusters: List[Tuple[List[Dict[str, Any]], float]] = []
    used = set()
    for i, t1 in enumerate(with_emb):
        if t1.get("id") in used:
            continue
        cluster = [t1]
        sims = []
        used.add(t1.get("id"))
        e1 = t1["ticket_embedding"]
        for j, t2 in enumerate(with_emb):
            if i == j or t2.get("id") in used:
                continue
            sim = _cosine_similarity(e1, t2["ticket_embedding"])
            if sim >= threshold:
                cluster.append(t2)
                sims.append(sim)
                used.add(t2.get("id"))
        if len(cluster) >= min_size:
            avg_sim = sum(sims) / len(sims) if sims else threshold
            clusters.append((cluster, avg_sim))
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
Output valid JSON with keys: title (clean, concise), content (step-by-step solution), category (single word), tags (array of 3-5 strings), cluster_summary (one sentence describing the common issue pattern, max 100 chars)."""
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
            "cluster_summary": (data.get("cluster_summary") or "Recurring issue from resolved tickets")[:200],
        }
    except Exception as e:
        logger.warning("KB article generation failed: %s", e)
        return {
            "title": "Draft from resolved tickets",
            "content": "Review and edit this article. Generated from ticket patterns.",
            "category": "General",
            "tags": [],
            "cluster_summary": "Recurring issue from resolved tickets",
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


def _check_suggestion_by_cluster_signature(
    db, organization_id: str, cluster_signature: str
) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    """
    Check if we already have a suggestion with this cluster_signature.
    Returns (status, suggestion_id, decision_reason) if found, else None.
    status is one of: rejected, approved, draft.
    Requires Firestore composite index: organization_id (ASC), cluster_signature (ASC).
    """
    ref = (
        db.collection("knowledge_suggestions")
        .where("organization_id", "==", organization_id)
        .where("cluster_signature", "==", cluster_signature)
    )
    for doc in ref.limit(1).stream():
        d = doc.to_dict()
        status = d.get("status")
        if status == "rejected":
            return ("rejected", doc.id, d.get("decision_reason"))
        if status == "approved":
            return ("approved", doc.id, None)
        if status == "draft":
            return ("draft", doc.id, None)
    return None


def _check_suggestion_by_cluster_id(
    db, organization_id: str, cluster_id: str
) -> Optional[Tuple[str, Optional[str], Optional[str]]]:
    """
    Fallback: check by cluster_id (hash of ticket IDs).
    Older suggestions may not have cluster_signature; they always have cluster_id.
    Returns (status, suggestion_id, decision_reason) if found, else None.
    Ensures rejected suggestions are never recreated as drafts.
    """
    ref = (
        db.collection("knowledge_suggestions")
        .where("organization_id", "==", organization_id)
        .where("cluster_id", "==", cluster_id)
    )
    for doc in ref.limit(1).stream():
        d = doc.to_dict()
        status = d.get("status")
        if status == "rejected":
            return ("rejected", doc.id, d.get("decision_reason"))
        if status == "approved":
            return ("approved", doc.id, None)
        if status == "draft":
            return ("draft", doc.id, None)
    return None


def _check_kb_similarity(
    db,
    organization_id: str,
    cluster_embedding: List[float],
    openai_client: OpenAI,
    threshold: float = KB_EXISTING_SIMILARITY_THRESHOLD,
) -> Optional[Dict[str, Any]]:
    """
    Check if cluster topic is already covered by an existing KB article (embedding similarity).
    Returns { "id": article_id, "title": title } if match >= threshold, else None.
    Multi-tenant: only org's KB articles.
    """
    kb_ref = db.collection("knowledge_base").where("organization_id", "==", organization_id)
    best_score = 0.0
    best_article = None
    count = 0
    for doc in kb_ref.stream():
        count += 1
        if count > 100:  # Cap to avoid too many embeddings
            break
        d = doc.to_dict()
        title = d.get("title") or ""
        content = (d.get("content") or "")[:2000]
        text = f"{title}\n{content}".strip()
        if not text:
            continue
        emb = generate_embedding(text, openai_client)
        if not emb:
            continue
        score = _cosine_similarity(cluster_embedding, emb)
        if score >= threshold and score > best_score:
            best_score = score
            best_article = {"id": doc.id, "title": title or doc.id}
    return best_article


def run_analysis_for_organization(
    organization_id: str,
    openai_client: Optional[OpenAI] = None,
) -> Dict[str, Any]:
    """
    Main entry: analyze resolved tickets, cluster, generate drafts.
    Decision-aware: does not create drafts for previously rejected or already-covered topics.
    Multi-tenant safe. Never auto-publishes.
    Returns:
      new_drafts: list of newly created suggestion summaries
      previously_rejected: list of { cluster_signature, suggestion_id, decision_reason?, normalized_topic }
      already_existing_kb: list of { cluster_signature, linked_kb_id, title, normalized_topic }
      already_approved: list of { cluster_signature, suggestion_id, linked_kb_id }
      clusters_processed: int
    """
    db = get_db()
    client = openai_client or OpenAI(api_key=OPENAI_API_KEY)
    tickets = get_resolved_tickets(db, organization_id, RESOLVED_DAYS_WINDOW)
    logger.info("Knowledge improvement: org=%s, resolved tickets=%d", organization_id, len(tickets))
    clusters_with_sim = cluster_tickets_by_similarity(tickets, SIMILARITY_THRESHOLD, CLUSTER_MIN_SIZE, client)

    new_drafts: List[Dict[str, Any]] = []
    previously_rejected: List[Dict[str, Any]] = []
    already_existing_kb: List[Dict[str, Any]] = []
    already_approved: List[Dict[str, Any]] = []

    for cluster, avg_similarity in clusters_with_sim:
        ticket_ids = sorted([t.get("id") for t in cluster if t.get("id")])
        cluster_id = hashlib.sha256("|".join(ticket_ids).encode()).hexdigest()[:24]

        # Build topic and deterministic cluster_signature (for decision-aware dedup)
        raw_topic = _build_cluster_topic(cluster)
        normalized_topic = _normalize_topic(raw_topic)
        sig = _cluster_signature(normalized_topic)

        # 1) Check knowledge_suggestions by cluster_signature (topic-based dedup)
        existing = _check_suggestion_by_cluster_signature(db, organization_id, sig)
        # 2) Fallback: check by cluster_id so older/rejected suggestions (without cluster_signature) are not duplicated
        if existing is None:
            existing = _check_suggestion_by_cluster_id(db, organization_id, cluster_id)
        if existing:
            status, suggestion_id, decision_reason = existing
            if status == "rejected":
                previously_rejected.append({
                    "cluster_signature": sig,
                    "suggestion_id": suggestion_id,
                    "decision_reason": decision_reason,
                    "normalized_topic": normalized_topic[:200],
                    "ticket_count": len(ticket_ids),
                })
                continue
            if status == "approved":
                doc_ref = db.collection("knowledge_suggestions").document(suggestion_id)
                doc_snap = doc_ref.get()
                linked_kb = None
                if doc_snap.exists:
                    d = doc_snap.to_dict()
                    linked_kb = d.get("published_article_id") or d.get("linked_kb_id")
                already_approved.append({
                    "cluster_signature": sig,
                    "suggestion_id": suggestion_id,
                    "linked_kb_id": linked_kb,
                    "normalized_topic": normalized_topic[:200],
                    "ticket_count": len(ticket_ids),
                })
                continue
            if status == "draft":
                continue  # Already have a draft for this topic

        # 2) Check knowledge_base by embedding similarity
        cluster_text = raw_topic[:4000]
        cluster_emb = generate_embedding(cluster_text, client)
        if cluster_emb:
            kb_match = _check_kb_similarity(db, organization_id, cluster_emb, client)
            if kb_match:
                already_existing_kb.append({
                    "cluster_signature": sig,
                    "linked_kb_id": kb_match["id"],
                    "title": kb_match.get("title", ""),
                    "normalized_topic": normalized_topic[:200],
                    "ticket_count": len(ticket_ids),
                })
                continue

        # 4) Only create new draft if cluster_signature (and cluster_id) do NOT exist in suggestions
        if check_cluster_already_suggested(db, organization_id, cluster_id):
            continue
        article = _generate_kb_article_from_cluster(cluster, client)
        confidence_score = min(100, max(0, int(avg_similarity * 100)))
        doc_data = {
            "organization_id": organization_id,
            "cluster_id": cluster_id,
            "cluster_signature": sig,
            "normalized_topic": normalized_topic[:500],
            "ticket_ids": ticket_ids,
            "related_ticket_ids": ticket_ids,
            "ticket_count": len(ticket_ids),
            "title": article["title"],
            "content": article["content"],
            "generated_draft": article["content"],
            "category": article["category"],
            "tags": article.get("tags") or [],
            "cluster_summary": article.get("cluster_summary") or "Recurring issue from resolved tickets",
            "confidence_score": confidence_score,
            "status": "draft",
            "decision_reason": None,
            "linked_kb_id": None,
            "created_at": datetime.utcnow().isoformat(),
            "reviewed_at": None,
            "reviewed_by": None,
        }
        db.collection("knowledge_suggestions").add(doc_data)
        new_drafts.append({
            "title": article["title"],
            "cluster_signature": sig,
            "ticket_count": len(ticket_ids),
            "confidence_score": confidence_score,
        })
        logger.info("Created KB suggestion: title=%s, cluster_size=%d, confidence=%d", article["title"], len(cluster), confidence_score)

    _update_analysis_metadata(db, organization_id, len(clusters_with_sim), new_drafts, previously_rejected, already_existing_kb, already_approved)
    return {
        "new_drafts": new_drafts,
        "previously_rejected": previously_rejected,
        "already_existing_kb": already_existing_kb,
        "already_approved": already_approved,
        "clusters_processed": len(clusters_with_sim),
    }


def _update_analysis_metadata(
    db,
    organization_id: str,
    recurring_issues_detected: int,
    new_drafts: Optional[List[Dict[str, Any]]] = None,
    previously_rejected: Optional[List[Dict[str, Any]]] = None,
    already_existing_kb: Optional[List[Dict[str, Any]]] = None,
    already_approved: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Store last analysis run timestamp, counts, and last run result for frontend."""
    resolved_ref = (
        db.collection("tickets")
        .where("organization_id", "==", organization_id)
        .where("status", "in", ["closed", "resolved", "auto_resolved"])
    )
    resolved_count = sum(1 for _ in resolved_ref.stream())
    ref = db.collection("knowledge_analysis_state").document(organization_id)
    payload = {
        "organization_id": organization_id,
        "last_analysis_run": SERVER_TIMESTAMP,
        "recurring_issues_detected": recurring_issues_detected,
        "resolved_count_at_last_run": resolved_count,
        "updated_at": SERVER_TIMESTAMP,
    }
    if new_drafts is not None:
        payload["last_run_new_drafts"] = new_drafts
    if previously_rejected is not None:
        payload["last_run_previously_rejected"] = previously_rejected
    if already_existing_kb is not None:
        payload["last_run_already_existing_kb"] = already_existing_kb
    if already_approved is not None:
        payload["last_run_already_approved"] = already_approved
    ref.set(payload, merge=True)


def get_suggestion_by_id(db, suggestion_id: str, organization_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a single suggestion by ID with related ticket details.
    Multi-tenant: enforces organization_id.
    Returns full suggestion + related_tickets array (ticket_id, title, description, resolution, status, created_at).
    """
    ref = db.collection("knowledge_suggestions").document(suggestion_id)
    doc = ref.get()
    if not doc.exists:
        return None
    d = doc.to_dict()
    if d.get("organization_id") != organization_id:
        return None
    d["id"] = doc.id
    ticket_ids = d.get("ticket_ids") or d.get("related_ticket_ids") or []
    # Fetch related tickets from Firestore
    related_tickets = []
    for tid in ticket_ids:
        t_ref = db.collection("tickets").document(tid)
        t_doc = t_ref.get()
        if not t_doc.exists:
            related_tickets.append({
                "ticket_id": tid,
                "title": "",
                "description": "",
                "resolution": "",
                "status": "unknown",
                "created_at": None,
            })
            continue
        td = t_doc.to_dict()
        if td.get("organization_id") != organization_id:
            continue
        resolution = _extract_resolution_from_ticket(td)
        created_str = td.get("createdAt") or td.get("created_at") or ""
        related_tickets.append({
            "ticket_id": tid,
            "title": (td.get("summary") or td.get("message") or "")[:200],
            "description": (td.get("message") or td.get("summary") or "")[:1000],
            "resolution": resolution[:2000] if resolution else "",
            "status": td.get("status") or "unknown",
            "created_at": created_str,
        })
    d["related_tickets"] = related_tickets
    d["related_ticket_ids"] = ticket_ids
    return d


def update_suggestion(
    db,
    suggestion_id: str,
    organization_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Update draft suggestion (Edit Draft). Only draft status can be edited."""
    ref = db.collection("knowledge_suggestions").document(suggestion_id)
    doc = ref.get()
    if not doc.exists:
        return {"ok": False, "error": "Suggestion not found"}
    d = doc.to_dict()
    if d.get("organization_id") != organization_id:
        return {"ok": False, "error": "Not your organization"}
    if d.get("status") != "draft":
        return {"ok": False, "error": f"Cannot edit suggestion with status {d.get('status')}"}
    updates = {"updated_at": datetime.utcnow().isoformat()}
    if title is not None:
        updates["title"] = title[:200]
    if content is not None:
        updates["content"] = content[:50000]
    if category is not None:
        updates["category"] = category[:128]
    ref.update(updates)
    return {"ok": True}


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
        "linked_kb_id": kb_ref.id,  # alias for frontend / already-covered linking
    })
    return {"ok": True, "article_id": kb_ref.id}


def reject_suggestion(
    db, suggestion_id: str, organization_id: str, reviewer_uid: str, decision_reason: Optional[str] = None
) -> Dict[str, Any]:
    """Reject suggestion. Optionally store decision_reason for decision-aware dedup."""
    ref = db.collection("knowledge_suggestions").document(suggestion_id)
    doc = ref.get()
    if not doc.exists:
        return {"ok": False, "error": "Suggestion not found"}
    d = doc.to_dict()
    if d.get("organization_id") != organization_id:
        return {"ok": False, "error": "Not your organization"}
    if d.get("status") != "draft":
        return {"ok": False, "error": f"Suggestion already {d.get('status')}"}
    updates = {
        "status": "rejected",
        "reviewed_at": datetime.utcnow().isoformat(),
        "reviewed_by": reviewer_uid,
    }
    if decision_reason is not None:
        updates["decision_reason"] = decision_reason[:1000]
    ref.update(updates)
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
    # Fetch last analysis metadata
    meta_ref = db.collection("knowledge_analysis_state").document(organization_id)
    meta_doc = meta_ref.get()
    last_analysis_run = None
    recurring_issues_detected = 0
    last_run_new_drafts = []
    last_run_previously_rejected = []
    last_run_already_existing_kb = []
    last_run_already_approved = []
    if meta_doc.exists:
        meta = meta_doc.to_dict()
        raw_last = meta.get("last_analysis_run")
        # Serialize for API: Firestore Timestamp -> {seconds, nanoseconds}; datetime -> same; str (legacy) -> as-is
        if raw_last is not None:
            if hasattr(raw_last, "seconds"):
                last_analysis_run = {"seconds": raw_last.seconds, "nanoseconds": getattr(raw_last, "nanoseconds", 0)}
            elif hasattr(raw_last, "timestamp"):
                s = int(raw_last.timestamp())
                last_analysis_run = {"seconds": s, "nanoseconds": 0}
            else:
                last_analysis_run = raw_last  # legacy ISO string
        recurring_issues_detected = meta.get("recurring_issues_detected") or 0
        last_run_new_drafts = meta.get("last_run_new_drafts") or []
        last_run_previously_rejected = meta.get("last_run_previously_rejected") or []
        last_run_already_existing_kb = meta.get("last_run_already_existing_kb") or meta.get("last_run_already_existing") or []
        last_run_already_approved = meta.get("last_run_already_approved") or []
    return {
        "recurring_issues_this_month": resolved_count,
        "suggested_articles_pending": draft_count,
        "last_analysis_run": last_analysis_run,
        "recurring_issues_detected": recurring_issues_detected,
        "last_run_new_drafts": last_run_new_drafts,
        "last_run_previously_rejected": last_run_previously_rejected,
        "last_run_already_existing_kb": last_run_already_existing_kb,
        "last_run_already_approved": last_run_already_approved,
    }
