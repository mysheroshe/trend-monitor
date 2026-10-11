"""Source and discovery quality signals (Phase 5, Steps 4-7).

  * ``hn_content_type``      PRODUCT / DEMAND_SIGNAL / NEWS_DISCUSSION / UNKNOWN
  * ``github_product_likeness`` HIGH / MEDIUM / LOW
  * ``novelty_signal``       HIGH / MEDIUM / LOW / UNKNOWN
  * ``discovery_quality``    HIGH / MEDIUM / LOW  (shortlist ordering + noise filter)
  * ``source_health``        per-collector fetched / accepted / filtered / status

Deterministic only. No new sources, no API calls.
"""

import re

from analyzers.keyword_quality import has_category_anchor, has_function_anchor
from analyzers.text_utils import has_phrase, product_text
from config import scoring_weights as SW

# ---------------------------------------------------------------------------
# Hacker News content typing (Step 4)
# ---------------------------------------------------------------------------

HN_PRODUCT = "PRODUCT"
HN_DEMAND = "DEMAND_SIGNAL"
HN_NEWS = "NEWS_DISCUSSION"
HN_UNKNOWN = "UNKNOWN"

_HN_LAUNCH_SIGNALS = [
    "show hn", "launch hn", "i built", "i made", "i created", "i launched",
    "we built", "we made", "we launched", "announcing", "introducing",
]

_HN_DEMAND_SIGNALS = [
    "ask hn", "tell hn", "how do i", "looking for", "recommend",
    "is there a tool", "any tool for", "wish there was", "why is there no",
    "anyone else", "help me find", "what do you use", "alternative to",
    "best way to",
]

_HN_NEWS_SIGNALS = [
    "drop in", "traffic", "after strike", "outage", "incident", "lawsuit",
    "acquires", "acquisition", "layoffs", "funding", "seeking", "legal help",
    "release", "update", "opinion", "the rise of", "the fall of",
    "history of", "lessons from", "review:", "is dead", "benchmark",
    "report", "study", "datacenter", "datacentre", "migration",
    "vulnerability", "breach", "deprecation",
]

_HN_PRODUCT_HINTS = [
    "tool", "app", "extension", "plugin", "cli", "self-hosted", "open source",
    "open-source", "saas", "api", "dashboard", "editor", "generator", "agent",
    "bot", "platform", "browser",
]

_ARTICLE_URL_MARKERS = ["/blog/", "medium.com", "substack.com", "dev.to", "/20", "/posts/"]


def classify_hn_item(item):
    """Return (hn_content_type, reason) for one Hacker News item."""
    title = (item.get("title") or item.get("name") or "").lower()
    url = (item.get("url") or "").lower()

    if has_phrase(title, _HN_LAUNCH_SIGNALS):
        return HN_PRODUCT, "product launch post (Show HN / Launch HN / 'I built')"
    if has_phrase(title, _HN_DEMAND_SIGNALS):
        return HN_DEMAND, "demand/discussion post (kept as demand evidence only)"
    if has_phrase(title, _HN_NEWS_SIGNALS) or any(marker in url for marker in _ARTICLE_URL_MARKERS):
        return HN_NEWS, "news / opinion / incident post"
    if has_phrase(title, _HN_PRODUCT_HINTS):
        return HN_UNKNOWN, "mentions a product noun but has no launch evidence"
    return HN_UNKNOWN, "no product evidence"


# ---------------------------------------------------------------------------
# GitHub product likeness (Step 5)
# ---------------------------------------------------------------------------

GH_HIGH = "HIGH"
GH_MEDIUM = "MEDIUM"
GH_LOW = "LOW"

_GH_LOW_SIGNALS = [
    "library for", "framework", "sdk", "boilerplate", "starter template",
    "research", "paper", "benchmark", "dataset", "model weights", "checkpoint",
    "inference server", "kubernetes", "infrastructure", "dependency",
    "binding", "wrapper for", "port of", "reverse engineer", "for developers",
    "developer tool", "devtool", "plugin for", "template for",
    "agent framework", "multi-agent", "npm install", "pip install",
]

_GH_HIGH_SIGNALS = [
    "browser extension", "chrome extension", "desktop app", "web app",
    "dashboard", "editor", "converter", "generator", "tracker", "app for",
    "tool for", "self-hosted", "cli tool", "game", "simulator", "player",
    "viewer", "reader", "scanner", "utility",
]


def github_product_likeness(item):
    """Return (HIGH/MEDIUM/LOW, reason) for one GitHub Trending repository."""
    text = product_text(item)
    low = has_phrase(text, _GH_LOW_SIGNALS)
    if low:
        return GH_LOW, f"developer library / tooling signal ('{low}')"
    high = has_phrase(text, _GH_HIGH_SIGNALS)
    if high:
        return GH_HIGH, f"end-user product signal ('{high}')"
    return GH_MEDIUM, "no strong library or product signal"


# ---------------------------------------------------------------------------
# Novelty (Step 6)
# ---------------------------------------------------------------------------

NOVELTY_HIGH = "HIGH"
NOVELTY_MEDIUM = "MEDIUM"
NOVELTY_LOW = "LOW"
NOVELTY_UNKNOWN = "UNKNOWN"

_MATURE_VISITS = 1_000_000
_MATURE_USERS = 1_000_000
_ESTABLISHED_USERS = 100_000


def _parse_number(text):
    """Parse '3,000,000', '290.3M', '1054.54%' into a float."""
    if text is None:
        return None
    match = re.search(r"([\d.,]+)\s*([kmb])?", str(text).lower().replace(",", ""))
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    multiplier = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}.get(match.group(2) or "")
    return value * multiplier if multiplier else value


