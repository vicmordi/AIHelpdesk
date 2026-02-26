"""
Background scheduler for Knowledge Improvement analysis.
Runs analysis every 24 hours and optionally when 10 new resolved tickets are added.
Multi-tenant safe. Uses cluster_id hash to prevent duplicate suggestions.
"""

import logging
import os
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from firebase_admin import firestore

from knowledge_improvement import run_analysis_for_organization
from config import OPENAI_API_KEY
from openai import OpenAI

logger = logging.getLogger(__name__)

ANALYSIS_INTERVAL_HOURS = int(os.getenv("KB_ANALYSIS_INTERVAL_HOURS", "24"))
RESOLVED_THRESHOLD = int(os.getenv("KB_RESOLVED_THRESHOLD", "10"))


def get_db():
    return firestore.client()


def _get_all_organization_ids():
    """Fetch all organization IDs from Firestore (organizations collection)."""
    db = get_db()
    org_ids = set()
    try:
        for doc in db.collection("organizations").stream():
            org_ids.add(doc.id)
    except Exception as e:
        logger.warning("Failed to fetch organizations: %s", e)
    # Fallback: get org IDs from users (super_admin or support_admin)
    if not org_ids:
        try:
            users = db.collection("users").where("role", "in", ["super_admin", "support_admin"]).stream()
            for u in users:
                oid = u.to_dict().get("organization_id")
                if oid:
                    org_ids.add(oid)
        except Exception as e:
            logger.warning("Fallback org fetch failed: %s", e)
    return list(org_ids)


def run_scheduled_analysis():
    """
    Run knowledge improvement analysis for all organizations.
    Called by APScheduler every 24 hours. Never auto-publishes.
    """
    if not OPENAI_API_KEY:
        logger.debug("OpenAI not configured, skipping scheduled analysis")
        return
    org_ids = _get_all_organization_ids()
    if not org_ids:
        return
    client = OpenAI(api_key=OPENAI_API_KEY)
    for org_id in org_ids:
        try:
            result = run_analysis_for_organization(org_id, client)
            logger.info(
                "Scheduled KI analysis org=%s: new_drafts=%d, clusters=%d",
                org_id, len(result.get("new_drafts", [])), result.get("clusters_processed", 0),
            )
        except Exception as e:
            logger.exception("Scheduled KI analysis failed for org %s: %s", org_id, e)


def maybe_run_analysis_on_resolution(organization_id: str) -> None:
    """
    Check if we should trigger analysis due to 10 new resolved tickets.
    Uses knowledge_analysis_state to track resolved count at last run.
    Prevents duplicate suggestions via cluster_id in run_analysis_for_organization.
    """
    if not OPENAI_API_KEY or not organization_id:
        return
    db = get_db()
    state_ref = db.collection("knowledge_analysis_state").document(organization_id)
    state_doc = state_ref.get()
    resolved_count_at_last_run = 0
    if state_doc.exists:
        resolved_count_at_last_run = state_doc.to_dict().get("resolved_count_at_last_run") or 0
    # Count current resolved tickets
    resolved_ref = (
        db.collection("tickets")
        .where("organization_id", "==", organization_id)
        .where("status", "in", ["closed", "resolved", "auto_resolved"])
    )
    current_resolved = sum(1 for _ in resolved_ref.stream())
    new_since_last = current_resolved - resolved_count_at_last_run
    if new_since_last >= RESOLVED_THRESHOLD:
        try:
            client = OpenAI(api_key=OPENAI_API_KEY)
            run_analysis_for_organization(organization_id, client)
            # Update resolved count so we don't re-trigger until 10 more
            state_ref.set({
                "organization_id": organization_id,
                "resolved_count_at_last_run": current_resolved,
                "last_analysis_run": datetime.utcnow().isoformat(),
                "trigger": "resolved_threshold",
            }, merge=True)
            logger.info(
                "KI analysis triggered by threshold org=%s: %d new resolved",
                organization_id, new_since_last,
            )
        except Exception as e:
            logger.exception("Threshold-triggered KI analysis failed for org %s: %s", organization_id, e)


def start_scheduler():
    """Start the background scheduler. Called from main.py on startup."""
    if not OPENAI_API_KEY:
        logger.info("OpenAI not configured, skipping KI background scheduler")
        return
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_scheduled_analysis,
        "interval",
        hours=ANALYSIS_INTERVAL_HOURS,
        id="knowledge_improvement",
    )
    scheduler.start()
    logger.info("Knowledge Improvement scheduler started (interval=%dh)", ANALYSIS_INTERVAL_HOURS)
