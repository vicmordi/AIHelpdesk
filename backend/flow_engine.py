"""
Universal troubleshooting flow engine: classification, normalization, step execution, lifecycle.
Production-grade conversational engine for all KB article types.
"""

import re
import random
from typing import List, Dict, Any, Optional, Tuple

# --- Phase 1: Universal article classification ---
ARTICLE_TYPES = ("flow", "guide", "single_action", "reference")

# --- Response variation pools (Phase 6: human-like rotation) ---
ADVANCE_VARIATIONS = (
    "Nice, we're making progress.",
    "Good, let's move to the next step.",
    "Alright, here's what to do next.",
    "Great job, almost there.",
    "Perfect! 👍",
    "Got it.",
)
CLARIFICATION_VARIATIONS = (
    "I didn't catch that. Please choose one of the options above.",
    "Could you pick one of the options?",
    "Which option applies to you?",
)
COMPLETION_VARIATIONS = (
    "You're all set. This should resolve the issue.\n\nIf you're still experiencing problems, I can escalate this to a support engineer.",
    "That's everything on my side. If it's still not working, I can escalate this to a support engineer.",
    "You're all set. If you're still having issues, I can escalate this to a support specialist.",
)
ESCALATION_VARIATIONS = (
    "I'm going to escalate this to a support specialist for further assistance.",
    "Let me escalate this to a support engineer who can help further.",
    "I'll pass this to a support specialist.",
)


def _pick(items: tuple) -> str:
    """Safe random choice for response variation."""
    if not items:
        return ""
    return random.choice(items)


def log_flow_event(event: str, **kwargs: Any) -> None:
    """Phase 9: Logging for article selection, branch, step progression."""
    parts = [f"FLOW | {event}"]
    for k, v in kwargs.items():
        parts.append(f"{k}={v}")
    print(" | ".join(parts))


# --- Legacy compatibility ---
SUPPORT_AGENT_SYSTEM = """You are a professional IT support technician.
Speak naturally and briefly. Guide users step-by-step.
Reply with ONLY the message to send to the user, no preamble."""

RESOLUTION_PHRASES = (
    "it's working", "it is working", "its working",
    "resolved", "fixed", "thank you", "thanks", "that worked",
    "all good", "all set", "got it", "working now", "solved",
    "yes it did", "that did it", "perfect", "fixed", "that worked",
)
ESCALATION_PHRASES = (
    "still broken", "still not working", "doesn't work", "didn't work",
    "no luck", "not working", "escalate", "speak to someone", "human",
    "this didn't help", "this didnt help", "didnt help", "wrong", "not helpful",
)
CONFIRMATION_KEYWORDS = (
    "done", "completed", "yes", "finished", "ok", "ready", "did it", "completed it",
    "i'm there", "im there", "i am there", "ive gone", "i've gone", "got it", "did that",
    "next", "fixed", "that worked",
)


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

    # Device sections: only actual devices (iPhone, Android, etc.)—not environments like "internal" or "vpn"
    DEVICE_PLATFORMS = ("iphone", "android", "windows", "mac")
    platform_headers = []
    for p in DEVICE_PLATFORMS:
        if p in content_lower or p in title_lower:
            platform_headers.append(p)

    flow = []
    platform_steps: Dict[str, List[str]] = {}
    if platform_headers and _has_multiple_platform_sections(content, platform_headers):
        # Parse steps per platform - NEVER mix iPhone and Android
        platform_steps = _parse_content_by_platform(content, platform_headers)
        if not platform_steps:
            platform_steps = {p.lower(): _parse_numbered_steps(content) for p in platform_headers[:5]}
        # Build branching: "What device are you using?" + iPhone / Android options
        options = [{"value": p.lower(), "label": p.replace("-", " ").title()} for p in platform_headers[:5]]
        flow.append({
            "step_id": "device",
            "message": "What device are you using?",
            "options": options,
            "save_as": "device_type",
            "condition": "",
            "next": "step_1",
        })
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

    out: Dict[str, Any] = {
        "title": title,
        "category": category,
        "type": "guided",
        "trigger_phrases": trigger_phrases,
        "flow": flow,
    }
    if platform_steps:
        out["_platform_steps"] = platform_steps
    return out


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


