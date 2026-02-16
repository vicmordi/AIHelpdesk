"""
Conversational flow engine: legacy conversion, flow matching, step execution, resolution/escalation.
"""

import re
from typing import List, Dict, Any, Optional, Tuple

# --- Human-like response system prompt (Part 3) ---
SUPPORT_AGENT_SYSTEM = """You are a professional IT support technician.
Speak naturally and briefly.
Guide users step-by-step.
Ask one question at a time.
Wait for confirmation before continuing.
Never dump full instructions at once.
Sound helpful and calm.
Reply with ONLY the message to send to the user, no preamble."""

# --- Resolution phrases (Part 5) ---
RESOLUTION_PHRASES = (
    "it's working", "it is working", "its working",
    "resolved", "fixed", "thank you", "thanks", "that worked",
    "all good", "all set", "got it", "working now", "solved",
    "yes it did", "that did it", "perfect",
)

# --- Escalation triggers (Part 6) ---
ESCALATION_PHRASES = ("still broken", "still not working", "doesn't work", "didn't work", "no luck", "not working", "escalate", "speak to someone", "human")
CONFIRMATION_KEYWORDS = ("done", "completed", "yes", "finished", "ok", "ready", "did it", "completed it", "i'm there", "im there", "i am there")


def convert_legacy_content_to_flow(title: str, content: str, category: str = "") -> Dict[str, Any]:
    """
    Convert legacy article content into structured flow format (Part 1).
    - Break into numbered steps
    - Detect platform sections (iPhone, Android, Windows, Mac)
    - Extract trigger phrases from title and content
    """
    trigger_phrases = _extract_trigger_phrases(title, content)
    content_lower = (content or "").lower()
    title_lower = (title or "").lower()

    # Detect platform sections
    platform_headers = []
    for p in ("iphone", "android", "windows", "mac", "vpn", "on-site", "off-site", "internal", "external"):
        if p in content_lower or p in title_lower:
            platform_headers.append(p)

    flow = []
    if platform_headers and _has_multiple_platform_sections(content, platform_headers):
        # Build branching: first step is "which device?", then branch by choice
        options = [{"value": p, "label": p.replace("-", " ").title()} for p in platform_headers[:5]]
        flow.append({
            "step_id": "device",
            "message": "What device or environment are you using?",
            "options": options,
            "save_as": "device_type",
            "condition": "",
            "next": "step_1",
        })
        # Parse steps per platform (simplified: one branch per platform with shared step pattern)
        steps = _parse_numbered_steps(content)
        for i, step_text in enumerate(steps):
            flow.append({
                "step_id": f"step_{i + 1}",
                "message": step_text,
                "options": [],
                "save_as": "",
                "condition": "",
                "next": f"step_{i + 2}" if i + 2 <= len(steps) else "end",
            })
        if flow and flow[-1].get("next") == "step_" + str(len(steps) + 1):
            flow[-1]["next"] = "end"
    else:
        steps = _parse_numbered_steps(content)
        for i, step_text in enumerate(steps):
            flow.append({
                "step_id": f"step_{i + 1}",
                "message": step_text,
                "options": [],
                "save_as": "",
                "condition": "",
                "next": f"step_{i + 2}" if i + 2 <= len(steps) else "end",
            })
        if flow and flow[-1].get("next") == "step_" + str(len(steps) + 1):
            flow[-1]["next"] = "end"

    if not flow:
        flow = [{"step_id": "step_1", "message": (content or title or "Please follow the instructions provided.")[:500], "options": [], "save_as": "", "condition": "", "next": "end"}]

    return {
        "title": title,
        "category": category,
        "type": "guided",
        "trigger_phrases": trigger_phrases,
        "flow": flow,
    }


def _extract_trigger_phrases(title: str, content: str) -> List[str]:
    """Extract trigger phrases from title and first 200 chars of content."""
    phrases = []
    t = (title or "").strip().lower()
    if t and len(t) > 2:
        phrases.append(t)
        for w in t.split():
            if len(w) > 3:
                phrases.append(w)
    content_start = (content or "")[:300].lower()
    for w in re.findall(r"[a-z0-9]+", content_start):
        if 4 <= len(w) <= 20 and w not in ("that", "this", "with", "from", "have", "your", "will", "can", "the", "and", "for", "are", "you"):
            phrases.append(w)
    return list(dict.fromkeys(phrases))[:15]


