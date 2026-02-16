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
    normalize_article_to_flow,
    match_flow_by_trigger,
    flow_get_first_message,
    flow_advance,
    is_resolution_message,
    is_escalation_message,
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

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)


def humanize_reply(text: str) -> str:
    """
    Formats AI reply into clean readable helpdesk format.
    """
    if not text:
        return "I'm escalating this to support."
    return (text or "").strip()


# Strict KB-only prompt: OpenAI may ONLY use the provided article (Step 2)
KB_ONLY_SYSTEM = """You are an internal IT helpdesk assistant.
You may ONLY answer using the provided knowledge base article.
You are strictly forbidden from using external knowledge.
If the article does not clearly contain the solution, respond exactly:
"I could not find a complete solution in your organization's knowledge base. I will escalate this ticket."
Do not improvise or generate general IT advice. Use only the article text."""

# User rejection phrases: trigger re-search with previous article excluded (Step 3)
DISSATISFACTION_PHRASES = (
    "wrong", "incorrect", "not helpful", "not what i asked", "that is not what i asked",
    "not right", "doesn't help", "not relevant", "not the right", "bad answer",
    "useless", "unhelpful", "that's wrong", "this is wrong", "incorrect answer",
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

Respond to the user using ONLY the article above. If the article does not clearly answer the question, respond exactly: "I could not find a complete solution in your organization's knowledge base. I will escalate this ticket." """

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
    """Standard escalation when no acceptable KB match (Step 4)."""
    return {
        "status": "pending_assignment",
        "escalated": True,
        "internal_note": "AI unable to find KB match",
        "aiReply": None,
        "user_message": "I could not find a matching solution in your organization's knowledge base. I am escalating this to a support specialist.",
    }


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
    return "Let me escalate this to a support specialist who can help further."


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
        clarifying_question = (
            "Alright — I'll walk you through this. It'll only take a few minutes.\n\n"
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
            kb_articles_full.append({
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
                "trigger_phrases": article_data.get("trigger_phrases"),
                "flow": article_data.get("flow"),
            })
            if not guided_flow and art_type != "guided":
                knowledge_base.append({
                    "title": article_data.get("title", ""),
                    "content": article_data.get("content", ""),
                })

        now_iso = datetime.utcnow().isoformat()
        messages = [
            {"sender": "user", "message": ticket.message, "createdAt": now_iso, "isRead": True}
        ]
        ticket_data = None

        try:
            # Part 1 & 2: Match by trigger_phrases (converted or structured guided) — guided overrides article dump
            matched = match_flow_by_trigger(ticket.message, kb_articles_full)
            if matched and matched.get("type") == "guided":
                first_msg = flow_get_first_message(matched.get("flow") or [])
                first_msg = humanize_reply(first_msg)
                print("FLOW MATCHED:", matched.get("title"))  # Part 8 debug
                messages.append({"sender": "ai", "message": first_msg, "createdAt": now_iso, "isRead": False})
                summary = (ticket.message[:200] + "..." if len(ticket.message) > 200 else ticket.message)
                ticket_data = {
                    "userId": uid,
                    "message": ticket.message,
                    "summary": summary,
                    "subject": summary,
                    "description": ticket.message,
                    "status": "in_progress",
                    "escalated": False,
                    "category": matched.get("category"),
                    "aiReply": None,
                    "confidence": 0.0,
                    "knowledge_used": [],
                    "internal_note": "",
                    "messages": messages,
                    "createdAt": now_iso,
                    "ai_mode": "guided",
                    "flow_id": matched.get("id"),
                    "current_step": (matched.get("flow") or [{}])[0].get("step_id", "step_1"),
                    "troubleshooting_context": {},
                    "resolved": False,
                    "completed": False,
                    "last_activity_timestamp": now_iso,
                    "confusion_count": 0,
                    "current_step_options": (matched.get("flow") or [{}])[0].get("options", []) if matched.get("flow") else [],
                }
                if matched.get("_legacy_branches"):
                    ticket_data["guided_article_id"] = matched.get("id")
            else:
                guided = _try_guided_mode(ticket.message, kb_articles_full)
                if guided.get("use_guided") and guided.get("clarifying_question"):
                    first_msg = humanize_reply(guided["clarifying_question"])
                    messages.append({"sender": "ai", "message": first_msg, "createdAt": now_iso, "isRead": False})
                    summary = (ticket.message[:200] + "..." if len(ticket.message) > 200 else ticket.message)
                    ticket_data = {
                        "userId": uid,
                        "message": ticket.message,
                        "summary": summary,
                        "subject": summary,
                        "description": ticket.message,
                        "status": "in_progress",
                        "escalated": False,
                        "category": None,
                        "aiReply": None,
                        "confidence": 0.0,
                        "knowledge_used": [],
                        "internal_note": "",
                        "messages": messages,
                        "createdAt": now_iso,
                        "ai_mode": "guided",
                        "flow_id": guided.get("matched_article_id"),
                        "current_step": 0,
                        "troubleshooting_context": {},
                        "resolved": False,
                        "completed": False,
                        "last_activity_timestamp": now_iso,
                        "confusion_count": 0,
                        "guided_article_id": guided.get("matched_article_id"),
                    }
                else:
                    # Strict KB matching: only org KB, keyword score, single article, no guessing (Step 1)
                    articles_for_scoring = []
                    for a in kb_articles_full:
                        if a.get("guided_flow") or (a.get("type") or "").strip().lower() == "guided":
                            continue
                        articles_for_scoring.append({
                            "id": a.get("id"),
                            "title": a.get("title", ""),
                            "content": a.get("content", ""),
                            "category": a.get("category", ""),
                            "tags": a.get("tags"),
                            "summary": a.get("summary", ""),
                        })
                    keywords = extract_keywords(ticket.message)
                    best_article, score, debug_info = select_best_article(
                        articles_for_scoring, keywords, exclude_article_ids=[], original_query=ticket.message
                    )
                    log_search(ticket.message, debug_info, best_article.get("title") if best_article else None)

                    if score < MIN_SCORE_THRESHOLD or not best_article:
                        esc = _escalate_no_kb_match()
                        messages.append({
                            "sender": "ai",
                            "message": esc["user_message"],
                            "createdAt": now_iso,
                            "isRead": False,
                        })
                        summary = (ticket.message[:200] + "..." if len(ticket.message) > 200 else ticket.message)
                        ticket_data = {
                            "userId": uid,
                            "message": ticket.message,
                            "summary": summary,
                            "subject": summary,
                            "description": ticket.message,
                            "status": esc["status"],
                            "escalated": esc["escalated"],
                            "category": None,
                            "aiReply": None,
                            "confidence": 0.0,
                            "knowledge_used": [],
                            "internal_note": esc["internal_note"],
                            "messages": messages,
                            "createdAt": now_iso,
                            "ai_mode": "article",
                            "current_step": 0,
                            "troubleshooting_context": {},
                            "resolved": False,
                            "returned_article_id": None,
                            "rejected_article_ids": [],
                        }
                    else:
                        answer_result = await _answer_from_single_article(ticket.message, best_article)
                        summary_short = (ticket.message[:200] + "..." if len(ticket.message) > 200 else ticket.message)
                        if answer_result.get("escalated") or not answer_result.get("aiReply"):
                            esc = _escalate_no_kb_match()
                            messages.append({
                                "sender": "ai",
                                "message": esc["user_message"],
                                "createdAt": now_iso,
                                "isRead": False,
                            })
                            ticket_data = {
                                "userId": uid,
                                "message": ticket.message,
                                "summary": summary_short,
                                "subject": summary_short,
                                "description": ticket.message,
                                "status": esc["status"],
                                "escalated": True,
                                "category": None,
                                "aiReply": None,
                                "confidence": 0.0,
                                "knowledge_used": [],
                                "internal_note": esc["internal_note"],
                                "messages": messages,
                                "createdAt": now_iso,
                                "ai_mode": "article",
                                "current_step": 0,
                                "troubleshooting_context": {},
                                "resolved": False,
                                "returned_article_id": None,
                                "rejected_article_ids": [],
                            }
                        else:
                            messages.append({
                                "sender": "ai",
                                "message": answer_result["aiReply"],
                                "createdAt": now_iso,
                                "isRead": False,
                            })
                            ticket_data = {
                                "userId": uid,
                                "message": ticket.message,
                                "summary": summary_short,
                                "subject": summary_short,
                                "description": ticket.message,
                                "status": "auto_resolved",
                                "escalated": False,
                                "category": best_article.get("category"),
                                "aiReply": answer_result["aiReply"],
                                "confidence": 0.9,
                                "knowledge_used": [best_article.get("title", "")],
                                "internal_note": "",
                                "messages": messages,
                                "createdAt": now_iso,
                                "ai_mode": "article",
                                "current_step": 0,
                                "troubleshooting_context": {},
                                "resolved": True,
                                "returned_article_id": best_article.get("id"),
                                "rejected_article_ids": [],
                            }
        except Exception as e:
            print("AI processing error:", str(e))
            esc = _escalate_no_kb_match()
            messages.append({
                "sender": "ai",
                "message": esc["user_message"],
                "createdAt": now_iso,
                "isRead": False,
            })
            summary_fallback = (ticket.message[:200] + "..." if len(ticket.message) > 200 else ticket.message)
            ticket_data = {
                "userId": uid,
                "message": ticket.message,
                "summary": summary_fallback,
                "subject": summary_fallback,
                "description": ticket.message,
                "status": esc["status"],
                "escalated": True,
                "category": None,
                "aiReply": None,
                "confidence": 0.0,
                "knowledge_used": [],
                "internal_note": esc["internal_note"] + f" (AI error: {str(e)[:200]})",
                "messages": messages,
                "createdAt": now_iso,
                "ai_mode": "article",
                "current_step": 0,
                "troubleshooting_context": {},
                "resolved": False,
                "returned_article_id": None,
                "rejected_article_ids": [],
            }

        if ticket_data is None:
            esc = _escalate_no_kb_match()
            messages.append({"sender": "ai", "message": esc["user_message"], "createdAt": now_iso, "isRead": False})
            summary_fallback = (ticket.message[:200] + "..." if len(ticket.message) > 200 else ticket.message)
            ticket_data = {
                "userId": uid,
                "message": ticket.message,
                "summary": summary_fallback,
                "subject": summary_fallback,
                "description": ticket.message,
                "status": esc["status"],
                "escalated": True,
                "category": None,
                "aiReply": None,
                "confidence": 0.0,
                "knowledge_used": [],
                "internal_note": esc["internal_note"],
                "messages": messages,
                "createdAt": now_iso,
                "ai_mode": "article",
                "current_step": 0,
                "troubleshooting_context": {},
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

        result = []
        for doc in tickets:
            ticket_data = doc.to_dict()
            if "escalated" not in ticket_data:
                ticket_data["escalated"] = (ticket_data.get("status") == "escalated" or
                                           ticket_data.get("status") == "needs_escalation")
            item = {"id": doc.id, **ticket_data}
            if _ticket_matches_filters(item, status_group, assigned_to, search):
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

        # Article mode: user says answer was wrong → re-search KB excluding that article (Step 3)
        if (
            message_request.sender == "user"
            and ticket_data.get("ai_mode") == "article"
            and not ticket_data.get("resolved")
            and not ticket_data.get("escalated")
        ):
            user_msg = message_request.message
            if _is_dissatisfaction(user_msg):
                returned_id = ticket_data.get("returned_article_id")
                rejected_ids = list(ticket_data.get("rejected_article_ids") or [])
                if returned_id:
                    rejected_ids = rejected_ids + [returned_id]
                # Load org KB (same shape as create_ticket)
                kb_ref = db.collection("knowledge_base")
                if organization_id is not None:
                    kb_stream = kb_ref.where("organization_id", "==", organization_id).stream()
                else:
                    kb_stream = kb_ref.stream()
                articles_for_scoring = []
                for doc in kb_stream:
                    article_data = doc.to_dict()
                    if article_data.get("guided_flow") or ((article_data.get("type") or "").strip().lower() == "guided"):
                        continue
                    articles_for_scoring.append({
                        "id": doc.id,
                        "title": article_data.get("title", ""),
                        "content": article_data.get("content", ""),
                        "category": article_data.get("category", ""),
                        "tags": article_data.get("tags"),
                        "summary": article_data.get("summary", ""),
                    })
                original_question = ticket_data.get("message", user_msg)
                keywords = extract_keywords(original_question)
                print("User question (re-search):", original_question)
                print("Extracted keywords:", keywords)
                print("Excluded article IDs:", rejected_ids)
                next_article, next_score, re_debug = select_best_article(
                    articles_for_scoring, keywords, exclude_article_ids=rejected_ids, original_query=original_question
                )
                log_search(original_question, re_debug, next_article.get("title") if next_article else None)

                now_iso = datetime.utcnow().isoformat()
                if next_score >= MIN_SCORE_THRESHOLD and next_article:
                    answer_result = await _answer_from_single_article(original_question, next_article)
                    if answer_result.get("aiReply") and not answer_result.get("escalated"):
                        ai_msg = {"sender": "ai", "message": answer_result["aiReply"], "createdAt": now_iso, "isRead": False}
                        messages.append(ai_msg)
                        ticket_ref.update({
                            "messages": messages,
                            "returned_article_id": next_article.get("id"),
                            "rejected_article_ids": rejected_ids,
                            "knowledge_used": [next_article.get("title", "")],
                        })
                        return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message, "ai_reply": ai_msg}
                # No acceptable next match → escalate (Step 4)
                esc = _escalate_no_kb_match()
                messages.append({"sender": "ai", "message": esc["user_message"], "createdAt": now_iso, "isRead": False})
                ticket_ref.update({
                    "messages": messages,
                    "status": esc["status"],
                    "escalated": True,
                    "internal_note": (ticket_data.get("internal_note") or "") + " " + esc["internal_note"],
                })
                return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message, "ai_reply": {"sender": "ai", "message": esc["user_message"], "createdAt": now_iso}}

        if (
            message_request.sender == "user"
            and ticket_data.get("ai_mode") == "guided"
            and not ticket_data.get("resolved")
        ):
            user_msg = message_request.message
            now_iso = datetime.utcnow().isoformat()
            context = dict(ticket_data.get("troubleshooting_context") or {})
            confusion = int(ticket_data.get("confusion_count") or 0)
            completed = bool(ticket_data.get("completed"))

            # Part 5: Resolution detection
            if is_resolution_message(user_msg):
                ai_reply = "Awesome! Glad we got that sorted. If you need anything else, I'm here."
                ai_reply = humanize_reply(ai_reply)
                messages.append({"sender": "ai", "message": ai_reply, "createdAt": now_iso, "isRead": False})
                ticket_ref.update({
                    "messages": messages,
                    "resolved": True,
                    "status": "resolved",
                    "troubleshooting_context": {**context, "resolved_at": now_iso},
                    "last_activity_timestamp": now_iso,
                    "completed": True,
                })
                print("COMPLETED:", True, "CONTEXT:", context)
                return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message, "ai_reply": {"sender": "ai", "message": ai_reply, "createdAt": now_iso}, "resolved": True}

            # Part 6: Escalation — "no"/"still not working" or 3x confusion
            if is_escalation_message(user_msg) or (completed and user_msg.strip().lower() in ("no", "n", "not yet", "didn't work")):
                escalation_msg = "I'm going to escalate this to a support specialist for further assistance."
                escalation_msg = humanize_reply(escalation_msg)
                messages.append({"sender": "ai", "message": escalation_msg, "createdAt": now_iso, "isRead": False})
                ticket_ref.update({
                    "messages": messages,
                    "ai_mode": "ai_free",
                    "status": "escalated",
                    "escalated": True,
                    "internal_note": (ticket_data.get("internal_note") or "") + f" [Escalated by user/flow at {now_iso}]",
                    "last_activity_timestamp": now_iso,
                })
                print("ESCALATED: ai_mode=ai_free")
                return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message, "ai_reply": {"sender": "ai", "message": escalation_msg, "createdAt": now_iso}}

            flow_id = ticket_data.get("flow_id") or ticket_data.get("guided_article_id")
            art_doc = db.collection("knowledge_base").document(flow_id).get() if flow_id else None
            article_raw = {"id": art_doc.id, **art_doc.to_dict()} if art_doc and art_doc.exists else None
            normalized = normalize_article_to_flow(article_raw) if article_raw else None

            # New flow[] state machine (no legacy branches)
            if normalized and normalized.get("flow") and not normalized.get("_legacy_branches"):
                flow = normalized.get("flow") or []
                current_step_id = ticket_data.get("current_step") or (flow[0].get("step_id") if flow else "step_1")
                next_step, reply_msg, new_context = flow_advance(flow, current_step_id, context, user_msg)
                if next_step is None and "Did this resolve" in (reply_msg or ""):
                    completed = True
                if reply_msg and ("I didn't catch" in reply_msg or "Please choose" in reply_msg):
                    confusion = confusion + 1
                else:
                    confusion = 0
                new_step_id = next_step.get("step_id") if next_step else current_step_id
                if next_step is None:
                    new_step_id = current_step_id
                reply_msg = humanize_reply(reply_msg or "Let me know when you've completed this step.")
                messages.append({"sender": "ai", "message": reply_msg, "createdAt": now_iso, "isRead": False})
                step_options = next_step.get("options", []) if next_step else []
                update_data = {
                    "messages": messages,
                    "troubleshooting_context": new_context,
                    "current_step": new_step_id,
                    "last_activity_timestamp": now_iso,
                    "confusion_count": min(confusion, 10),
                    "completed": completed,
                    "current_step_options": step_options,
                }
                if confusion >= 3:
                    update_data["ai_mode"] = "ai_free"
                    update_data["status"] = "escalated"
                    update_data["escalated"] = True
                print("STEP:", new_step_id, "CONTEXT:", new_context, "COMPLETED:", completed)
                ticket_ref.update(update_data)
                return {"message": "Message added successfully", "ticket_id": ticket_id, "new_message": new_message, "ai_reply": {"sender": "ai", "message": reply_msg, "createdAt": now_iso, "options": step_options}, "resolved": False}

            # Legacy branches: existing _guided_flow_respond
            guided_article_id = ticket_data.get("guided_article_id")
            guided_article = None
            if guided_article_id and article_raw and article_raw.get("id") == guided_article_id:
                guided_article = article_raw
            elif guided_article_id:
                art_ref = db.collection("knowledge_base").document(guided_article_id)
                art_doc = art_ref.get()
                if art_doc.exists:
                    guided_article = {"id": art_doc.id, **art_doc.to_dict()}
            ai_reply, new_context, resolved, escalate = _guided_flow_respond(
                ticket_data, message_request.message, guided_article
            )
            ai_message = {
                "sender": "ai",
                "message": humanize_reply(ai_reply),
                "createdAt": now_iso,
                "isRead": False
            }
            messages.append(ai_message)
            update_data = {
                "messages": messages,
                "troubleshooting_context": new_context,
                "current_step": new_context.get("step", 0),
                "last_activity_timestamp": now_iso,
            }
            if resolved:
                update_data["resolved"] = True
                update_data["status"] = "resolved"
                update_data["completed"] = True
            if escalate:
                update_data["ai_mode"] = "ai_free"
                update_data["status"] = "escalated"
                update_data["escalated"] = True
                update_data["internal_note"] = (ticket_data.get("internal_note") or "") + " [Escalated: user stuck or issue unresolved]"
            ticket_ref.update(update_data)
            print("STEP:", new_context.get("step"), "CONTEXT:", new_context, "COMPLETED:", resolved)
            return {
                "message": "Message added successfully",
                "ticket_id": ticket_id,
                "new_message": new_message,
                "ai_reply": ai_message,
                "resolved": resolved,
            }
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
