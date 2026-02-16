"""
Strict knowledge base search: keyword extraction, scoring, single-article selection.
Only uses the organization's KB; never guesses or uses outside knowledge.
"""

import re
from typing import List, Dict, Any, Optional, Tuple

# Minimum score to return an article; below this we escalate
MIN_SCORE_THRESHOLD = 2.0

# Stop words to remove when extracting keywords (normalized lowercase)
STOP_WORDS = frozenset({
    "how", "do", "i", "the", "is", "a", "an", "to", "of", "and", "in", "for", "on", "with",
    "at", "by", "from", "as", "it", "that", "this", "be", "are", "was", "were", "been",
    "have", "has", "had", "can", "could", "would", "should", "will", "my", "me", "we",
    "what", "when", "where", "which", "who", "why", "get", "got", "need", "want", "like",
})

# Weights per field (exact match of keyword in that field)
WEIGHT_TITLE = 2.0
WEIGHT_TAGS = 1.0
WEIGHT_CATEGORY = 1.0
WEIGHT_SUMMARY = 0.5
WEIGHT_CONTENT = 0.25


def normalize_text(text: str) -> str:
    """Lowercase and remove punctuation (keep alphanumeric and spaces)."""
    if not text:
        return ""
    s = (text or "").lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def extract_keywords(question: str) -> List[str]:
    """
    Normalize question and extract keywords (remove stop words).
    Example: "How do I set up company email?" -> ["set", "up", "company", "email"]
    """
    normalized = normalize_text(question)
    if not normalized:
        return []
    words = normalized.split()
    return [w for w in words if w and w not in STOP_WORDS and len(w) > 1]


def _field_text(article: Dict[str, Any], key: str) -> str:
    val = article.get(key)
    if val is None:
        return ""
    if isinstance(val, list):
        return " ".join(str(x) for x in val).lower()
    return (str(val) or "").lower()


def score_article(article: Dict[str, Any], keywords: List[str]) -> float:
    """
    Score one article against keywords.
    +2 per keyword in title, +1 in tags, +1 in category, +0.5 in summary, +0.25 in content.
    """
    if not keywords:
        return 0.0
    total = 0.0
    title = _field_text(article, "title")
    category = _field_text(article, "category")
    tags_text = _field_text(article, "tags")
    summary = _field_text(article, "summary")
    content = _field_text(article, "content")

    for kw in keywords:
        if kw in title:
            total += WEIGHT_TITLE
        if tags_text and kw in tags_text:
            total += WEIGHT_TAGS
        if category and kw in category:
            total += WEIGHT_CATEGORY
        if summary and kw in summary:
            total += WEIGHT_SUMMARY
        if kw in content:
            total += WEIGHT_CONTENT

    return total


def select_best_article(
    articles: List[Dict[str, Any]],
    keywords: List[str],
    exclude_article_ids: Optional[List[str]] = None,
) -> Tuple[Optional[Dict[str, Any]], float]:
    """
    Rank articles by score; exclude any whose id is in exclude_article_ids.
    Returns (best_article, score) or (None, 0.0) if no articles.
    """
    exclude = set(exclude_article_ids or [])
    scored = []
    for art in articles:
        aid = art.get("id")
        if aid and aid in exclude:
            continue
        s = score_article(art, keywords)
        scored.append((art, s))
    if not scored:
        return (None, 0.0)
    scored.sort(key=lambda x: -x[1])
    best_article, best_score = scored[0]
    return (best_article, best_score)
