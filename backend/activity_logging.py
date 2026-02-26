"""
Enterprise activity logging — Firestore activity_logs collection.
Schema: organization_id, user_id, user_name, user_role, action_type, action_label,
metadata (page, ticket_id, ip_address, device, user_agent, clicked_button, attempted_email),
created_at (serverTimestamp).
Multi-tenant: every log has organization_id when known. No passwords or message bodies.
"""

import logging
from typing import Any, Dict, Optional

from firebase_admin import firestore
from firebase_admin.firestore import SERVER_TIMESTAMP

logger = logging.getLogger(__name__)

# —— Action types (enterprise + legacy for backward compatibility) ——
ACTION_LOGIN_SUCCESS = "login_success"
ACTION_LOGIN_FAILED = "login_failed"
ACTION_BRUTE_FORCE_ATTEMPT = "brute_force_attempt"
ACTION_TICKET_SUBMITTED = "ticket_submitted"
ACTION_TICKET_ESCALATED = "ticket_escalated"
ACTION_TICKET_RESOLVED = "ticket_resolved"
ACTION_PAGE_CLICK = "page_click"
ACTION_BUTTON_CLICK = "button_click"
# Legacy aliases (still accepted and stored)
ACTION_LOGIN = "login"
ACTION_DASHBOARD_VIEW = "dashboard_view"
ACTION_TICKET_SUBMISSION = "ticket_submission"
ACTION_TICKET_ESCALATION = "ticket_escalation"
ACTION_TICKET_RESOLUTION = "ticket_resolution"
ACTION_KNOWLEDGE_BASE_VIEW = "knowledge_base_view"
ACTION_NAVIGATION = "navigation"

ALLOWED_ACTION_TYPES = frozenset({
    ACTION_LOGIN_SUCCESS,
    ACTION_LOGIN_FAILED,
    ACTION_BRUTE_FORCE_ATTEMPT,
    ACTION_TICKET_SUBMITTED,
    ACTION_TICKET_ESCALATED,
    ACTION_TICKET_RESOLVED,
    ACTION_PAGE_CLICK,
    ACTION_BUTTON_CLICK,
    ACTION_LOGIN,
    ACTION_DASHBOARD_VIEW,
    ACTION_TICKET_SUBMISSION,
    ACTION_TICKET_ESCALATION,
    ACTION_TICKET_RESOLUTION,
    ACTION_KNOWLEDGE_BASE_VIEW,
    ACTION_NAVIGATION,
})

# Metadata keys we allow (no sensitive data)
ALLOWED_METADATA_KEYS = frozenset({
    "page", "ticket_id", "article_id", "section",
    "ip_address", "device", "user_agent", "clicked_button", "attempted_email",
})


def _sanitize_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Only allow safe, non-sensitive keys for storage."""
    if not metadata or not isinstance(metadata, dict):
        return {}
    return {
        k: (str(v)[:500] if v is not None else None)
        for k, v in metadata.items()
        if k in ALLOWED_METADATA_KEYS and v is not None
    }


def log_activity(
    db,
    organization_id: str,
    user_id: str,
    user_role: str,
    action_type: str,
    action_label: str,
    metadata: Optional[Dict[str, Any]] = None,
    *,
    user_name: Optional[str] = None,
) -> None:
    """
    Append one activity log to Firestore activity_logs.
    Uses server timestamp for created_at. Fails silently so app flow is never broken.
    organization_id/user_id may be empty for login_failed/brute_force when user is unknown.
    """
    if not action_type:
        return
    if action_type not in ALLOWED_ACTION_TYPES:
        logger.warning("activity_logging: unknown action_type=%s", action_type)
        return
    # For login_failed / brute_force we allow missing org/user
    org_id = (organization_id or "").strip()
    uid = (user_id or "").strip()
    try:
        payload = {
            "organization_id": org_id or "",
            "user_id": uid or "",
            "user_name": (user_name or "").strip()[:256] or "",
            "user_role": (user_role or "employee").strip() or "employee",
            "action_type": action_type,
            "action_label": (action_label or "").strip()[:500] or action_type,
            "metadata": _sanitize_metadata(metadata),
            "created_at": SERVER_TIMESTAMP,
        }
        db.collection("activity_logs").add(payload)
    except Exception as e:
        logger.exception("activity_logging: failed to write log: %s", e)
