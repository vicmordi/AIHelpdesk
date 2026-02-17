"""
Message notification endpoints: unread count and mark-as-read.
Messages are stored inside ticket documents; counting is recipient-based.
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from firebase_admin import firestore

from middleware import get_current_user

router = APIRouter()


def get_db():
    return firestore.client()


def _is_unread_for_user(msg: dict, current_uid: str, ticket_user_id: str, ticket_assigned_to: Optional[str]) -> bool:
    """True if this message is unread for current_uid. Supports legacy messages without recipient_id."""
    if msg.get("isRead") is True:
        return False
    recipient_id = msg.get("recipient_id")
    if recipient_id is not None:
        return recipient_id == current_uid
    # Legacy: no recipient_id — infer from sender
    sender = msg.get("sender", "")
    if sender == "user":
        # User message: unread for the assigned admin (or any admin if unassigned)
        return ticket_assigned_to == current_uid if ticket_assigned_to else False
    if sender in ("admin", "ai"):
        # Admin/AI message: unread for the ticket owner (customer)
        return ticket_user_id == current_uid
    return False


@router.get("/unread-count")
async def get_unread_count(current_user: dict = Depends(get_current_user)):
    """
    Return total unread message count for the current user.
    USER: unread in own tickets (from AI or admin).
    SUPPORT_ADMIN: unread only in tickets assigned to them.
    SUPER_ADMIN: unread across all org tickets.
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
            # else super_admin no org: all tickets
        tickets_stream = tickets_ref.stream()
    else:
        # USER: own tickets only
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
        messages = data.get("messages") or []
        for m in messages:
            if _is_unread_for_user(m, uid, ticket_user_id, assigned_to):
                count += 1
    return {"unread_count": count}


@router.post("/mark-read/{ticket_id}")
async def mark_ticket_messages_read(
    ticket_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Mark all messages in the ticket as read for the current user (recipient).
    Only messages where recipient_id == current_user.id are updated.
    """
    db = get_db()
    uid = current_user["uid"]
    role = current_user.get("role")
    organization_id = current_user.get("organization_id")
    is_admin = role in ("super_admin", "support_admin", "admin")

    ticket_ref = db.collection("tickets").document(ticket_id)
    doc = ticket_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Ticket not found")
    data = doc.to_dict()
    if organization_id and data.get("organization_id") != organization_id:
        raise HTTPException(status_code=403, detail="Ticket not in your organization")
    if not is_admin and data.get("userId") != uid:
        raise HTTPException(status_code=403, detail="Not your ticket")
    if is_admin and role == "support_admin" and data.get("assigned_to") != uid:
        raise HTTPException(status_code=403, detail="Ticket not assigned to you")

    messages = data.get("messages") or []
    updated = []
    for m in messages:
        rec = m.get("recipient_id")
        # Legacy: if no recipient_id, mark read for the appropriate party
        if rec is not None:
            if rec == uid:
                updated.append({**m, "isRead": True})
            else:
                updated.append(m)
        else:
            sender = m.get("sender", "")
            if sender == "user" and (data.get("assigned_to") == uid or not data.get("assigned_to")):
                updated.append({**m, "isRead": True})
            elif sender in ("admin", "ai") and data.get("userId") == uid:
                updated.append({**m, "isRead": True})
            else:
                updated.append(m)
    ticket_ref.update({"messages": updated})
    return {"message": "Messages marked as read", "ticket_id": ticket_id}
