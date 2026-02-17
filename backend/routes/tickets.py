"""
Ticket routes with AI resolution
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from fastapi import Query
from datetime import datetime
from openai import OpenAI
import json
from firebase_admin import firestore
from config import OPENAI_API_KEY
from middleware import verify_token, verify_admin, get_current_user, require_admin_or_above, require_super_admin
from flow_engine import (
    get_article_type,
    get_escalation_reply,
    is_escalation_message,
    log_flow_event,
    SUPPORT_AGENT_SYSTEM,
)
from kb_search import (
    extract_keywords,
    select_best_article,
    log_search,
    MIN_SCORE_THRESHOLD,
)

router = APIRouter()


def get_db():
    """Lazy initialization of Firestore client"""
    return firestore.client()


def _user_display_name(db, uid: Optional[str]) -> Optional[str]:
    """Return full_name or email for a user by uid; None if uid is None or user not found."""
    if not uid:
        return None
    try:
        user_doc = db.collection("users").document(uid).get()
        if not user_doc.exists:
            return None
        d = user_doc.to_dict()
        return (d.get("full_name") or d.get("name") or d.get("email") or "").strip() or None
    except Exception:
        return None

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)


def humanize_reply(text: str) -> str:
    """
    Formats AI reply into clean readable helpdesk format.
    """
    if not text:
        return "I'm escalating this to support."
    return (text or "").strip()


def _message_payload(
    sender: str,
    message: str,
    created_at: str,
    is_read: bool,
    ticket_user_id: str,
    assigned_to: Optional[str],
    *,
    sender_id: Optional[str] = None,
    sender_name: Optional[str] = None,
    sender_role: Optional[str] = None,
) -> dict:
    """Build message dict with recipient_id and sender_role for unread notifications."""
    if sender == "user":
        recipient_id = assigned_to
        role = "USER"
    elif sender == "admin":
        recipient_id = ticket_user_id
        role = (sender_role or "SUPPORT_ADMIN").replace("super_admin", "SUPER_ADMIN").replace("support_admin", "SUPPORT_ADMIN")
    else:
        recipient_id = ticket_user_id
        role = "AI"
    out = {
        "sender": sender,
        "message": message,
        "createdAt": created_at,
        "isRead": is_read,
        "recipient_id": recipient_id,
        "sender_role": role,
    }
    if sender_id is not None:
        out["sender_id"] = sender_id
    if sender_name is not None:
        out["sender_name"] = sender_name
    return out


# Strict KB-only prompt: OpenAI may ONLY use the provided article (Step 2)
KB_ONLY_SYSTEM = """You are a friendly, professional IT helpdesk agent. You speak naturally and supportively.
You may ONLY answer using the provided knowledge base article. You are strictly forbidden from using external knowledge.
If the article does not clearly contain the solution, respond exactly:
"I could not find a complete solution in your organization's knowledge base. I will escalate this ticket."
Do not improvise or generate general IT advice. Use only the article text.
Tone: conversational, helpful, human-like—like a real support agent. Start with a brief intro such as "I'll guide you through..." or "Let me help you with...". Be clear and supportive. Do not sound robotic."""

# User rejection phrases: trigger re-search with previous article excluded (Step 3)
DISSATISFACTION_PHRASES = (
    "wrong", "incorrect", "not helpful", "not what i asked", "that is not what i asked",
    "not right", "doesn't help", "not relevant", "not the right", "bad answer",
    "useless", "unhelpful", "that's wrong", "this is wrong", "incorrect answer",
    "this didn't work", "this didnt work", "didn't work", "didnt work", "still not working",
    "issue unresolved", "still unresolved", "doesn't resolve", "didn't resolve",
)


def _is_dissatisfaction(message: str) -> bool:
    """True if user is saying the answer was wrong / not helpful."""
    m = (message or "").lower().strip()
    return any(p in m for p in DISSATISFACTION_PHRASES)


async def _answer_from_single_article(question: str, article: dict) -> dict:
    """
    Send ONLY the selected article to OpenAI. No guessing, no external knowledge.
    Returns dict: { "aiReply": str or None, "escalated": bool }.
    """
    title = article.get("title") or ""
    content = article.get("content") or ""
    single_article_text = f"Title: {title}\n\nContent:\n{content}"
    system = KB_ONLY_SYSTEM
    user_prompt = f"""User question:
{question}

Knowledge base article (ONLY use this):
{single_article_text}