def _parse_content_by_platform(content: str, platform_headers: List[str]) -> Dict[str, List[str]]:
    """
    Split content by platform sections and extract steps for each platform only.
    Returns e.g. {"iphone": [step1, step2], "android": [step1, step2]}.
    NEVER mix iPhone and Android steps.
    """
    if not content or not platform_headers:
        return {}
    result: Dict[str, List[str]] = {}
    content_lower = content.lower()
    # Split by platform headers: iPhone, Android, etc.
    for i, platform in enumerate(platform_headers):
        p_lower = platform.lower()
        # Pattern: "iPhone" or "iPhone:" or "iPhone -" or "## iPhone" at start of line/section
        pat = rf"(?:\n|^)\s*[#\-]*\s*{re.escape(p_lower)}\s*[:\-\s]*\s*\n"
        parts = re.split(pat, content_lower, flags=re.I | re.MULTILINE)
        # Find section for this platform: after this platform header, before next platform
        section = ""
        for j, part in enumerate(parts):
            if j == 0 and i > 0:
                continue
            if j == 1 or (i == 0 and j == 0):
                section = part
                break
            if j == i + 1:
                section = part
                break
        if not section:
            # Fallback: try splitting by platform name as delimiter
            idx = content_lower.find(p_lower)
            if idx >= 0:
                start = idx + len(p_lower)
                next_platform_start = len(content)
                for op in platform_headers:
                    if op.lower() != p_lower:
                        ni = content_lower.find(op.lower(), start)
                        if 0 <= ni < next_platform_start:
                            next_platform_start = ni
                section = content[start:next_platform_start]
            else:
                section = content
        steps = _parse_numbered_steps(section)
        # Strip any mention of OTHER platforms from each step
        other_platforms = [x.lower() for x in platform_headers if x.lower() != p_lower]
        cleaned = []
        for s in steps:
            s_lower = s.lower()
            # Remove phrases like "on Android", "for Android", "iPhone or Android", etc.
            cleaned_s = s
            for op in other_platforms:
                cleaned_s = re.sub(rf"\s*(?:on|for|or|and)\s+{op}[^\n.]*\.?", " ", cleaned_s, flags=re.I)
                cleaned_s = re.sub(rf"{op}\s*(?:or|and)\s+{p_lower}", p_lower, cleaned_s, flags=re.I)
                cleaned_s = re.sub(rf"{p_lower}\s*(?:or|and)\s+{op}", p_lower, cleaned_s, flags=re.I)
            cleaned.append(cleaned_s.strip() or s)
        result[p_lower] = cleaned if cleaned else _parse_numbered_steps(content)
    return result


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

    # Legacy: guided_flow + branches — only add device step when article has multiple device options
    branches = article.get("guided_branches") or article.get("branches")
    if isinstance(branches, dict) and len(branches) >= 2:
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


def get_article_type(article: Dict[str, Any]) -> str:
    """
    Phase 1: Universal classification. Returns one of flow, guide, single_action, reference.
    Backward compat: if article_type missing, derive from type / guided_flow.
    """
    at = (article.get("article_type") or "").strip().lower()
    if at in ARTICLE_TYPES:
        return at
    t = (article.get("type") or "").strip().lower()
    if t == "guided" or article.get("guided_flow"):
        return "flow"
    if t == "static":
        return "guide"
    return "guide"


def is_flow_capable(article: Dict[str, Any]) -> bool:
    """
    Flow-first: True if article can be used for step-by-step troubleshooting.
    Any article with flow structure OR parseable steps uses flow mode.
    """
    if not article:
        return False
    if article.get("guided_flow") or (article.get("type") or "").strip().lower() == "guided":
        return True
    if isinstance(article.get("flow"), list) and len(article.get("flow", [])) > 0:
        return True
    branches = article.get("guided_branches") or article.get("branches")
    if isinstance(branches, dict) and len(branches) > 0:
        return True
    content = (article.get("content") or "").strip()
    if not content:
        return False
    parsed = _parse_numbered_steps(content)
    return len(parsed) >= 1


