"""
Phase 3: Universal weighted article retrieval.
Tokenize query and article fields; score by weight (title > tags > category > content).
Never select on a single shared word.
"""

import re
from typing import List, Dict, Any, Optional, Tuple

# Minimum score to return an article; below this we escalate
MIN_SCORE_THRESHOLD = 5.0

# Phase 3: Never select based on single keyword match
MIN_KEYWORD_MATCHES = 2

# Score gap: if top two articles are within this, use intent to disambiguate
CLOSE_SCORE_GAP = 2.0

# Weighted scoring (Phase 3)
WEIGHT_TITLE = 4.0
WEIGHT_TAGS = 3.0
WEIGHT_CATEGORY = 2.0
WEIGHT_CONTENT = 1.0
WEIGHT_SUMMARY = 1.5

# Stop words (normalized lowercase)
STOP_WORDS = frozenset({
    "how", "do", "i", "the", "is", "a", "an", "to", "of", "and", "in", "for", "on", "with",
    "at", "by", "from", "as", "it", "that", "this", "be", "are", "was", "were", "been",
    "have", "has", "had", "can", "could", "would", "should", "will", "my", "me", "we",
    "what", "when", "where", "which", "who", "why", "get", "got", "need", "want", "like",
    "up",  # "set up" -> ["set", "company", "email"]
})

# Intent signals: phrases/words that indicate user intent
INTENT_EMAIL_SETUP = frozenset({"set", "setup", "configure", "add", "account", "company", "email", "mail", "exchange", "outlook"})
INTENT_PASSWORD_RESET = frozenset({"reset", "forgot", "change", "password", "recover"})
INTENT_VPN = frozenset({"vpn", "connect", "remote", "network"})
INTENT_DEVICE = frozenset({"iphone", "android", "phone", "mobile", "device"})


def normalize_text(text: str) -> str:
    """Lowercase, remove punctuation, collapse spaces."""
    if not text:
        return ""
    s = (text or "").lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def extract_keywords(question: str) -> List[str]:
    """
    Normalize and extract meaningful tokens (remove stop words).
    Example: "How do I set up company email?" -> ["set", "company", "email"]
    """
    normalized = normalize_text(question)
    if not normalized:
        return []
    words = normalized.split()
    return [w for w in words if w and w not in STOP_WORDS and len(w) > 1]


def classify_intent(query: str) -> Tuple[str, float]:
    """
    Classify user intent from query.
    Returns (intent, confidence): "email_setup" | "password_reset" | "vpn" | "unclear", 0.0-1.0.
    """
    keywords = set(extract_keywords(query))
    if not keywords:
        return ("unclear", 0.0)

    email_signals = len(keywords & INTENT_EMAIL_SETUP)
    password_signals = len(keywords & INTENT_PASSWORD_RESET)
    vpn_signals = len(keywords & INTENT_VPN)

    # Strong intent: multiple signals in one category
    if password_signals >= 1 and email_signals == 0:
        return ("password_reset", 0.9 if password_signals >= 2 else 0.7)
    if email_signals >= 2 and password_signals == 0:
        return ("email_setup", 0.9)
    if email_signals >= 1 and "setup" in keywords or "set" in keywords or "configure" in keywords:
        return ("email_setup", 0.8)
    if vpn_signals >= 1:
        return ("vpn", 0.8)

    # Weak: "email" alone could be setup or password (password reset often mentions email)
    if "email" in keywords and password_signals >= 1:
        return ("password_reset", 0.6)
    if "email" in keywords and ("set" in keywords or "company" in keywords or "setup" in keywords):
        return ("email_setup", 0.85)

    return ("unclear", 0.0)


def _field_text(article: Dict[str, Any], key: str) -> str:
    val = article.get(key)
    if val is None:
        return ""
    if isinstance(val, list):
        return " ".join(str(x) for x in val).lower()
    return (str(val) or "").lower()


def _word_match(text: str, keyword: str) -> bool:
    """True if keyword appears as whole word in text (avoids 'set' matching 'reset')."""
    if not text or not keyword:
        return False
    return bool(re.search(rf"\b{re.escape(keyword)}\b", text, re.I))


def _article_intent_hints(article: Dict[str, Any]) -> set:
    """
    Extract intent hints from article. Title/category weighted heavily.
    Avoid adding email_setup just because 'email' appears (password reset often mentions email).
    """
    title = _field_text(article, "title")
    category = _field_text(article, "category")
    content = _field_text(article, "content")[:500]
    title_tokens = set(re.findall(r"\b\w{3,}\b", title))
    combined = f"{title} {category}"
    tokens = set(re.findall(r"\b\w{3,}\b", combined))
    hints = set()

    # Password reset: title has reset/forgot/password
    if tokens & INTENT_PASSWORD_RESET:
        hints.add("password_reset")

    # Email setup: title must suggest setup (not just "email" - that appears in password articles too)
    setup_signals = {"setup", "configure", "add", "account", "company"}
    if title_tokens & setup_signals or "set up" in title or "setup" in title:
        hints.add("email_setup")
    elif (title_tokens & {"company", "email"}) and "password" not in title and "reset" not in title:
        hints.add("email_setup")

    if tokens & INTENT_VPN:
        hints.add("vpn")
    return hints