Respond in a friendly, human-like way—like a real helpdesk agent. Start with a brief intro such as "I'll guide you through {title}." or "Let me help you with that." Then provide the steps or instructions from the article in a clear, conversational way. Use ONLY the article above. If the article does not clearly answer the question, respond exactly: "I could not find a complete solution in your organization's knowledge base. I will escalate this ticket." """

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=800,
        )
        out = (response.choices[0].message.content or "").strip()
        escalate_phrase = "could not find a complete solution"
        if escalate_phrase in out.lower() or not out:
            return {"aiReply": None, "escalated": True}
        return {"aiReply": out, "escalated": False}
    except Exception:
        return {"aiReply": None, "escalated": True}


def _escalate_no_kb_match() -> dict:
    """Standard escalation when no acceptable KB match."""
    return {
        "status": "pending_assignment",
        "escalated": True,
        "internal_note": "AI unable to find KB match",
        "aiReply": None,
        "user_message": "I'm going to escalate this to a support specialist so they can assist you further.",
    }


def _build_ai_internal_summary(
    ticket_message: str,
    messages: list,
    article_title: Optional[str] = None,
    reason: str = "No relevant knowledge base found",
    recommended_action: Optional[str] = None,
) -> str:
    """
    Build a structured AI escalation summary for support admins.
    Not visible to users. Stored in ai_internal_summary.
    """
    lines = [
        "-------------------------------------------------------",
        "AI ESCALATION SUMMARY",
        "-------------------------------------------------------",
        "",
        "User Intent:",
        f"- The user is trying to: {ticket_message[:300]}",
        "",
        "Knowledge Base Attempted:",
    ]
    if article_title:
        steps_summary = "Article provided to user."
        if messages:
            ai_msgs = [m.get("message", "")[:150] for m in messages if m.get("sender") == "ai"]
            if ai_msgs:
                steps_summary = ai_msgs[-1][:200] + "..." if len(ai_msgs[-1]) > 200 else ai_msgs[-1]
        lines.extend([
            f"- Article matched: {article_title}",
            f"- Steps provided: {steps_summary}",
            "- Outcome: User reported issue not resolved",
        ])
    else:
        lines.extend([
            "- No matching article found",
            "- Outcome: N/A",
        ])
    lines.extend(["", "Conversation Summary:"])
    for m in (messages or [])[:10]:
        sender = m.get("sender", "?")
        label = "User" if sender == "user" else "AI" if sender == "ai" else "Admin"
        msg = (m.get("message") or "")[:200]
        if len((m.get("message") or "")) > 200:
            msg += "..."
        lines.append(f"- {label} said: \"{msg}\"")
    lines.extend([
        "",
        "Reason for Escalation:",
        f"- {reason}",
        "",
        "Recommended Next Action:",
        f"- {recommended_action or 'Manual review required'}",
        "-------------------------------------------------------",
    ])
    return "\n".join(lines)


INTRO_MSG = "I'll help you with that right away."
CONFIRMATION_PROMPT = "Please let me know if this resolved your issue.\n\nReply YES to close the ticket,\nor NO to escalate to support."
RESOLVED_REPLY = "Great! I'm glad that resolved your issue.\n\nIf you need anything else, feel free to open a new ticket."
ESCALATE_MSG_1 = "I wasn't able to fully resolve this for you."
ESCALATE_MSG_2 = "I've escalated your ticket to our support team. They will respond shortly."
ESCALATE_REPLY = ESCALATE_MSG_1 + "\n\n" + ESCALATE_MSG_2
NO_KB_FOUND_MSG = ESCALATE_MSG_1 + "\n\n" + ESCALATE_MSG_2
SUPPORT_CONFIRMATION_MSG = "Please confirm if this resolves your issue."


class TicketRequest(BaseModel):
    message: str


class MessageRequest(BaseModel):
    message: str
    sender: str  # Will be validated on backend based on user role


# --- Guided troubleshooting: human-like conversational flow ---

# Confirmation phrases: user is ready for next step
CONFIRMATION_KEYWORDS = (
    "done", "completed", "yes", "next", "finished", "ready", "okay", "ok",
    "did it", "completed it", "im there", "i'm there", "i am there",
    "got it", "did that", "all set", "moving on",
)

# User is stuck or it didn't work
STUCK_PHRASES = ("stuck", "doesn't work", "doesnt work", "not working", "can't find", "cant find", "i'm stuck", "im stuck", "help", "confused")


def _format_step_message(
    step_index: int,
    total_steps: int,
    instruction: str,
    device_context: str,
    article_title: str,
    is_first: bool,
) -> str:
    """Human-like step message. Only uses KB instruction; no external knowledge."""
    device_label = (device_context or "").replace("_", " ").title()
    topic = article_title or "this"
    if is_first and step_index == 1:
        return (
            f"Perfect 👍 Let's get {topic} set up on your {device_label}.\n\n"
            f"**Step 1:**\n{instruction}\n\n"
            "Tell me when you're there."
        )
    if step_index < total_steps:
        return (
            f"Nice! 👍\n\n**Step {step_index}:**\n{instruction}\n\n"
            "Tell me when you're done."
        )
    return (
        f"Almost there! 🎯\n\n**Step {step_index}:**\n{instruction}\n\n"
        "Tell me when you've completed this step."
    )


def _format_final_complete_message(article_title: str) -> str:
    """Clean ending when all steps are done. No device mixing."""
    topic = article_title or "this"
    return (
        f"Great 🎉 {topic} should now be fully set up.\n\n"
        "Try sending yourself a test to confirm everything is working.\n\n"
        "If anything doesn't look right, I'm here to help."
    )


def _format_resolution_confirmed_message() -> str:
    """When user confirms issue is resolved."""
    return "Awesome! I've marked this as resolved. If you need anything else, I'm here. 👍"


def _format_stuck_or_escalate_message() -> str:
    """When user says stuck or doesn't work."""
    return ESCALATE_REPLY


