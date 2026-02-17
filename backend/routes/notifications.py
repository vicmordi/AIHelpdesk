"""
Notifications API: unread count for navbar/badge.
Returns { unread_messages: number } for GET /notifications/unread-count.
"""

from fastapi import APIRouter, Depends
from firebase_admin import firestore

from middleware import get_current_user
from routes.messages import _is_unread_for_user

router = APIRouter()


def get_db():
    return firestore.client()


@router.get("/unread-count")
async def get_notifications_unread_count(current_user: dict = Depends(get_current_user)):
    """
    Return unread message count for the current user.
    Same role logic as /messages/unread-count; response key is unread_messages.
    """
    db = get_db()
    uid = current_user["uid"]
    role = (current_user.get("role") or "").lower()
    organization_id = current_user.get("organization_id")

    tickets_ref = db.collection("tickets")
    if role in ("super_admin", "support_admin", "admin"):
        if organization_id:
            if role == "support_admin":
                tickets_ref = tickets_ref.where("organization_id", "==", organization_id).where("assigned_to", "==", uid)
            else:
                tickets_ref = tickets_ref.where("organization_id", "==", organization_id)
        else:
            if role == "support_admin":
                tickets_ref = tickets_ref.where("assigned_to", "==", uid)
        tickets_stream = tickets_ref.stream()
    else:
        if organization_id:
            tickets_ref = db.collection("tickets").where("organization_id", "==", organization_id).where("userId", "==", uid)
        else:
            tickets_ref = db.collection("tickets").where("userId", "==", uid)
        tickets_stream = tickets_ref.stream()

    count = 0
    for doc in tickets_stream:
        data = doc.to_dict()
        ticket_user_id = data.get("userId") or ""
        assigned_to = data.get("assigned_to")
        ticket_org_id = data.get("organization_id")
        messages = data.get("messages") or []
        for m in messages:
            if _is_unread_for_user(
                m, uid, ticket_user_id, assigned_to,
                current_role=role, ticket_org_id=ticket_org_id, current_org_id=organization_id,
            ):
                count += 1
    return {"unread_messages": count}