def score_article(
    article: Dict[str, Any],
    keywords: List[str],
    intent: str,
) -> Tuple[float, int]:
    """
    Phase 3: Weighted relevance scoring.
    Title (highest), tags (high), category (medium), content (lower).
    Returns (score, distinct_keyword_matches). Never select on single shared word.
    """
    if not keywords:
        return (0.0, 0)

    title = _field_text(article, "title")
    category = _field_text(article, "category")
    content = _field_text(article, "content")
    tags_text = _field_text(article, "tags")
    summary = _field_text(article, "summary")

    score = 0.0
    matched_keywords: set = set()

    for kw in keywords:
        if _word_match(title, kw):
            score += WEIGHT_TITLE
            matched_keywords.add(kw)
        if tags_text and _word_match(tags_text, kw):
            score += WEIGHT_TAGS
            matched_keywords.add(kw)
        if category and _word_match(category, kw):
            score += WEIGHT_CATEGORY
            matched_keywords.add(kw)
        if _word_match(content, kw):
            score += WEIGHT_CONTENT
            matched_keywords.add(kw)
        if summary and _word_match(summary, kw):
            score += WEIGHT_SUMMARY
            matched_keywords.add(kw)

    # Exact phrase in title: bonus
    phrase = " ".join(keywords)
    if phrase in title:
        score += 3.0

    # Intent alignment (legacy): boost/penalty
    hints = _article_intent_hints(article)
    if intent != "unclear":
        if intent in hints:
            score += 4.0
        else:
            if intent == "email_setup" and "password_reset" in hints and "email_setup" not in hints:
                score -= 10.0
            elif intent == "password_reset" and "email_setup" in hints and "password_reset" not in hints:
                score -= 10.0

    return (max(0.0, score), len(matched_keywords))


def select_best_article(
    articles: List[Dict[str, Any]],
    keywords: List[str],
    exclude_article_ids: Optional[List[str]] = None,
    original_query: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], float, Dict[str, Any]]:
    """
    Rank articles by relevance; apply intent disambiguation.
    Returns (best_article, score, debug_info).
    original_query: if provided, used for intent classification (better than keywords alone).
    """
    exclude = set(exclude_article_ids or [])
    query_for_intent = (original_query or "").strip() or " ".join(keywords)
    intent, _ = classify_intent(query_for_intent)

    scored = []
    for art in articles:
        aid = art.get("id")
        if aid and aid in exclude:
            continue
        s, match_count = score_article(art, keywords, intent)
        scored.append((art, s, match_count))

    if not scored:
        debug = {"intent": intent, "keywords": keywords, "scores": []}
        return (None, 0.0, debug)

    scored.sort(key=lambda x: -x[1])
    best_article, best_score, best_matches = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0.0

    debug = {
        "intent": intent,
        "keywords": keywords,
        "scores": [(a.get("title"), s) for a, s, _ in scored[:5]],
        "best_title": best_article.get("title"),
        "best_score": best_score,
        "best_keyword_matches": best_matches,
        "second_score": second_score,
        "close_call": (best_score - second_score) <= CLOSE_SCORE_GAP if len(scored) > 1 else False,
    }

    # Phase 3: Never select on single shared word
    if best_matches < MIN_KEYWORD_MATCHES:
        debug["escalation_reason"] = "single_word_match"
        return (None, best_score, debug)

    if best_score < MIN_SCORE_THRESHOLD:
        debug["escalation_reason"] = "below_threshold"
        return (None, best_score, debug)

    # If scores are close and intent is unclear, escalate (don't guess)
    if len(scored) > 1 and (best_score - second_score) <= CLOSE_SCORE_GAP and intent == "unclear":
        debug["escalation_reason"] = "close_scores_unclear_intent"
        return (None, best_score, debug)

    return (best_article, best_score, debug)


def log_search(query: str, debug_info: Dict[str, Any], selected: Optional[str]) -> None:
    """Step 8: Log for debugging."""
    print("KB_SEARCH | User query:", query)
    print("KB_SEARCH | Extracted keywords:", debug_info.get("keywords", []))
    print("KB_SEARCH | Intent classification:", debug_info.get("intent", "unclear"))
    print("KB_SEARCH | Article scores:", debug_info.get("scores", []))
    print("KB_SEARCH | Selected article:", selected or "(none - escalated)")
    if debug_info.get("escalation_reason"):
        print("KB_SEARCH | Escalation reason:", debug_info["escalation_reason"])