def _has_multiple_platform_sections(content: str, platforms: List[str]) -> bool:
    """Heuristic: content has multiple section headers for platforms."""
    c = content.lower()
    count = sum(1 for p in platforms if re.search(rf"\b{p}\b|{p}\s*:|{p}\s*\-", c))
    return count >= 2


def _parse_numbered_steps(content: str) -> List[str]:
    """Extract numbered steps (1. 2. or Step 1 Step 2 or - bullet)."""
    if not content or not content.strip():
        return []
    steps = []
    # Step 1: ... Step 2: ...
    for m in re.finditer(r"(?:step\s*)?(\d+)[\.\):\s]+([^\n]+(?:\n(?!\s*(?:step\s*)?\d+[\.\):\s])[^\n]*)*)", content, re.I | re.DOTALL):
        steps.append(m.group(2).strip()[:400])
    if steps:
        return steps
    # 1. ... 2. ...
    for m in re.finditer(r"\n\s*(\d+)[\.\)]\s*([^\n]+(?:\n(?!\s*\d+[\.\)])[^\n]*)*)", content, re.DOTALL):
        steps.append(m.group(2).strip()[:400])
    if steps:
        return steps
    # Split by double newline or bullet
    parts = re.split(r"\n\s*[\-\*]\s+|\n\n+", content)
    parts = [p.strip()[:400] for p in parts if p.strip() and len(p.strip()) > 10]
    return parts[:15] if parts else [content.strip()[:400]]


