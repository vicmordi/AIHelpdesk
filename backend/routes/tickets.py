"""
Ticket routes with AI resolution
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from openai import OpenAI
import json
from firebase_admin import firestore
from config import OPENAI_API_KEY
from middleware import verify_token, verify_admin, get_current_user, require_admin_or_above, require_super_admin

router = APIRouter()


def get_db():
    """Lazy initialization of Firestore client"""
    return firestore.client()

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)


class TicketRequest(BaseModel):
    message: str


class MessageRequest(BaseModel):
    message: str
    sender: str  # Will be validated on backend based on user role


class TicketResponse(BaseModel):
    id: str
    userId: str
    message: str
    summary: Optional[str]
    status: str
    category: Optional[str]
    aiReply: Optional[str]
    confidence: Optional[float]
    knowledge_used: Optional[List[str]]
    internal_note: Optional[str]
    messages: Optional[List[dict]]  # New: conversation thread
    createdAt: str


@router.post("")
async def create_ticket(
    ticket: TicketRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Create a new support ticket and attempt AI resolution.
    Scoped by organization_id when user belongs to an org.
    """
    try:
        db = get_db()
        uid = current_user["uid"]
        organization_id = current_user.get("organization_id")

        # Fetch knowledge base articles scoped by organization (only this org's KB for AI)
        kb_ref = db.collection("knowledge_base")
        if organization_id is not None:
            kb_articles = kb_ref.where("organization_id", "==", organization_id).stream()
        else:
            kb_articles = kb_ref.stream()
        knowledge_base = []
        for doc in kb_articles:
            article_data = doc.to_dict()
            knowledge_base.append({
                "title": article_data.get("title", ""),
                "content": article_data.get("content", "")
            })

        kb_text = "\n\n".join([
            f"Title: {kb['title']}\nContent: {kb['content']}"
            for kb in knowledge_base
        ])
        ai_result = await analyze_ticket_with_ai(ticket.message, kb_text, knowledge_base)

        messages = [
            {
                "sender": "user",
                "message": ticket.message,
                "createdAt": datetime.utcnow().isoformat(),
                "isRead": True
            }
        ]
        if ai_result.get("status") == "auto_resolved" and ai_result.get("aiReply"):
            messages.append({
                "sender": "ai",
                "message": ai_result.get("aiReply"),
                "createdAt": datetime.utcnow().isoformat(),
                "isRead": False
            })

        ticket_status = ai_result.get("status", "needs_escalation")
        if ticket_status == "needs_escalation":
            ticket_status = "escalated"
        is_escalated = (ticket_status == "escalated")

        summary = ai_result.get("summary", "")
        ticket_data = {
            "userId": uid,
            "message": ticket.message,
            "summary": summary,
            "subject": summary or (ticket.message[:200] + "..." if len(ticket.message) > 200 else ticket.message),
            "description": ticket.message,
            "status": ticket_status,
            "escalated": is_escalated,
            "category": ai_result.get("category"),
            "aiReply": ai_result.get("aiReply"),
            "confidence": ai_result.get("confidence", 0.0),
            "knowledge_used": ai_result.get("knowledge_used", []),
            "internal_note": ai_result.get("internal_note", ""),
            "messages": messages,
            "createdAt": datetime.utcnow().isoformat()
        }
        if organization_id is not None:
            ticket_data["organization_id"] = organization_id
            ticket_data["created_by"] = uid
            ticket_data["assigned_to"] = None

        doc_ref = db.collection("tickets").add(ticket_data)
        ticket_id = doc_ref[1].id
        return {
            "message": "Ticket created successfully",
            "ticket": {"id": ticket_id, **ticket_data}
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating ticket: {str(e)}")


async def analyze_ticket_with_ai(ticket_message: str, kb_text: str, knowledge_base: List[dict]) -> dict:
    """
    Use OpenAI Decision Engine to analyze ticket and determine if it should be auto-resolved or escalated.
    
    This function prioritizes escalation over auto-resolution. It will escalate if:
    - User already tried the solution
    - Time delays or persistence issues exist
    - Role/permission/access problems are mentioned
    - Multiple systems are affected
    - Manual intervention is required
    
    Returns a dict with status, aiReply, confidence, etc.
    """
    
    system_prompt = """You are an expert AI Helpdesk Decision Engine.

Your primary responsibility is NOT to answer questions, but to decide whether an issue should be AUTO-RESOLVED or ESCALATED.

Knowledge base articles are guidance, not guarantees.

CRITICAL THINKING RULES (MUST FOLLOW):

You MUST escalate the ticket if ANY of the following are true:

1. The user explicitly states they already followed the steps described in a knowledge base article.

2. The issue persists beyond an expected time window (e.g., permission sync longer than 24 hours).

3. The user mentions:
   - Incorrect role
   - Access denied
   - Permissions missing
   - Admin access issues
   - Regression (something worked before and stopped)

4. The problem affects MULTIPLE systems or applications.

5. The ticket requires manual verification, role reassignment, account correction, or human approval.

WHEN TO AUTO-RESOLVE:

ONLY auto-resolve if ALL conditions below are true:
- The ticket exactly matches a knowledge base article
- The user has NOT already tried the solution
- The issue is simple, single-step, and reversible
- There are no time delays, errors, or inconsistencies mentioned

If there is ANY doubt, escalate.

RESPONSE FORMAT (STRICT JSON):

Return ONLY valid JSON:

{
  "summary": "Short summary of the issue",
  "status": "auto_resolved" or "needs_escalation",
  "category": "Technical" or "Billing" or "Account" or "General",
  "confidence": "High" or "Medium" or "Low",
  "knowledge_used": "Article title or null",
  "user_reply": "Message sent to the user (step-by-step solution if auto_resolved, acknowledgment if escalated)",
  "internal_note": "Reason for escalation or null"
}

ESCALATION EXAMPLES (LEARN FROM THESE):

Ticket: "I reset my password but still can't access tools after 3 days."
→ MUST escalate
Reason: Steps already followed + exceeded time window

Ticket: "My role looks wrong and I can't access admin features."
→ MUST escalate
Reason: Role mismatch requires manual intervention

FORBIDDEN BEHAVIOR:
- Do NOT auto-resolve just because keywords match
- Do NOT ignore timelines or user statements
- Do NOT assume retrying steps will fix permission issues
- Do NOT override human judgment with confidence

FINAL RULE:
When uncertain, escalate."""

    user_prompt = f"""Support Ticket Message:
{ticket_message}

Knowledge Base Articles:
{kb_text if kb_text else "No knowledge base articles available."}

ANALYSIS REQUIRED:
1. Read the ticket carefully for escalation triggers:
   - Has user already tried the solution?
   - Are there time delays or persistence issues?
   - Are there role/permission/access problems?
   - Does it affect multiple systems?
   - Does it require manual intervention?

2. If ANY escalation trigger is present, set status to "needs_escalation"

3. Only set status to "auto_resolved" if:
   - Ticket exactly matches KB article
   - User has NOT tried the solution
   - Issue is simple and reversible
   - No time delays or errors mentioned

4. Provide your response in JSON format following the exact structure specified in the system prompt."""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.2,  # Lower temperature for more consistent, factual responses
            max_tokens=1500  # Increased for more detailed escalation reasoning
        )
        
        # Extract JSON from response
        ai_response_text = response.choices[0].message.content.strip()
        
        # Try to parse JSON (handle cases where AI might add markdown formatting)
        # Remove markdown code blocks if present
        if ai_response_text.startswith("```"):
            lines = ai_response_text.split("\n")
            ai_response_text = "\n".join(lines[1:-1])
        if ai_response_text.startswith("```json"):
            lines = ai_response_text.split("\n")
            ai_response_text = "\n".join(lines[1:-1])
        
        ai_result = json.loads(ai_response_text)
        
        # Extract and normalize status
        status = ai_result.get("status", "needs_escalation")
        # Map "needs_escalation" to "escalated" for consistency
        if status == "needs_escalation":
            status = "escalated"
        if status not in ["auto_resolved", "escalated"]:
            status = "escalated"  # Default to escalation if invalid
        
        # Convert confidence string to float for backward compatibility
        confidence_str = ai_result.get("confidence", "Low")
        confidence_map = {"High": 0.9, "Medium": 0.6, "Low": 0.3}
        confidence_float = confidence_map.get(confidence_str, 0.3)
        
        # Determine if can resolve based on status
        can_resolve = (status == "auto_resolved")
        
        # Get user reply (new field name) or fall back to aiReply (old field name)
        user_reply = ai_result.get("user_reply") or ai_result.get("aiReply")
        
        # Get knowledge used (handle both string and array formats)
        knowledge_used = ai_result.get("knowledge_used", [])
        if isinstance(knowledge_used, str):
            knowledge_used = [knowledge_used] if knowledge_used and knowledge_used != "null" else []
        elif knowledge_used is None:
            knowledge_used = []
        
        # Validate and set defaults
        result = {
            "can_resolve": can_resolve,
            "confidence": confidence_float,
            "summary": ai_result.get("summary", "No summary provided"),
            "status": status,
            "category": ai_result.get("category") if status == "escalated" else None,
            "aiReply": user_reply if can_resolve else None,
            "knowledge_used": knowledge_used,
            "internal_note": ai_result.get("internal_note", "") if not can_resolve else ""
        }
        
        # Additional safety: Override status if confidence is too low (even if AI said auto_resolved)
        if confidence_float < 0.7 and status == "auto_resolved":
            result["status"] = "escalated"
            result["can_resolve"] = False
            result["aiReply"] = None
            result["category"] = ai_result.get("category", "Technical")
            result["internal_note"] = "Auto-resolved with low confidence - escalated for safety"
        
        return result
        
    except json.JSONDecodeError as e:
        # If JSON parsing fails, escalate the ticket
        return {
            "can_resolve": False,
            "confidence": 0.0,
            "summary": "Error parsing AI response",
            "status": "escalated",
            "category": "Technical",
            "aiReply": None,
            "knowledge_used": [],
            "internal_note": f"AI response parsing error: {str(e)}"
        }
    except Exception as e:
        # If OpenAI API fails, escalate the ticket
        return {
            "can_resolve": False,
            "confidence": 0.0,
            "summary": "Error calling AI service",
            "status": "escalated",
            "category": "Technical",
            "aiReply": None,
            "knowledge_used": [],
            "internal_note": f"OpenAI API error: {str(e)}"
        }


