"""
Analytics routes: activity logging (POST) and activity summary (GET).
Multi-tenant: activity-summary scoped to current user's organization.
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from firebase_admin import firestore
from middleware import get_current_user, require_super_admin
from activity_logging import (
    log_activity,
    ACTION_LOGIN,
    ACTION_DASHBOARD_VIEW,
    ACTION_TICKET_SUBMISSION,
    ACTION_TICKET_ESCALATION,
    ACTION_TICKET_RESOLUTION,
    ACTION_KNOWLEDGE_BASE_VIEW,
    ACTION_NAVIGATION,
    ALLOWED_ACTION_TYPES,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def get_db():
    return firestore.client()


def _serialize_timestamp(ts) -> Optional[Dict[str, int]]:
    """Firestore Timestamp or datetime -> { seconds, nanoseconds } for JSON."""
    if ts is None:
        return None
    if hasattr(ts, "seconds"):
        return {"seconds": ts.seconds, "nanoseconds": getattr(ts, "nanoseconds", 0)}
    if hasattr(ts, "timestamp"):
        s = int(ts.timestamp())
        return {"seconds": s, "nanoseconds": 0}
    return None


class ActivityLogRequest(BaseModel):
    action_type: str = Field(..., min_length=1, max_length=64)
    action_label: Optional[str] = Field(None, max_length=500)
    metadata: Optional[Dict[str, Any]] = None


@router.post("/activity")
async def post_activity(
    body: ActivityLogRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Log a client-initiated activity (e.g. dashboard_view, navigation).
    organization_id, user_id, user_role and created_at are set by the backend.
    """
    if body.action_type not in ALLOWED_ACTION_TYPES:
        return {"ok": False, "error": "Invalid action_type"}
    org_id = current_user.get("organization_id")
    if not org_id:
        return {"ok": False, "error": "Organization required"}
    db = get_db()
    log_activity(
        db,
        organization_id=org_id,
        user_id=current_user["uid"],
        user_role=current_user.get("role") or "employee",
        action_type=body.action_type,
        action_label=body.action_label or body.action_type,
        metadata=body.metadata,
    )
    return {"ok": True}


def _get_activity_summary(
    db,
    organization_id: str,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    role_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Query activity_logs and return grouped analytics."""
    base = db.collection("activity_logs").where("organization_id", "==", organization_id)
    stream = base.stream()
    logs: List[Dict[str, Any]] = []
    max_logs = 10000
    for doc in stream:
        if len(logs) >= max_logs:
            break
        d = doc.to_dict()
        d["id"] = doc.id
        created = d.get("created_at")
        if created is not None:
            if hasattr(created, "seconds"):
                ts = datetime.fromtimestamp(created.seconds + getattr(created, "nanoseconds", 0) / 1e9, tz=timezone.utc)
            elif hasattr(created, "timestamp"):
                ts = datetime.fromtimestamp(created.timestamp(), tz=timezone.utc)
            else:
                ts = None
            if ts and date_from and ts < date_from:
                continue
            if ts and date_to and ts > date_to:
                continue
        if role_filter and (d.get("user_role") or "") != role_filter:
            continue
        logs.append(d)

    def _sort_key(log):
        c = log.get("created_at")
        if c is None:
            return (0, 0)
        if hasattr(c, "seconds"):
            return (c.seconds, getattr(c, "nanoseconds", 0))
        if hasattr(c, "timestamp"):
            return (int(c.timestamp()), 0)
        return (0, 0)

    logs.sort(key=_sort_key, reverse=True)

    total_logins = sum(1 for l in logs if l.get("action_type") == ACTION_LOGIN)
    total_ticket_submissions = sum(1 for l in logs if l.get("action_type") == ACTION_TICKET_SUBMISSION)
    total_escalations = sum(1 for l in logs if l.get("action_type") == ACTION_TICKET_ESCALATION)
    total_resolutions = sum(1 for l in logs if l.get("action_type") == ACTION_TICKET_RESOLUTION)

    logins_by_day: Dict[str, int] = defaultdict(int)
    for log in logs:
        if log.get("action_type") != ACTION_LOGIN:
            continue
        c = log.get("created_at")
        if c is None:
            continue
        if hasattr(c, "seconds"):
            dt = datetime.fromtimestamp(c.seconds, tz=timezone.utc)
        elif hasattr(c, "timestamp"):
            dt = datetime.fromtimestamp(c.timestamp(), tz=timezone.utc)
        else:
            continue
        day_key = dt.date().isoformat()
        logins_by_day[day_key] += 1
    logins_per_day = [{"date": k, "count": v} for k, v in sorted(logins_by_day.items())]

    page_counts: Dict[str, int] = defaultdict(int)
    for log in logs:
        if log.get("action_type") != ACTION_NAVIGATION:
            continue
        page = (log.get("metadata") or {}).get("page") or "unknown"
        page_counts[page] += 1
    top_clicked_pages = [{"page": k, "count": v} for k, v in sorted(page_counts.items(), key=lambda x: -x[1])[:20]]

    user_counts: Dict[str, int] = defaultdict(int)
    for log in logs:
        uid = log.get("user_id") or "unknown"
        user_counts[uid] += 1
    most_active_users = [{"user_id": k, "count": v} for k, v in sorted(user_counts.items(), key=lambda x: -x[1])[:20]]

    actions_grouped_by_type: Dict[str, int] = defaultdict(int)
    for log in logs:
        t = log.get("action_type") or "unknown"
        actions_grouped_by_type[t] += 1
    actions_grouped_by_type = dict(actions_grouped_by_type)

    recent = logs[:50]
    recent_serialized = []
    for log in recent:
        r = {
            "id": log.get("id"),
            "user_id": log.get("user_id"),
            "user_role": log.get("user_role"),
            "action_type": log.get("action_type"),
            "action_label": log.get("action_label"),
            "metadata": log.get("metadata") or {},
        }
        c = log.get("created_at")
        if c is not None:
            r["created_at"] = _serialize_timestamp(c)
        else:
            r["created_at"] = None
        recent_serialized.append(r)

    return {
        "total_logins": total_logins,
        "total_ticket_submissions": total_ticket_submissions,
        "total_escalations": total_escalations,
        "total_resolutions": total_resolutions,
        "logins_per_day": logins_per_day,
        "top_clicked_pages": top_clicked_pages,
        "most_active_users": most_active_users,
        "actions_grouped_by_type": actions_grouped_by_type,
        "recent_activities": recent_serialized,
    }


@router.get("/activity-summary")
async def get_activity_summary(
    current_user: dict = Depends(require_super_admin),
    date_from: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="ISO date YYYY-MM-DD"),
    role: Optional[str] = Query(None, description="Filter by user_role"),
):
    """
    Return grouped activity analytics for the current organization.
    Super_admin only. Multi-tenant: only current org's logs.
    """
    organization_id = current_user.get("organization_id")
    if not organization_id:
        return {
            "total_logins": 0,
            "total_ticket_submissions": 0,
            "total_escalations": 0,
            "total_resolutions": 0,
            "logins_per_day": [],
            "top_clicked_pages": [],
            "most_active_users": [],
            "actions_grouped_by_type": {},
            "recent_activities": [],
        }
    db = get_db()
    date_from_dt = None
    date_to_dt = None
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to.replace("Z", "+00:00")).replace(tzinfo=timezone.utc)
            date_to_dt = date_to_dt + timedelta(days=1)
        except ValueError:
            pass
    return _get_activity_summary(db, organization_id, date_from=date_from_dt, date_to=date_to_dt, role_filter=role)
