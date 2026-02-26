"""
User activity logging — Firestore activity_logs collection.
Multi-tenant: every log has organization_id. No sensitive data (no passwords, message bodies).
"""

import logging
from typing import Any, Dict, Optional

from firebase_admin import firestore
from firebase_admin.firestore import SERVER_TIMESTAMP

logger = logging.getLogger(__name__)

# Action types for analytics grouping
ACTION_LOGIN = "login"
ACTION_DASHBOARD_VIEW = "dashboard_view"
ACTION_TICKET_SUBMISSION = "ticket_submission"
ACTION_TICKET_ESCALATION = "ticket_escalation"
ACTION_TICKET_RESOLUTION = "ticket_resolution"
ACTION_KNOWLEDGE_BASE_VIEW = "knowledge_base_view"
ACTION_NAVIGATION = "navigation"

ALLOWED_ACTION_TYPES = frozenset({
    ACTION_LOGIN,
    ACTION_DASHBOARD_VIEW,
    ACTION_TICKET_SUBMISSION,
    ACTION_TICKET_ESCALATION,
    ACTION_TICKET_RESOLUTION,
    ACTION_KNOWLEDGE_BASE_VIEW,
    ACTION_NAVIGATION,
})


def _sanitize_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Only allow safe, non-sensitive keys for storage."""
    if not metadata or not isinstance(metadata, dict):
        return {}
    allowed_keys = frozenset({"ticket_id", "page", "article_id", "section"})
    return {k: v for k, v in metadata.items() if k in allowed_keys and v is not None}


def log_activity(
    db,
    organization_id: str,
    user_id: str,
    user_role: str,
    action_type: str,
    action_label: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Append one activity log to Firestore activity_logs.
    Uses server timestamp for created_at. Fails silently so app flow is never broken.
    """
    if not organization_id or not user_id or not action_type:
        return
    if action_type not in ALLOWED_ACTION_TYPES:
        logger.warning("activity_logging: unknown action_type=%s", action_type)
        return
    try:
        payload = {
            "organization_id": organization_id,
            "user_id": user_id,
            "user_role": (user_role or "employee").strip() or "employee",
            "action_type": action_type,
            "action_label": (action_label or "").strip()[:500] or action_type,
            "metadata": _sanitize_metadata(metadata),
            "created_at": SERVER_TIMESTAMP,
        }
        db.collection("activity_logs").add(payload)
    except Exception as e:
        logger.exception("activity_logging: failed to write log: %s", e)