def universal_normalize_flow(article: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Phase 2: Normalize any article into canonical flow structure.
    Returns: { "type": "flow", "id", "title", "steps": [{step, text}], "branches": {branch_name: [step_texts]} }
    or None if not a flow article.
    """
    if get_article_type(article) != "flow":
        return None
    normalized = normalize_article_to_flow(article)
    if not normalized:
        return None
    aid = normalized.get("id") or article.get("id")
    title = normalized.get("title") or article.get("title") or ""
    branches = normalized.get("_platform_steps") or normalized.get("_legacy_branches")
    steps_flat: List[Dict[str, Any]] = []
    branches_out: Dict[str, List[str]] = {}

    if isinstance(branches, dict) and len(branches) >= 1:
        for branch_name, step_list in branches.items():
            if isinstance(step_list, list):
                branches_out[str(branch_name).lower()] = [str(s).strip() for s in step_list if s]
        if branches_out:
            first_branch = next(iter(branches_out.values()), [])
            steps_flat = [{"step": i + 1, "text": t} for i, t in enumerate(first_branch)]
    flow = normalized.get("flow") or []
    if not steps_flat and flow:
        for i, s in enumerate(flow):
            if (s.get("step_id") or "").startswith("step_") or (s.get("step_id") or "").startswith("platform_step_"):
                steps_flat.append({"step": i + 1, "text": s.get("message", "").strip()})
    if not steps_flat and flow:
        steps_flat = [{"step": i + 1, "text": s.get("message", "").strip()} for i, s in enumerate(flow) if s.get("message")]

    return {
        "type": "flow",
        "id": aid,
        "title": title,
        "steps": steps_flat,
        "branches": branches_out,
        "_normalized": normalized,
    }


def match_flow_by_trigger(user_message: str, articles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Search KB by relevance scoring (intent-aware). Returns best guided article only if score >= threshold.
    Uses kb_search to avoid wrong matches (e.g. password article for "set up company email").
    """
    try:
        from kb_search import extract_keywords, select_best_article, MIN_SCORE_THRESHOLD
        guided_articles = []
        for art in articles:
            normalized = normalize_article_to_flow(art)
            if not normalized or normalized.get("type") != "guided":
                continue
            guided_articles.append({
                "id": art.get("id"),
                "title": art.get("title", ""),
                "content": art.get("content", ""),
                "category": art.get("category", ""),
                "tags": art.get("tags"),
                "summary": art.get("summary", ""),
            })
        if not guided_articles:
            return None
        keywords = extract_keywords(user_message)
        best_article, score, _ = select_best_article(
            guided_articles, keywords, original_query=user_message
        )
        if not best_article or score < MIN_SCORE_THRESHOLD:
            return None
        # Map back to full article for normalization
        art_by_id = {a.get("id"): a for a in articles if a.get("id")}
        full_art = art_by_id.get(best_article.get("id"))
        if not full_art:
            return None
        return normalize_article_to_flow(full_art)
    except Exception:
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


def flow_get_first_message(flow: List[Dict], article_title: str = "") -> str:
    """Return first step only. Never dump full article. Human-like opener."""
    if not flow:
        return "I can help with that. What would you like to do?"
    first = flow[0]
    msg = first.get("message", "Let's get started.")
    options = first.get("options") or []
    topic = (article_title or "this").lower()
    if options and "device" in (first.get("step_id") or "").lower():
        msg = f"Great — I'll guide you through {topic}. It'll only take a few minutes.\n\nWhat device are you using?\n\n" + "\n".join(
            f"{i+1}️⃣ {opt.get('label', opt.get('value', '')).replace('-', ' ').title()}" for i, opt in enumerate(options[:5])
        )
    elif not options and first.get("step_id") and "device" not in (first.get("step_id") or "").lower():
        msg = f"Great, I'll guide you through {topic}.\n\n**Step 1:**\n{msg}\n\nLet me know when you're there."
    return msg


def get_completion_reply() -> str:
    """Phase 5: Smart flow termination message (variation)."""
    return _pick(COMPLETION_VARIATIONS)


def get_escalation_reply() -> str:
    """Phase 6: Escalation message (variation)."""
    return _pick(ESCALATION_VARIATIONS)


def _format_platform_step(
    step_index: int, total_steps: int, instruction: str,
    device: str, article_title: str, is_first: bool,
) -> str:
    """Human-like step message for platform-specific flow (with variation)."""
    advance = _pick(ADVANCE_VARIATIONS)
    device_label = (device or "").replace("_", " ").title()
    topic = article_title or "this"
    if is_first and step_index == 1:
        return (
            f"{advance} I'll guide you through {topic} on your {device_label}.\n\n"
            f"**First step:**\n{instruction}\n\n"
            "Let me know when you're there."
        )
    if step_index < total_steps:
        return (
            f"{advance}\n\n**Step {step_index}:**\n{instruction}\n\n"
            "Let me know when you've done that."
        )
    return (
        f"Almost there! 🎯\n\n**Step {step_index}:**\n{instruction}\n\n"
        "Let me know when you've completed this step."
    )


def flow_advance(
    flow: List[Dict],
    current_step_id: str,
    context: Dict[str, Any],
    user_message: str,
    platform_steps: Optional[Dict[str, List[str]]] = None,
    article_title: str = "",
) -> Tuple[Optional[Dict], Optional[str], Dict[str, Any]]:
    """
    Advance flow state. Returns (next_step_dict, reply_message, new_context).
    When platform_steps is set: only use steps for LOCKED device (never mix iPhone/Android).
    Human-like messaging; clean ending.
    """
    context = dict(context or {})
    platform_steps = platform_steps or {}
    msg_lower = (user_message or "").lower().strip()

    # Platform-specific flow: device step + steps from platform_steps[device] only
    device_context = context.get("device_type", "").lower()
    steps = platform_steps.get(device_context, []) if device_context else []
    total_steps = len(steps)
    step_index = int(context.get("platform_step_index", 1))

    # Current step is device choice
    step_index_in_flow = next((i for i, s in enumerate(flow) if s.get("step_id") == current_step_id), None)
    if step_index_in_flow is None:
        step_index_in_flow = 0
    current_step = flow[step_index_in_flow] if 0 <= step_index_in_flow < len(flow) else flow[0]
    options = current_step.get("options") or []

    if options and not device_context:
        # Device choice step - user has not selected yet
        choice = None
        for opt in options:
            val = (opt.get("value") or opt.get("label") or "").lower()
            lab = (opt.get("label") or opt.get("value") or "").lower()
            if msg_lower == val or msg_lower == lab or msg_lower in val or val in msg_lower:
                choice = (opt.get("value") or opt.get("label") or "").lower()
                break
        if not choice and msg_lower.isdigit():
            idx = int(msg_lower)
            if 1 <= idx <= len(options):
                choice = (options[idx - 1].get("value") or options[idx - 1].get("label") or "").lower()
        if choice:
            context["device_type"] = choice
            if platform_steps:
                steps = platform_steps.get(choice, [])
                if steps:
                    context["platform_step_index"] = 1
                    inst = steps[0]
                    reply = _format_platform_step(1, len(steps), inst, choice, article_title, is_first=True)
                    return ({"step_id": "platform_step_1", "message": inst}, reply, context)
            context["flow_completed"] = True
            return (None, get_completion_reply(), context)
        return (current_step, _pick(CLARIFICATION_VARIATIONS), context)

    # Platform steps flow: we have device locked, use ONLY that device's steps
    if platform_steps and device_context and steps:
        if is_confirmation_message(msg_lower):
            if step_index < total_steps:
                next_idx = step_index + 1
                context["platform_step_index"] = next_idx
                inst = steps[next_idx - 1]
                reply = _format_platform_step(next_idx, total_steps, inst, device_context, article_title, is_first=False)
                return ({"step_id": f"platform_step_{next_idx}", "message": inst}, reply, context)
            else:
                context["flow_completed"] = True
                return (None, get_completion_reply(), context)
        # Re-send current step
        if step_index <= total_steps:
            inst = steps[step_index - 1]
            reply = _format_platform_step(step_index, total_steps, inst, device_context, article_title, is_first=(step_index == 1))
            return ({"step_id": f"platform_step_{step_index}", "message": inst}, reply, context)

    def _humanize_step(step_dict: Dict, step_idx: int, total: int) -> str:
        """Human-like step message for non-platform flows."""
        raw = step_dict.get("message", "Let me know when you're done.")
        if step_idx == 1 and total >= 1:
            return f"I'll guide you through {article_title or 'this'}. It'll only take a few minutes.\n\n**First step:**\n{raw}\n\nLet me know when you're there."
        if step_idx < total:
            return f"Perfect! 👍\n\n**Step {step_idx}:**\n{raw}\n\nLet me know when you've done that."
        return f"Almost there! 🎯\n\n**Step {step_idx}:**\n{raw}\n\nLet me know when you've completed this step."

    instruction_steps = [s for s in flow if (s.get("step_id") or "").startswith("step_")]
    total_instruction_steps = len(instruction_steps)

    # Fallback: original flow (no platform_steps)
    if options and device_context:
        next_id = current_step.get("next") or "step_1"
        next_step = next((s for s in flow if s.get("step_id") == next_id), None)
        if next_step:
            idx = int((next_id or "step_1").replace("step_", "") or 1)
            reply = _humanize_step(next_step, idx, total_instruction_steps)
            return (next_step, reply, context)
        context["flow_completed"] = True
        return (None, get_completion_reply(), context)

    if is_confirmation_message(msg_lower):
        next_id = current_step.get("next") or "end"
        if next_id == "end":
            context["flow_completed"] = True
            return (None, get_completion_reply(), context)
        next_step = next((s for s in flow if s.get("step_id") == next_id), None)
        if next_step:
            idx = int((next_id or "step_1").replace("step_", "") or 1)
            reply = _humanize_step(next_step, idx, total_instruction_steps)
            return (next_step, reply, context)
        context["flow_completed"] = True
        return (None, get_completion_reply(), context)

    raw = current_step.get("message", "Let me know when you've completed this step.")
    idx = int((current_step.get("step_id") or "step_1").replace("step_", "") or 1)
    reply = _humanize_step(current_step, idx, total_instruction_steps)
    return (current_step, reply, context)


def flow_get_step_by_index(flow: List[Dict], index: int) -> Optional[Dict]:
    """Get step by 0-based index."""
    if 0 <= index < len(flow):
        return flow[index]
    return None