def _get_article_branches(art: dict) -> dict:
    """Return branches dict from article (guided_branches or branches)."""
    b = art.get("guided_branches") or art.get("branches")
    return b if isinstance(b, dict) else {}


def _try_guided_mode(user_message: str, kb_articles_full: List[dict]) -> dict:
    """
    If a matching article has guided_flow with multiple branches, return clarifying question.
    Uses kb_search intent-aware scoring to avoid wrong matches.
    Returns: { "use_guided": True, "clarifying_question": str, "matched_article_id": str } or { "use_guided": False }.
    """
    try:
        articles_with_branches = []
        for art in kb_articles_full:
            if not art.get("guided_flow"):
                continue
            branches = _get_article_branches(art)
            if not isinstance(branches, dict) or len(branches) < 2:
                continue
            articles_with_branches.append({
                "id": art.get("id"),
                "title": art.get("title", ""),
                "content": art.get("content", ""),
                "category": art.get("category", ""),
                "tags": art.get("tags"),
                "summary": art.get("summary", ""),
            })
        if not articles_with_branches:
            return {"use_guided": False}
        best_article, score, _ = select_best_article(
            articles_with_branches, extract_keywords(user_message),
            original_query=user_message
        )
        if not best_article or score < MIN_SCORE_THRESHOLD:
            return {"use_guided": False}
        # Build clarifying question
        art_full = next((a for a in kb_articles_full if a.get("id") == best_article.get("id")), None)
        if not art_full:
            return {"use_guided": False}
        branches = _get_article_branches(art_full)
        branch_names = list(branches.keys())
        option_lines = []
        for i, key in enumerate(branch_names):
            label = key.replace("_", " ").title()
            emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"][i] if i < 5 else f"{i + 1}."
            option_lines.append(f"{emoji} {label}")
        article_title = (art_full.get("title") or "").strip()
        topic = article_title.lower() if article_title else "this"
        clarifying_question = (
            f"Alright — I'll guide you through {topic}. It'll only take a few minutes.\n\n"
            "What device are you using?\n\n"
            + "\n".join(option_lines)
        )
        print("GUIDED MODE TRIGGERED:", best_article.get("title"))  # DEBUG
        return {
            "use_guided": True,
            "clarifying_question": clarifying_question,
            "matched_article_id": best_article.get("id"),
        }
    except Exception:
        return {"use_guided": False}


def _get_branch_steps(branch_data) -> List[str]:
    """Get ordered steps from branch: step1, step2, step3... or steps array."""
    if not branch_data:
        return []
    if isinstance(branch_data, list):
        return list(branch_data)
    if isinstance(branch_data, dict):
        if "steps" in branch_data and isinstance(branch_data["steps"], list):
            return list(branch_data["steps"])
        out = []
        k = 1
        while f"step{k}" in branch_data:
            out.append(branch_data[f"step{k}"])
            k += 1
        return out
    return []


