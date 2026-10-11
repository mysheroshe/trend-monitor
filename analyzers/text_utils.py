"""Shared text helpers used by scoring, clustering and keyword generation.

Kept in one place so the word-boundary matching rules (which previously
mismatched "ai" inside "email" and "reel" inside "freelancers") are defined
exactly once.
"""

import re


def has_phrase(text, phrases):
    """Return the first matching phrase from ``phrases`` or ``None``.

    Short purely-alphanumeric tokens (e.g. "ai", "crm") are matched on word
    boundaries; phrases containing spaces or punctuation are matched as plain
    substrings. ``text`` must already be lowercased.
    """
    for phrase in phrases:
        if re.match(r"^[a-z0-9]+$", phrase):
            if re.search(r"\b" + re.escape(phrase) + r"\b", text):
                return phrase
        elif phrase in text:
            return phrase
    return None


def normalize_name(name):
    """Lowercase, strip punctuation and collapse whitespace for comparison."""
    text = (name or "").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_url(url):
    """Reduce a URL to a comparable form (scheme/fragment/trailing slash)."""
    text = (url or "").strip().lower()
    if not text:
        return ""
    text = re.sub(r"^https?://", "", text)
    text = text.split("#", 1)[0]
    return text.rstrip("/")


def product_text(product):
    """Return a single lowercased string combining all text fields."""
    tags = product.get("tags", "")
    if isinstance(tags, list):
        tags = " ".join(tags)
    parts = [
        product.get("name", ""),
        product.get("title", ""),
        product.get("description", ""),
        product.get("tagline", ""),
        product.get("category", ""),
        tags,
    ]
    return " ".join(p for p in parts if p).lower()


def tokenize(text):
    """Split text into lowercase alphanumeric tokens."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())