def normalize_article_to_flow(article: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Normalize article to unified shape: type, trigger_phrases, flow[].
    - If article has type "guided" and flow[]: validate and return.
    - If article has guided_flow + branches (legacy): convert to flow[].
    - If type missing or "static": convert content to flow via convert_legacy_content_to_flow.
    """
    art_type = (article.get("type") or "").strip().lower()
    flow = article.get("flow")
    if isinstance(flow, list) and len(flow) > 0:
        trigger_phrases = article.get("trigger_phrases") or _extract_trigger_phrases(article.get("title", ""), article.get("content", ""))
        # Ensure each step has next or terminate
        for i, s in enumerate(flow):
            if not s.get("next") and i < len(flow) - 1:
                s["next"] = flow[i + 1].get("step_id", f"step_{i + 2}")
            if i == len(flow) - 1 and not s.get("next"):
                s["next"] = "end"
        return {
            "id": article.get("id"),
            "title": article.get("title", ""),
            "category": article.get("category", ""),
            "type": "guided",
            "trigger_phrases": trigger_phrases,
            "flow": flow,
        }

    # Legacy: guided_flow + branches (keep for existing _guided_flow_respond in tickets)
    branches = article.get("guided_branches") or article.get("branches")
    if isinstance(branches, dict) and len(branches) >= 1:
        branch_names = list(branches.keys())
        device_step = {
            "step_id": "device",
            "message": "What device are you using?",
            "options": [{"value": b, "label": b.replace("_", " ").title()} for b in branch_names],
            "save_as": "device_type",
            "condition": "",
            "next": "step_1",
        }
        trigger = article.get("trigger_phrases") or _extract_trigger_phrases(article.get("title", ""), article.get("content", ""))
        return {
            "id": article.get("id"),
            "title": article.get("title", ""),
            "category": article.get("category", ""),
            "type": "guided",
            "trigger_phrases": trigger,
            "flow": [device_step],
            "_legacy_branches": branches,
        }

    # Legacy static: convert content to flow
    title = article.get("title", "")
    content = article.get("content", "")
    category = article.get("category", "")
    converted = convert_legacy_content_to_flow(title, content, category)
    converted["id"] = article.get("id")
    return converted


def _get_branch_steps_legacy(branch_data: Any) -> List[str]:
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


def match_flow_by_trigger(user_message: str, articles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Search KB by trigger_phrases; return first article where type is guided and triggers match.
    """
    msg_lower = (user_message or "").lower().strip()
    if not msg_lower:
        return None
    msg_words = set(w for w in msg_lower.split() if len(w) > 2)
    for art in articles:
        normalized = normalize_article_to_flow(art)
        if not normalized or normalized.get("type") != "guided":
            continue
        triggers = normalized.get("trigger_phrases") or []
        title = (normalized.get("title") or "").lower()
        content = (art.get("content") or "").lower()
        combined = f"{title} {' '.join(str(t) for t in triggers)} {content[:500]}"
        if msg_words and not any(w in combined for w in msg_words):
            continue
        if triggers and not any(t in msg_lower for t in (str(ph).lower() for ph in triggers[:5])):
            if not any(w in title for w in msg_words):
                continue
        return normalized
    return None


def is_resolution_message(message: str) -> bool:
    """Part 5: Detect resolution phrases."""
    m = (message or "").lower().strip()
    return any(p in m for p in RESOLUTION_PHRASES)


def is_escalation_message(message: str) -> bool:
    """Part 6: User wants to escalate."""
    m = (message or "").lower().strip()
    return any(p in m for p in ESCALATION_PHRASES)


def is_confirmation_message(message: str) -> bool:
    """User confirmed step (done, yes, etc.)."""
    m = (message or "").lower().strip()
    return any(p in m for p in CONFIRMATION_KEYWORDS) or m in ("yes", "y", "ok", "k")


def flow_get_first_message(flow: List[Dict]) -> str:
    """Return the first step message (for device question or step 1)."""
    if not flow:
        return "I can help with that. What would you like to do?"
    return flow[0].get("message", "Let's get started.")


def flow_advance(
    flow: List[Dict],
    current_step_id: str,
    context: Dict[str, Any],
    user_message: str,
) -> Tuple[Optional[Dict], Optional[str], Dict[str, Any]]:
    """
    Advance flow state. Returns (next_step_dict, reply_message, new_context).
    - If current step has options: validate user choice, save to context, return next step.
    - If current step requires confirmation: if user said done/yes, go to next; else re-send current step.
    - If no next step: return (None, "Did this resolve your issue?", context) for completion.
    """
    context = dict(context or {})
    step_index = next((i for i, s in enumerate(flow) if s.get("step_id") == current_step_id), None)
    if step_index is None:
        step_index = 0
    current_step = flow[step_index] if 0 <= step_index < len(flow) else flow[0]
    msg_lower = (user_message or "").lower().strip()

    # Step has options (e.g. device choice)
    options = current_step.get("options") or []
    if options:
        choice = None
        for opt in options:
            val = (opt.get("value") or opt.get("label") or "").lower()
            lab = (opt.get("label") or opt.get("value") or "").lower()
            if msg_lower == val or msg_lower == lab or msg_lower in val or val in msg_lower:
                choice = opt.get("value") or opt.get("label")
                break
        if not choice and msg_lower.isdigit():
            idx = int(msg_lower)
            if 1 <= idx <= len(options):
                choice = options[idx - 1].get("value") or options[idx - 1].get("label")
        if choice:
            save_as = current_step.get("save_as")
            if save_as:
                context[save_as] = choice
            next_id = current_step.get("next") or "step_1"
            next_step = next((s for s in flow if s.get("step_id") == next_id), None)
            if next_step:
                return (next_step, next_step.get("message"), context)
            return (None, "Did this resolve your issue?", context)
        return (current_step, "I didn't catch that. Please choose one of the options above.", context)

    # Step is instruction; need confirmation to advance
    if is_confirmation_message(user_message):
        next_id = current_step.get("next") or "end"
        if next_id == "end":
            return (None, "It looks like we've completed all steps. Did this resolve your issue?", context)
        next_step = next((s for s in flow if s.get("step_id") == next_id), None)
        if next_step:
            return (next_step, next_step.get("message"), context)
        return (None, "It looks like we've completed all steps. Did this resolve your issue?", context)

    # User didn't confirm: re-send current step
    return (current_step, current_step.get("message", "Let me know when you've completed this step."), context)


def flow_get_step_by_index(flow: List[Dict], index: int) -> Optional[Dict]:
    """Get step by 0-based index."""
    if 0 <= index < len(flow):
        return flow[index]
    return None