def _guided_flow_respond(
    ticket_data: dict,
    user_message: str,
    guided_article: dict,
) -> tuple:
    """
    Compute next AI reply for guided flow. Returns (ai_reply: str, new_context: dict, resolved: bool, escalate: bool).
    - Locks to device_context once chosen; only pulls steps for that device (never Android after iPhone).
    - Session state: current_step_index, total_steps, completed_steps.
    - Human-like conversational tone; clean ending.
    - Handles "I'm stuck" / "doesn't work" with escalation.
    """
    context = dict((ticket_data.get("troubleshooting_context") or {}))
    device_context = context.get("device_type") or context.get("branch")
    current_step_index = context.get("step", 1)
    article_title = (guided_article or {}).get("title", "")
    branches = _get_article_branches(guided_article or {})

    if not isinstance(branches, dict):
        return ("I'm sorry, I couldn't load the steps. Please contact support.", context, False, False)

    # Only pull steps for the LOCKED device (never mix iPhone + Android)
    steps = _get_branch_steps(branches.get(device_context)) if device_context else []
    total_steps = len(steps)
    context["total_steps"] = total_steps

    msg_lower = (user_message or "").lower().strip()

    # User is stuck or it doesn't work -> escalate
    if any(p in msg_lower for p in STUCK_PHRASES):
        context["escalated_stuck"] = True
        return (_format_stuck_or_escalate_message(), context, False, True)

    # Resolved detection: user confirms issue is fixed
    explicit_resolve = any(x in msg_lower for x in ("resolved", "fixed", "it works", "solved", "yes it did", "that worked", "all good", "thank you", "thanks"))
    yes_resolve = "yes" in msg_lower and current_step_index >= total_steps
    if explicit_resolve or yes_resolve:
        context["resolved_confirmed"] = True
        return (_format_resolution_confirmed_message(), context, True, False)

    # DEVICE NOT LOCKED: parse user reply for iPhone/Android, lock device_context
    if not device_context:
        branch_names = list(branches.keys())
        choice = None
        for i, name in enumerate(branch_names):
            if msg_lower in (str(i + 1), name.lower(), name.lower().replace(" ", "").replace("-", "")):
                choice = name
                break
        if not choice and len(msg_lower) <= 30:
            for name in branch_names:
                if name.lower() in msg_lower or msg_lower in name.lower():
                    choice = name
                    break
        if choice:
            context["device_type"] = choice
            context["branch"] = choice
            context["step"] = 1
            context["device_context"] = choice
            steps = _get_branch_steps(branches.get(choice))
            if steps:
                reply = _format_step_message(
                    step_index=1,
                    total_steps=len(steps),
                    instruction=steps[0],
                    device_context=choice,
                    article_title=article_title,
                    is_first=True,
                )
                return (reply, context, False, False)
            return ("You're all set for that option. Did this solve your issue?", context, False, False)
        return (
            "I didn't catch that. Please reply with the number or name (e.g. 1 or iPhone).",
            context,
            False,
            False,
        )

    # DEVICE LOCKED: advance step on confirmation
    if any(x in msg_lower for x in CONFIRMATION_KEYWORDS):
        next_index = current_step_index + 1
        if next_index <= total_steps:
            context["step"] = next_index
            instruction = steps[next_index - 1]
            reply = _format_step_message(
                step_index=next_index,
                total_steps=total_steps,
                instruction=instruction,
                device_context=device_context,
                article_title=article_title,
                is_first=(next_index == 1),
            )
            return (reply, context, False, False)
        else:
            # Clean ending: all steps done
            reply = _format_final_complete_message(article_title)
            return (reply, context, False, False)

    if current_step_index > total_steps:
        reply = _format_final_complete_message(article_title)
        return (reply, context, False, False)

    # Re-send current step (user didn't confirm)
    instruction = steps[current_step_index - 1]
    reply = _format_step_message(
        step_index=current_step_index,
        total_steps=total_steps,
        instruction=instruction,
        device_context=device_context,
        article_title=article_title,
        is_first=(current_step_index == 1),
    )
    return (reply, context, False, False)


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

        kb_ref = db.collection("knowledge_base")
        if organization_id is not None:
            kb_stream = kb_ref.where("organization_id", "==", organization_id).stream()
        else:
            kb_stream = kb_ref.stream()
        knowledge_base = []
        kb_articles_full = []
        for doc in kb_stream:
            article_data = doc.to_dict()
            guided_flow = article_data.get("guided_flow", False)
            art_type = (article_data.get("type") or "").strip() or ("guided" if guided_flow else "static")
            full_art = {
                "id": doc.id,
                "title": article_data.get("title", ""),
                "content": article_data.get("content", ""),
                "category": article_data.get("category", ""),
                "tags": article_data.get("tags"),
                "summary": article_data.get("summary", ""),
                "guided_flow": guided_flow,
                "guided_branches": article_data.get("guided_branches"),
                "branches": article_data.get("branches"),
                "type": art_type,
                "article_type": article_data.get("article_type") or get_article_type({"type": art_type, "guided_flow": guided_flow, **article_data}),
                "trigger_phrases": article_data.get("trigger_phrases"),
                "flow": article_data.get("flow"),
            }
            kb_articles_full.append(full_art)
            if not guided_flow and art_type != "guided":
                knowledge_base.append({
                    "title": article_data.get("title", ""),
                    "content": article_data.get("content", ""),
                })

        now_iso = datetime.utcnow().isoformat()
        # Resolve user name for chat identity
        user_doc = db.collection("users").document(uid).get()
        user_name = "Customer"
        if user_doc.exists:
            d = user_doc.to_dict() or {}
            user_name = d.get("full_name") or d.get("email") or "Customer"
        messages = [
            _message_payload(
                "user", ticket.message, now_iso, True, uid, None,
                sender_id=uid, sender_name=user_name, sender_role="USER",
            )
        ]
        ticket_data = None

        try:
            # Phase 3: Universal retrieval — one weighted selection over ALL articles
            keywords = extract_keywords(ticket.message)
            best_article, score, debug_info = select_best_article(
                kb_articles_full, keywords, exclude_article_ids=[], original_query=ticket.message
            )
            log_search(ticket.message, debug_info, best_article.get("title") if best_article else None)
            log_flow_event("article_selection", query=ticket.message, best_id=best_article.get("id") if best_article else None, score=score)

            if not best_article or score < MIN_SCORE_THRESHOLD:
                # No KB article found: escalate. Do NOT mark escalated when article exists.
                print("KB article found:", False)
                messages.append(_message_payload("ai", NO_KB_FOUND_MSG, now_iso, False, uid, None))
                summary = (ticket.message[:200] + "..." if len(ticket.message) > 200 else ticket.message)
                ai_summary = _build_ai_internal_summary(
                    ticket.message, messages, article_title=None,
                    reason="No relevant knowledge base found",
                    recommended_action="Manual review and KB article creation if applicable",
                )
                ticket_data = {
                    "userId": uid,
                    "created_by_name": user_name,
                    "message": ticket.message,
                    "summary": summary,
                    "subject": summary,
                    "description": ticket.message,
                    "status": "escalated",
                    "escalated": True,
                    "mode": "human",
                    "category": None,
                    "aiReply": None,
                    "confidence": 0.0,
                    "knowledge_used": [],
                    "internal_note": "No KB match",
                    "ai_internal_summary": ai_summary,
                    "messages": messages,
                    "createdAt": now_iso,
                    "ai_mode": "ai_free",
                    "resolved": False,
                    "returned_article_id": None,
                    "rejected_article_ids": [],
                }
                print("Ticket status after creation:", ticket_data["status"])
            else:
                # Article found: MESSAGE 1 (intro), MESSAGE 2 (FULL raw article), MESSAGE 3 (confirmation)
                print("KB article found:", best_article is not None)
                summary_short = (ticket.message[:200] + "..." if len(ticket.message) > 200 else ticket.message)
                full_article_content = (best_article.get("content") or best_article.get("title") or "").strip()
                if not full_article_content:
                    full_article_content = best_article.get("title") or "No content available."
                messages.append(_message_payload("ai", INTRO_MSG, now_iso, False, uid, None))
                messages.append(_message_payload("ai", full_article_content, now_iso, False, uid, None))
                messages.append(_message_payload("ai", CONFIRMATION_PROMPT, now_iso, False, uid, None))
                log_flow_event("article_selection", article_id=best_article.get("id"), title=best_article.get("title"))
                ticket_data = {
                    "userId": uid,
                    "created_by_name": user_name,
                    "message": ticket.message,
                    "summary": summary_short,
                    "subject": summary_short,
                    "description": ticket.message,
                    "status": "ai_responded",
                    "escalated": False,
                    "mode": "ai",
                    "category": best_article.get("category"),
                    "aiReply": INTRO_MSG,
                    "confidence": float(score),
                    "knowledge_used": [best_article.get("title", "")],
                    "internal_note": "",
                    "messages": messages,
                    "createdAt": now_iso,
                    "ai_mode": "article",
                    "resolved": False,
                    "returned_article_id": best_article.get("id"),
                    "rejected_article_ids": [],
                }
                print("Ticket status after creation:", ticket_data["status"])
        except Exception as e:
            print("AI processing error:", str(e))
            messages.append(_message_payload("ai", NO_KB_FOUND_MSG, now_iso, False, uid, None))
            summary_fallback = (ticket.message[:200] + "..." if len(ticket.message) > 200 else ticket.message)
            ai_summary = _build_ai_internal_summary(
                ticket.message, messages, article_title=None,
                reason=f"AI processing error: {str(e)[:150]}",
                recommended_action="Manual review required",
            )
            ticket_data = {
                "userId": uid,
                "created_by_name": user_name,
                "message": ticket.message,
                "summary": summary_fallback,
                "subject": summary_fallback,
                "description": ticket.message,
                "status": "escalated",
                "escalated": True,
                "mode": "human",
                "category": None,
                "aiReply": None,
                "confidence": 0.0,
                "knowledge_used": [],
                "internal_note": f"AI error: {str(e)[:200]}",
                "ai_internal_summary": ai_summary,
                "messages": messages,
                "createdAt": now_iso,
                "ai_mode": "ai_free",
                "resolved": False,
                "returned_article_id": None,
                "rejected_article_ids": [],
            }

        if ticket_data is None:
            messages.append(_message_payload("ai", NO_KB_FOUND_MSG, now_iso, False, uid, None))
            summary_fallback = (ticket.message[:200] + "..." if len(ticket.message) > 200 else ticket.message)
            ai_summary = _build_ai_internal_summary(
                ticket.message, messages, article_title=None,
                reason="No relevant knowledge base found",
                recommended_action="Manual review required",
            )
            ticket_data = {
                "userId": uid,
                "created_by_name": user_name,
                "message": ticket.message,
                "summary": summary_fallback,
                "subject": summary_fallback,
                "description": ticket.message,
                "status": "escalated",
                "escalated": True,
                "mode": "human",
                "category": None,
                "aiReply": None,
                "confidence": 0.0,
                "knowledge_used": [],
                "internal_note": "No KB match",
                "ai_internal_summary": ai_summary,
                "messages": messages,
                "createdAt": now_iso,
                "ai_mode": "ai_free",
                "resolved": False,
                "returned_article_id": None,
                "rejected_article_ids": [],
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


def _ticket_matches_filters(
    ticket: dict,
    status_group: Optional[str],
    assigned_to: Optional[str],
    search: Optional[str],
) -> bool:
    """Apply optional filters: status_group (open/closed/assigned/all), assigned_to, search."""
    if status_group and status_group != "all":
        status = ticket.get("status") or ""
        has_assigned = ticket.get("assigned_to") is not None
        if status_group == "open":
            if status in ("resolved", "auto_resolved"):
                return False
        elif status_group == "closed":
            if status not in ("resolved", "auto_resolved"):
                return False
        elif status_group == "assigned":
            if not has_assigned:
                return False
    if assigned_to:
        if ticket.get("assigned_to") != assigned_to:
            return False
    if search and search.strip():
        q = search.strip().lower()
        text = " ".join([
            str(ticket.get("subject") or ""),
            str(ticket.get("message") or ""),
            str(ticket.get("description") or ""),
            str(ticket.get("summary") or ""),
        ]).lower()
        if q not in text:
            return False
    return True


@router.get("")
async def get_all_tickets(
    current_user: dict = Depends(require_admin_or_above),
    status_group: Optional[str] = Query(None, description="open | closed | assigned | all"),
    assigned_to: Optional[str] = Query(None, description="Filter by assigned user uid"),
    search: Optional[str] = Query(None, description="Search in subject, message, summary"),
):
    """
    Get tickets (Admin only). Super_admin sees all org tickets; support_admin sees only assigned.
    Optional filters: status_group (open/closed/assigned/all), assigned_to, search.
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

        # Support admin: ignore assigned_to param - they only see their own tickets
        filter_assigned_to = None if role == "support_admin" else assigned_to

        result = []
        for doc in tickets:
            ticket_data = doc.to_dict()
            if "escalated" not in ticket_data:
                ticket_data["escalated"] = (ticket_data.get("status") == "escalated" or
                                           ticket_data.get("status") == "needs_escalation")
            at = ticket_data.get("assigned_to")
            if at:
                ticket_data["assigned_to_name"] = _user_display_name(db, at)
            item = {"id": doc.id, **ticket_data}
            if _ticket_matches_filters(item, status_group, filter_assigned_to, search):
                result.append(item)
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
            ticket_data.pop("ai_internal_summary", None)
            at = ticket_data.get("assigned_to")
            if at:
                ticket_data["assigned_to_name"] = _user_display_name(db, at)
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
            at = ticket_data.get("assigned_to")
            if at:
                ticket_data["assigned_to_name"] = _user_display_name(db, at)
            ticket_ids.add(doc.id)
            result.append({"id": doc.id, **ticket_data})
        for doc in base_s1.stream():
            if doc.id not in ticket_ids:
                ticket_data = doc.to_dict()
                if "escalated" not in ticket_data:
                    ticket_data["escalated"] = True
                at = ticket_data.get("assigned_to")
                if at:
                    ticket_data["assigned_to_name"] = _user_display_name(db, at)
                result.append({"id": doc.id, **ticket_data})
                ticket_ids.add(doc.id)
        for doc in base_s2.stream():
            if doc.id not in ticket_ids:
                ticket_data = doc.to_dict()
                if "escalated" not in ticket_data:
                    ticket_data["escalated"] = True
                at = ticket_data.get("assigned_to")
                if at:
                    ticket_data["assigned_to_name"] = _user_display_name(db, at)
                result.append({"id": doc.id, **ticket_data})
        result.sort(key=lambda x: x.get("createdAt", ""), reverse=True)
        return {"tickets": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error fetching escalated tickets: {str(e)}")


@router.get("/{ticket_id}")
async def get_ticket_by_id(
    ticket_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Get a single ticket by id. Role-based access:
    - Employee: own tickets only (userId == current user).
    - Support_admin: tickets assigned to them only.
    - Super_admin: any ticket in org (or all if no org).
    """
    db = get_db()
    uid = current_user["uid"]
    role = current_user.get("role")
    organization_id = current_user.get("organization_id")
    is_admin = role in ("super_admin", "support_admin")

    ticket_ref = db.collection("tickets").document(ticket_id)
    doc = ticket_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail="Ticket not found")
    ticket_data = doc.to_dict()
    ticket_org_id = ticket_data.get("organization_id")
    ticket_user_id = ticket_data.get("userId")
    assigned_to = ticket_data.get("assigned_to")

    if organization_id is not None and ticket_org_id != organization_id:
        raise HTTPException(status_code=403, detail="Ticket not in your organization")
    if not is_admin:
        if ticket_user_id != uid:
            raise HTTPException(status_code=403, detail="You can only view your own tickets")
    elif role == "support_admin" and assigned_to != uid:
        raise HTTPException(status_code=403, detail="You can only view tickets assigned to you")

    if "escalated" not in ticket_data:
        ticket_data["escalated"] = (
            ticket_data.get("status") == "escalated" or ticket_data.get("status") == "needs_escalation"
        )
    ticket_data.pop("ai_internal_summary", None)
    assigned_to = ticket_data.get("assigned_to")
    if assigned_to:
        ticket_data["assigned_to_name"] = _user_display_name(db, assigned_to) or None
    return {"id": doc.id, **ticket_data}


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

        # Support admin: can only message tickets assigned to them
        if role == "support_admin" and ticket_data.get("assigned_to") != uid:
            raise HTTPException(status_code=403, detail="You can only send messages on tickets assigned to you")

        messages = ticket_data.get("messages", [])
        now_iso = datetime.utcnow().isoformat()
        ticket_user_id = ticket_data.get("userId") or ""
        assigned_to = ticket_data.get("assigned_to")
        new_message = _message_payload(
            message_request.sender,
            message_request.message,
            now_iso,
            False,
            ticket_user_id,
            assigned_to,
            sender_id=uid if is_admin else None,
            sender_name=(current_user.get("name") or current_user.get("email") or "Admin") if is_admin else None,
            sender_role=role if is_admin else "USER",
        )
        messages.append(new_message)

        # Support flow: first admin reply when ESCALATED → status IN_PROGRESS
        if (
            message_request.sender == "admin"
            and ticket_data.get("status") == "escalated"
        ):
            ticket_ref.update({
                "messages": messages,
                "status": "in_progress",
            })
            return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message}

        # HUMAN mode: AI must NEVER respond. Only store user message.
        if ticket_data.get("mode") == "human":
            ticket_ref.update({"messages": messages})
            return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message}

        # CLOSED: No further AI responses.
        if ticket_data.get("status") == "closed":
            ticket_ref.update({"messages": messages})
            return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message}

        # Phase 4: AWAITING_CONFIRMATION — user confirms admin resolution (YES → closed, NO → reopened)
        if (
            message_request.sender == "user"
            and ticket_data.get("status") == "awaiting_confirmation"
        ):
            user_msg = message_request.message
            msg_lower = user_msg.strip().lower()
            now_iso = datetime.utcnow().isoformat()
            if msg_lower in ("yes", "y", "yeah", "sure") or any(p in msg_lower for p in ("working", "resolved", "fixed", "all good", "thank")):
                ticket_ref.update({
                    "messages": messages,
                    "status": "closed",
                    "resolved": True,
                })
                return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message}
            if msg_lower in ("no", "n") or _is_dissatisfaction(user_msg):
                ticket_ref.update({
                    "messages": messages,
                    "status": "in_progress",
                    "mode": "human",
                    "resolved": False,
                    "internal_note": (ticket_data.get("internal_note") or "") + " [User: still not resolved]",
                })
                return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message}

        # Phase 2: AI mode — user confirmation (YES → close, NO → escalate)
        if (
            message_request.sender == "user"
            and (ticket_data.get("mode") == "ai" or ticket_data.get("ai_mode") == "article")
            and not ticket_data.get("resolved")
            and not ticket_data.get("escalated")
        ):
            user_msg = message_request.message
            msg_lower = user_msg.strip().lower()
            now_iso = datetime.utcnow().isoformat()

            # YES / solved / fixed / resolved → close ticket (status=CLOSED, mode=AI)
            if msg_lower in ("yes", "y", "yeah", "sure") or any(p in msg_lower for p in ("solved", "fixed", "resolved", "it worked", "working", "all good", "thank you", "thanks")):
                ai_reply = RESOLVED_REPLY
                messages.append(_message_payload("ai", ai_reply, now_iso, False, ticket_user_id, assigned_to))
                ticket_ref.update({
                    "messages": messages,
                    "status": "closed",
                    "mode": "ai",
                    "resolved": True,
                    "escalated": False,
                })
                return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message, "ai_reply": {"sender": "ai", "message": ai_reply, "createdAt": now_iso}, "resolved": True}

            # NO / not working / escalate → escalate to human
            if msg_lower in ("no", "n") or _is_dissatisfaction(user_msg) or any(p in msg_lower for p in ("not working", "still broken", "didn't help", "escalate")):
                ai_reply = ESCALATE_REPLY
                messages.append(_message_payload("ai", ai_reply, now_iso, False, ticket_user_id, assigned_to))
                article_title = (ticket_data.get("knowledge_used") or [None])[0] if ticket_data.get("knowledge_used") else None
                ai_summary = _build_ai_internal_summary(
                    ticket_data.get("message", ""),
                    messages,
                    article_title=article_title,
                    reason="User unsatisfied after guided steps",
                    recommended_action="Manual review and personalized support",
                )
                ticket_ref.update({
                    "messages": messages,
                    "status": "escalated",
                    "mode": "human",
                    "escalated": True,
                    "ai_mode": "ai_free",
                    "internal_note": (ticket_data.get("internal_note") or "") + " [User: NO / escalate]",
                    "ai_internal_summary": ai_summary,
                })
                return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message, "ai_reply": {"sender": "ai", "message": ai_reply, "createdAt": now_iso}}

        # Guided mode disabled: any legacy guided ticket → escalate
        if (
            message_request.sender == "user"
            and ticket_data.get("ai_mode") == "guided"
            and not ticket_data.get("resolved")
        ):
            now_iso = datetime.utcnow().isoformat()
            escalation_msg = ESCALATE_REPLY
            messages.append(_message_payload("ai", escalation_msg, now_iso, False, ticket_user_id, assigned_to))
            article_title = (ticket_data.get("knowledge_used") or [None])[0] if ticket_data.get("knowledge_used") else None
            ai_summary = _build_ai_internal_summary(
                ticket_data.get("message", ""),
                messages,
                article_title=article_title,
                reason="Flow disabled - escalated",
                recommended_action="Manual review required",
            )
            ticket_ref.update({
                "messages": messages,
                "mode": "human",
                "ai_mode": "ai_free",
                "status": "escalated",
                "escalated": True,
                "internal_note": (ticket_data.get("internal_note") or "") + " [Flow disabled - escalated]",
                "ai_internal_summary": ai_summary,
                "last_activity_timestamp": now_iso,
            })
            return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message, "ai_reply": {"sender": "ai", "message": escalation_msg, "createdAt": now_iso}}
        else:
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
        ticket_user_id = ticket_data.get("userId") or ""
        assigned_to = ticket_data.get("assigned_to")
        updated_messages = []
        for m in messages:
            rec = m.get("recipient_id")
            if rec is not None:
                updated_messages.append({**m, "isRead": True} if rec == uid else m)
            else:
                # Legacy: mark read for the appropriate party
                sender = m.get("sender", "")
                if sender == "user" and (assigned_to == uid or not assigned_to):
                    updated_messages.append({**m, "isRead": True})
                elif sender in ("admin", "ai") and ticket_user_id == uid:
                    updated_messages.append({**m, "isRead": True})
                else:
                    updated_messages.append(m)
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
    Allowed statuses: pending, in_progress, resolved, escalated, closed, ai_responded, awaiting_confirmation, reopened.
    Phase 4: When admin marks resolved (mode=human), status → awaiting_confirmation, send confirmation prompt.
    """
    try:
        db = get_db()
        organization_id = current_user.get("organization_id")
        allowed_statuses = ["open", "pending", "in_progress", "resolved", "escalated", "closed", "ai_responded", "awaiting_confirmation", "reopened", "auto_resolved"]
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

        # Support flow: Admin marks resolved (mode=human) → awaiting_confirmation + support sends confirmation
        update_data = {
            "status": new_status,
            "escalated": current_escalated,
            "updatedAt": datetime.utcnow().isoformat()
        }
        if new_status == "resolved" and ticket_data.get("mode") == "human":
            update_data["status"] = "awaiting_confirmation"
            messages = list(ticket_data.get("messages") or [])
            uid = current_user["uid"]
            role = current_user.get("role") or "support_admin"
            t_uid = ticket_data.get("userId") or ""
            t_assigned = ticket_data.get("assigned_to")
            messages.append(_message_payload(
                "admin", SUPPORT_CONFIRMATION_MSG, datetime.utcnow().isoformat(), False,
                t_uid, t_assigned,
                sender_id=uid,
                sender_name=current_user.get("name") or current_user.get("email") or "Support",
                sender_role=role,
            ))
            update_data["messages"] = messages
        ticket_ref.update(update_data)
        final_status = update_data["status"]
        return {"message": "Ticket status updated successfully", "ticket_id": ticket_id, "status": final_status, "escalated": current_escalated}
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