@router.get("")
async def get_all_tickets(current_user: dict = Depends(require_admin_or_above)):
    """
    Get tickets (Admin only). Super_admin sees all org tickets; support_admin sees only assigned.
    Scoped by organization_id when user belongs to an org.
    """
    try:
        db = get_db()
        organization_id = current_user.get("organization_id")
        uid = current_user["uid"]
        role = current_user.get("role")

        tickets_ref = db.collection("tickets")
        if organization_id is not None:
            if role == "support_admin":
                tickets_ref = tickets_ref.where("organization_id", "==", organization_id).where("assigned_to", "==", uid)
            else:
                tickets_ref = tickets_ref.where("organization_id", "==", organization_id)
            tickets = tickets_ref.stream()
        else:
            tickets = tickets_ref.stream()

        result = []
        for doc in tickets:
            ticket_data = doc.to_dict()
            if "escalated" not in ticket_data:
                ticket_data["escalated"] = (ticket_data.get("status") == "escalated" or
                                           ticket_data.get("status") == "needs_escalation")
            result.append({"id": doc.id, **ticket_data})
        result.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return {"tickets": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching tickets: {str(e)}")


@router.get("/my-tickets")
async def get_my_tickets(current_user: dict = Depends(get_current_user)):
    """
    Get tickets created by the current user. Scoped by organization_id when applicable.
    """
    try:
        db = get_db()
        uid = current_user["uid"]
        organization_id = current_user.get("organization_id")

        if organization_id is not None:
            tickets_ref = db.collection("tickets").where("organization_id", "==", organization_id).where("userId", "==", uid)
        else:
            tickets_ref = db.collection("tickets").where("userId", "==", uid)
        tickets = tickets_ref.stream()

        result = []
        for doc in tickets:
            ticket_data = doc.to_dict()
            if "escalated" not in ticket_data:
                ticket_data["escalated"] = (ticket_data.get("status") == "escalated" or
                                           ticket_data.get("status") == "needs_escalation")
            result.append({"id": doc.id, **ticket_data})
        result.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return {"tickets": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching tickets: {str(e)}")


@router.get("/escalated")
async def get_escalated_tickets(current_user: dict = Depends(require_admin_or_above)):
    """
    Get escalated tickets for the organization. Super_admin: all org escalated; support_admin: assigned only.
    """
    try:
        db = get_db()
        organization_id = current_user.get("organization_id")
        uid = current_user["uid"]
        role = current_user.get("role")

        base = db.collection("tickets")
        if organization_id is not None:
            if role == "support_admin":
                base_escalated = base.where("organization_id", "==", organization_id).where("assigned_to", "==", uid).where("escalated", "==", True)
                base_s1 = base.where("organization_id", "==", organization_id).where("assigned_to", "==", uid).where("status", "==", "escalated")
                base_s2 = base.where("organization_id", "==", organization_id).where("assigned_to", "==", uid).where("status", "==", "needs_escalation")
            else:
                base_escalated = base.where("organization_id", "==", organization_id).where("escalated", "==", True)
                base_s1 = base.where("organization_id", "==", organization_id).where("status", "==", "escalated")
                base_s2 = base.where("organization_id", "==", organization_id).where("status", "==", "needs_escalation")
        else:
            base_escalated = base.where("escalated", "==", True)
            base_s1 = base.where("status", "==", "escalated")
            base_s2 = base.where("status", "==", "needs_escalation")

        ticket_ids = set()
        result = []
        for doc in base_escalated.stream():
            ticket_data = doc.to_dict()
            ticket_data["escalated"] = True
            ticket_ids.add(doc.id)
            result.append({"id": doc.id, **ticket_data})
        for doc in base_s1.stream():
            if doc.id not in ticket_ids:
                ticket_data = doc.to_dict()
                if "escalated" not in ticket_data:
                    ticket_data["escalated"] = True
                result.append({"id": doc.id, **ticket_data})
                ticket_ids.add(doc.id)
        for doc in base_s2.stream():
            if doc.id not in ticket_ids:
                ticket_data = doc.to_dict()
                if "escalated" not in ticket_data:
                    ticket_data["escalated"] = True
                result.append({"id": doc.id, **ticket_data})
        result.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return {"tickets": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching escalated tickets: {str(e)}")


@router.post("/{ticket_id}/messages")
async def add_message_to_ticket(
    ticket_id: str,
    message_request: MessageRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Add a message to a ticket. Users: own tickets as "user"; admins: as "admin".
    Enforces organization_id match when user belongs to an org.
    """
    try:
        db = get_db()
        uid = current_user["uid"]
        role = current_user.get("role")
        organization_id = current_user.get("organization_id")
        is_admin = role in ("super_admin", "support_admin")

        ticket_ref = db.collection("tickets").document(ticket_id)
        ticket_doc = ticket_ref.get()
        if not ticket_doc.exists:
            raise HTTPException(status_code=404, detail="Ticket not found")
        ticket_data = ticket_doc.to_dict()
        ticket_user_id = ticket_data.get("userId")
        ticket_org_id = ticket_data.get("organization_id")

        if organization_id is not None and ticket_org_id != organization_id:
            raise HTTPException(status_code=403, detail="Ticket not in your organization")
        if not is_admin and ticket_user_id != uid:
            raise HTTPException(status_code=403, detail="You can only send messages on your own tickets")
        if not is_admin and message_request.sender != "user":
            raise HTTPException(status_code=403, detail="Users can only send messages as 'user'")
        if is_admin and message_request.sender != "admin":
            raise HTTPException(status_code=400, detail="Admins must send messages as 'admin'")

        messages = ticket_data.get("messages", [])
        is_read = (message_request.sender == "user")
        new_message = {
            "sender": message_request.sender,
            "message": message_request.message,
            "createdAt": datetime.utcnow().isoformat(),
            "isRead": is_read
        }
        messages.append(new_message)
        ticket_ref.update({"messages": messages})
        return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding message: {str(e)}")


@router.post("/{ticket_id}/messages/read")
async def mark_messages_as_read(
    ticket_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Mark all messages in a ticket as read. Users: own tickets only; admins: any in org.
    """
    try:
        db = get_db()
        uid = current_user["uid"]
        role = current_user.get("role")
        organization_id = current_user.get("organization_id")
        is_admin = role in ("super_admin", "support_admin")

        ticket_ref = db.collection("tickets").document(ticket_id)
        ticket_doc = ticket_ref.get()
        if not ticket_doc.exists:
            raise HTTPException(status_code=404, detail="Ticket not found")
        ticket_data = ticket_doc.to_dict()
        if organization_id is not None and ticket_data.get("organization_id") != organization_id:
            raise HTTPException(status_code=403, detail="Ticket not in your organization")
        if not is_admin and ticket_data.get("userId") != uid:
            raise HTTPException(status_code=403, detail="You can only mark messages as read on your own tickets")

        messages = ticket_data.get("messages", [])
        updated_messages = [dict(m, isRead=True) for m in messages]
        ticket_ref.update({"messages": updated_messages})
        return {"message": "Messages marked as read", "ticket_id": ticket_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error marking messages as read: {str(e)}")


@router.put("/{ticket_id}/status")
async def update_ticket_status(
    ticket_id: str,
    status_update: dict,
    current_user: dict = Depends(require_admin_or_above)
):
    """
    Update ticket status (support_admin or super_admin). Scoped by organization.
    Allowed statuses: pending, in_progress, resolved, escalated, auto_resolved.
    """
    try:
        db = get_db()
        organization_id = current_user.get("organization_id")
        allowed_statuses = ["pending", "in_progress", "resolved", "escalated", "auto_resolved"]
        new_status = status_update.get("status")
        if not new_status or new_status not in allowed_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status. Allowed: {', '.join(allowed_statuses)}")

        ticket_ref = db.collection("tickets").document(ticket_id)
        ticket_doc = ticket_ref.get()
        if not ticket_doc.exists:
            raise HTTPException(status_code=404, detail="Ticket not found")
        ticket_data = ticket_doc.to_dict()
        if organization_id is not None and ticket_data.get("organization_id") != organization_id:
            raise HTTPException(status_code=403, detail="Ticket not in your organization")
        # support_admin may only update tickets assigned to them
        if current_user.get("role") == "support_admin" and ticket_data.get("assigned_to") != current_user["uid"]:
            raise HTTPException(status_code=403, detail="You can only update tickets assigned to you")

        current_escalated = ticket_data.get("escalated", False)
        if new_status == "escalated":
            current_escalated = True
        ticket_ref.update({
            "status": new_status,
            "escalated": current_escalated,
            "updatedAt": datetime.utcnow().isoformat()
        })
        return {"message": "Ticket status updated successfully", "ticket_id": ticket_id, "status": new_status, "escalated": current_escalated}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating ticket status: {str(e)}")


@router.put("/{ticket_id}/assign")
async def assign_ticket(
    ticket_id: str,
    body: dict,
    current_user: dict = Depends(require_super_admin),
):
    """
    Assign a ticket to a user (support_admin). Super_admin only. Scoped by organization.
    Body: { "assigned_to": "<uid>" } or { "assigned_to": null } to unassign.
    """
    try:
        db = get_db()
        organization_id = current_user.get("organization_id")
        if not organization_id:
            raise HTTPException(status_code=400, detail="Organization required")
        assigned_to = body.get("assigned_to")

        ticket_ref = db.collection("tickets").document(ticket_id)
        ticket_doc = ticket_ref.get()
        if not ticket_doc.exists:
            raise HTTPException(status_code=404, detail="Ticket not found")
        ticket_data = ticket_doc.to_dict()
        if ticket_data.get("organization_id") != organization_id:
            raise HTTPException(status_code=403, detail="Ticket not in your organization")
        if assigned_to is not None:
            user_doc = db.collection("users").document(assigned_to).get()
            if not user_doc.exists or user_doc.to_dict().get("organization_id") != organization_id:
                raise HTTPException(status_code=400, detail="Assigned user must belong to your organization")
        ticket_ref.update({
            "assigned_to": assigned_to,
            "updatedAt": datetime.utcnow().isoformat(),
        })
        return {"message": "Ticket assignment updated", "ticket_id": ticket_id, "assigned_to": assigned_to}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error assigning ticket: {str(e)}")