def novelty_signal(item, source=None):
    """Return (HIGH/MEDIUM/LOW/UNKNOWN, reason): how *new* is this product?"""
    source = source or item.get("_source", "")

    if source == "toolify":
        category = (item.get("category") or "").lower()
        visits = _parse_number(item.get("monthly_visit"))
        growth = _parse_number(item.get("growth_rate"))
        if "just launched" in category or "new" in category or visits is None:
            return NOVELTY_HIGH, "listed on the Toolify 'new' page"
        if visits >= _MATURE_VISITS and (growth is None or growth < 20):
            return NOVELTY_LOW, (
                f"mature tool ({item.get('monthly_visit')} monthly visits) "
                "without a growth signal"
            )
        return NOVELTY_MEDIUM, "trending list with traffic data"

    if source == "ai_tools":
        return NOVELTY_HIGH, "new-tools directory listing"

    if source == "product_hunt":
        return NOVELTY_MEDIUM, "product launch feed"

    if source == "hackernews":
        kind, _ = classify_hn_item(item)
        if kind == HN_PRODUCT:
            return NOVELTY_HIGH, "Show HN / Launch HN post"
        return NOVELTY_UNKNOWN, "not a product post"

    if source == "chrome_extensions":
        users = _parse_number(item.get("users"))
        if users is None:
            return NOVELTY_UNKNOWN, "no install data"
        if users >= _MATURE_USERS:
            return NOVELTY_LOW, f"mature extension ({item.get('users')})"
        if users >= _ESTABLISHED_USERS:
            return NOVELTY_MEDIUM, f"established extension ({item.get('users')})"
        return NOVELTY_HIGH, f"small/new extension ({item.get('users')})"

    if source == "github":
        return NOVELTY_MEDIUM, "trending repository"

    return NOVELTY_UNKNOWN, "no novelty signal"


# ---------------------------------------------------------------------------
# Discovery quality (Step 7)
# ---------------------------------------------------------------------------

DQ_HIGH = "HIGH"
DQ_MEDIUM = "MEDIUM"
DQ_LOW = "LOW"


def discovery_quality(item, source=None):
    """Is this item useful as an *opportunity-discovery* input?

    Deliberately separate from the Solo Builder Score, the SEO score and the
    Opportunity Score; used only for shortlist ordering and for dropping noise.
    """
    source = source or item.get("_source", "")
    text = product_text(item)
    anchored = has_category_anchor(text) or has_function_anchor(text)

    if source == "hackernews":
        kind, why = classify_hn_item(item)
        if kind != HN_PRODUCT:
            return DQ_LOW, f"HN {kind}: {why}"
        return DQ_HIGH, f"HN {kind}: {why}"

    if source == "github":
        level, why = github_product_likeness(item)
        if level == GH_LOW:
            return DQ_LOW, f"GitHub {level}: {why}"
        novelty, _ = novelty_signal(item, source)
        if level == GH_HIGH and novelty in (NOVELTY_HIGH, NOVELTY_MEDIUM):
            return DQ_HIGH, f"GitHub {level}: {why}"
        return DQ_MEDIUM, f"GitHub {level}: {why}"

    novelty, novelty_why = novelty_signal(item, source)
    confidence = SW.SOURCE_CONFIDENCE.get(source, SW.DEFAULT_SOURCE_CONFIDENCE)

    if novelty == NOVELTY_HIGH and confidence >= 0.6:
        return DQ_HIGH, f"emerging product ({novelty_why})"
    if novelty == NOVELTY_MEDIUM and confidence >= 0.8 and anchored:
        return DQ_HIGH, "fresh launch with a clear tool category"
    if confidence >= 0.6:
        return DQ_MEDIUM, f"product-like but {novelty_why or 'no novelty signal'}"
    return DQ_LOW, f"low-confidence source with {novelty_why or 'no novelty signal'}"


# ---------------------------------------------------------------------------
# Source health (Step 10)
# ---------------------------------------------------------------------------

SOURCE_LABELS = {
    "product_hunt": "Product Hunt",
    "toolify": "Toolify",
    "ai_tools": "TAAFT",
    "chrome_extensions": "Chrome Web Store",
    "github": "GitHub Trending",
    "hackernews": "Hacker News",
}


def source_health(groups, suitable, filtered, errors=None):
    """Per-collector fetched / accepted / filtered counts plus a status note."""
    errors = errors or {}
    rows = []
    for source, label in SOURCE_LABELS.items():
        fetched = len(groups.get(source) or [])
        accepted = [item for item in suitable if item.get("_source") == source]
        dropped = [item for item in filtered if item.get("_source") == source]

        note = ""
        if source == "hackernews":
            counts = {}
            for item in accepted + dropped:
                kind = item.get("hn_content_type") or HN_UNKNOWN
                counts[kind] = counts.get(kind, 0) + 1
            note = ", ".join(f"{count} {kind.lower().replace('_', ' ')}"
                             for kind, count in sorted(counts.items()))
        elif source == "github":
            counts = {}
            for item in accepted:
                level = item.get("github_product_likeness") or GH_MEDIUM
                counts[level] = counts.get(level, 0) + 1
            if dropped:
                counts["LOW"] = counts.get("LOW", 0) + len(dropped)
            note = ", ".join(f"{count} {level.lower()}" for level, count in sorted(counts.items()))

        error = errors.get(source) or ""
        status = "error" if error else ("empty" if fetched == 0 else "ok")
        rows.append({
            "source": source,
            "label": label,
            "fetched": fetched,
            "accepted": len(accepted),
            "filtered": len(dropped),
            "status": status,
            "note": note,
            "error": error,
        })
    return rows
