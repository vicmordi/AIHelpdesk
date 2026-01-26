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
from middleware import verify_token, verify_admin

# Get Firestore client
db = firestore.client()

router = APIRouter()

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
    decoded_token: dict = Depends(verify_token)
):
    """
    Create a new support ticket and attempt AI resolution
    """
    try:
        uid = decoded_token.get("uid")
        
        # Fetch all knowledge base articles
        kb_ref = db.collection("knowledge_base")
        kb_articles = kb_ref.stream()
        
        knowledge_base = []
        for doc in kb_articles:
            article_data = doc.to_dict()
            knowledge_base.append({
                "title": article_data.get("title", ""),
                "content": article_data.get("content", "")
            })
        
        # Prepare knowledge base text for AI
        kb_text = "\n\n".join([
            f"Title: {kb['title']}\nContent: {kb['content']}"
            for kb in knowledge_base
        ])
        
        # Call OpenAI to analyze the ticket
        ai_result = await analyze_ticket_with_ai(ticket.message, kb_text, knowledge_base)
        
        # Initialize messages array with user message and AI response
        messages = [
            {
                "sender": "user",
                "message": ticket.message,
                "createdAt": datetime.utcnow().isoformat(),
                "isRead": True  # User's own message is read
            }
        ]
        
        # Add AI response as a message if auto-resolved
        if ai_result.get("status") == "auto_resolved" and ai_result.get("aiReply"):
            messages.append({
                "sender": "ai",
                "message": ai_result.get("aiReply"),
                "createdAt": datetime.utcnow().isoformat(),
                "isRead": False  # AI response is unread by user initially
            })
        
        # Determine if ticket is escalated
        # Escalation is a historical state - once escalated, always escalated
        ticket_status = ai_result.get("status", "needs_escalation")
        # Map "needs_escalation" to "escalated" status for consistency
        if ticket_status == "needs_escalation":
            ticket_status = "escalated"
        is_escalated = (ticket_status == "escalated")
        
        # Create ticket document
        ticket_data = {
            "userId": uid,
            "message": ticket.message,  # Keep original message field for backward compatibility
            "summary": ai_result.get("summary", ""),
            "status": ticket_status,
            "escalated": is_escalated,  # Track escalation independently from status
            "category": ai_result.get("category"),
            "aiReply": ai_result.get("aiReply"),  # Keep for backward compatibility
            "confidence": ai_result.get("confidence", 0.0),
            "knowledge_used": ai_result.get("knowledge_used", []),
            "internal_note": ai_result.get("internal_note", ""),
            "messages": messages,  # New: conversation thread
            "createdAt": datetime.utcnow().isoformat()
        }
        
        # Save to Firestore
        doc_ref = db.collection("tickets").add(ticket_data)
        ticket_id = doc_ref[1].id
        
        return {
            "message": "Ticket created successfully",
            "ticket": {
                "id": ticket_id,
                **ticket_data
            }
        }
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
async def get_all_tickets(decoded_token: dict = Depends(verify_admin)):
    """
    Get all tickets (Admin only)
    """
    try:
        tickets_ref = db.collection("tickets")
        tickets = tickets_ref.stream()
        
        result = []
        for doc in tickets:
            ticket_data = doc.to_dict()
            # Backward compatibility: If escalated field doesn't exist, infer from status
            if "escalated" not in ticket_data:
                ticket_data["escalated"] = (ticket_data.get("status") == "escalated" or 
                                           ticket_data.get("status") == "needs_escalation")
            result.append({
                "id": doc.id,
                **ticket_data
            })
        
        # Sort by createdAt descending (newest first)
        result.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        
        return {"tickets": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching tickets: {str(e)}")


@router.get("/my-tickets")
async def get_my_tickets(decoded_token: dict = Depends(verify_token)):
    """
    Get tickets for the current user
    """
    try:
        uid = decoded_token.get("uid")
        
        tickets_ref = db.collection("tickets").where("userId", "==", uid)
        tickets = tickets_ref.stream()
        
        result = []
        for doc in tickets:
            ticket_data = doc.to_dict()
            # Backward compatibility: If escalated field doesn't exist, infer from status
            if "escalated" not in ticket_data:
                ticket_data["escalated"] = (ticket_data.get("status") == "escalated" or 
                                           ticket_data.get("status") == "needs_escalation")
            result.append({
                "id": doc.id,
                **ticket_data
            })
        
        # Sort by createdAt descending (newest first)
        result.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        
        return {"tickets": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching tickets: {str(e)}")


@router.get("/escalated")
async def get_escalated_tickets(decoded_token: dict = Depends(verify_admin)):
    """
    Get all escalated tickets (Admin only)
    Uses the escalated field, not status, since escalation is a historical state
    """
    try:
        # Query by escalated field instead of status
        # This ensures we get all tickets that were ever escalated, regardless of current status
        # Also query by status for backward compatibility with old tickets
        tickets_ref_escalated = db.collection("tickets").where("escalated", "==", True)
        tickets_ref_status1 = db.collection("tickets").where("status", "==", "escalated")
        tickets_ref_status2 = db.collection("tickets").where("status", "==", "needs_escalation")
        
        # Get tickets from all queries and merge (avoid duplicates)
        escalated_tickets = tickets_ref_escalated.stream()
        status_tickets1 = tickets_ref_status1.stream()
        status_tickets2 = tickets_ref_status2.stream()
        
        ticket_ids = set()
        result = []
        
        # Add tickets from escalated field query
        for doc in escalated_tickets:
            ticket_data = doc.to_dict()
            ticket_data["escalated"] = True  # Ensure it's set
            ticket_ids.add(doc.id)
            result.append({
                "id": doc.id,
                **ticket_data
            })
        
        # Add tickets from status queries (for backward compatibility)
        for doc in status_tickets1:
            if doc.id not in ticket_ids:
                ticket_data = doc.to_dict()
                # Set escalated field if missing
                if "escalated" not in ticket_data:
                    ticket_data["escalated"] = True
                result.append({
                    "id": doc.id,
                    **ticket_data
                })
                ticket_ids.add(doc.id)
        
        for doc in status_tickets2:
            if doc.id not in ticket_ids:
                ticket_data = doc.to_dict()
                # Set escalated field if missing
                if "escalated" not in ticket_data:
                    ticket_data["escalated"] = True
                result.append({
                    "id": doc.id,
                    **ticket_data
                })
        
        # Sort by createdAt descending (newest first)
        result.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        
        return {"tickets": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching escalated tickets: {str(e)}")


@router.post("/{ticket_id}/messages")
async def add_message_to_ticket(
    ticket_id: str,
    message_request: MessageRequest,
    decoded_token: dict = Depends(verify_token)
):
    """
    Add a message to a ticket conversation thread
    - Users can only send messages as "user" on their own tickets
    - Admins can send messages as "admin" on any ticket
    """
    try:
        uid = decoded_token.get("uid")
        
        # Get user role
        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_data = user_doc.to_dict()
        user_role = user_data.get("role", "employee")
        is_admin = (user_role == "admin")
        
        # Get ticket
        ticket_ref = db.collection("tickets").document(ticket_id)
        ticket_doc = ticket_ref.get()
        
        if not ticket_doc.exists:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        ticket_data = ticket_doc.to_dict()
        ticket_user_id = ticket_data.get("userId")
        
        # Security: Users can only message their own tickets
        if not is_admin and ticket_user_id != uid:
            raise HTTPException(
                status_code=403,
                detail="You can only send messages on your own tickets"
            )
        
        # Validate sender role
        # Users can only send as "user", admins can only send as "admin"
        if not is_admin and message_request.sender != "user":
            raise HTTPException(
                status_code=403,
                detail="Users can only send messages as 'user'"
            )
        
        if is_admin and message_request.sender != "admin":
            raise HTTPException(
                status_code=400,
                detail="Admins must send messages as 'admin'"
            )
        
        # Get existing messages or initialize empty array
        messages = ticket_data.get("messages", [])
        
        # Add new message
        # Determine if message should be marked as read:
        # - If sender is "user", mark as read (user sees their own message)
        # - If sender is "admin", mark as unread for the ticket owner
        # - If sender is "ai", mark as unread for the ticket owner
        is_read = (message_request.sender == "user")
        
        new_message = {
            "sender": message_request.sender,
            "message": message_request.message,
            "createdAt": datetime.utcnow().isoformat(),
            "isRead": is_read
        }
        messages.append(new_message)
        
        # Update ticket with new message
        ticket_ref.update({
            "messages": messages
        })
        
        return {
            "message": "Message added successfully",
            "ticket_id": ticket_id,
            "new_message": new_message
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error adding message: {str(e)}")


@router.post("/{ticket_id}/messages/read")
async def mark_messages_as_read(
    ticket_id: str,
    decoded_token: dict = Depends(verify_token)
):
    """
    Mark all messages in a ticket as read for the current user
    - Users can mark messages as read on their own tickets
    - Admins can mark messages as read on any ticket
    """
    try:
        uid = decoded_token.get("uid")
        
        # Get user role
        user_ref = db.collection("users").document(uid)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_data = user_doc.to_dict()
        user_role = user_data.get("role", "employee")
        is_admin = (user_role == "admin")
        
        # Get ticket
        ticket_ref = db.collection("tickets").document(ticket_id)
        ticket_doc = ticket_ref.get()
        
        if not ticket_doc.exists:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        ticket_data = ticket_doc.to_dict()
        ticket_user_id = ticket_data.get("userId")
        
        # Security: Users can only mark messages as read on their own tickets
        if not is_admin and ticket_user_id != uid:
            raise HTTPException(
                status_code=403,
                detail="You can only mark messages as read on your own tickets"
            )
        
        # Get existing messages
        messages = ticket_data.get("messages", [])
        
        # Mark all messages as read
        updated_messages = []
        for msg in messages:
            msg_copy = msg.copy()
            msg_copy["isRead"] = True
            updated_messages.append(msg_copy)
        
        # Update ticket with read messages
        ticket_ref.update({
            "messages": updated_messages
        })
        
        return {
            "message": "Messages marked as read",
            "ticket_id": ticket_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error marking messages as read: {str(e)}")


@router.put("/{ticket_id}/status")
async def update_ticket_status(
    ticket_id: str,
    status_update: dict,
    decoded_token: dict = Depends(verify_admin)
):
    """
    Update ticket status (Admin only)
    Allowed statuses: pending, in_progress, resolved, escalated, auto_resolved
    
    IMPORTANT: Escalation is a historical state - once escalated, always escalated.
    Changing status does NOT change the escalated flag.
    """
    try:
        allowed_statuses = ["pending", "in_progress", "resolved", "escalated", "auto_resolved"]
        new_status = status_update.get("status")
        
        if not new_status or new_status not in allowed_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Allowed values: {', '.join(allowed_statuses)}"
            )
        
        # Get ticket
        ticket_ref = db.collection("tickets").document(ticket_id)
        ticket_doc = ticket_ref.get()
        
        if not ticket_doc.exists:
            raise HTTPException(status_code=404, detail="Ticket not found")
        
        ticket_data = ticket_doc.to_dict()
        current_escalated = ticket_data.get("escalated", False)
        
        # If ticket was previously escalated, keep escalated = true
        # Escalation is a historical state that never reverts
        # Also set escalated = true if new status is "escalated"
        if new_status == "escalated":
            current_escalated = True
        
        # Update status (but preserve escalated flag)
        ticket_ref.update({
            "status": new_status,
            "escalated": current_escalated,  # Preserve escalation state
            "updatedAt": datetime.utcnow().isoformat()
        })
        
        return {
            "message": "Ticket status updated successfully",
            "ticket_id": ticket_id,
            "status": new_status,
            "escalated": current_escalated
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error updating ticket status: {str(e)}")
