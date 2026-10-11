"""Reddit demand/pain analysis (Phase 7).

Deterministic only: classification, payment-confidence, engagement, recurrence,
demand score and keyword seeds. Reddit never sets a verdict and never creates a
PRODUCT_SIGNAL unless the post is explicitly a product launch.
"""

import re

from analyzers import signals as S
from analyzers.clustering import classify
from analyzers.text_utils import normalize_name, tokenize

# ---------------------------------------------------------------------------
# Configuration (Step 1/3)
# ---------------------------------------------------------------------------

SUBREDDIT_GROUPS = {
    "startup_saas": ["SaaS", "startups", "Entrepreneur", "indiehackers", "AppIdeas", "SideProject"],
    "small_business": ["smallbusiness"],
    "productivity": ["productivity", "Notion", "excel", "googlesheets"],
    "data": ["dataanalysis", "analytics", "datascience"],
    "developers": ["webdev", "programming", "selfhosted"],
    "marketing": ["marketing", "socialmedia", "youtubers", "podcasting"],
    "ecommerce": ["ecommerce", "EtsySellers", "shopify"],
}

DEFAULT_SUBREDDITS = [name for group in SUBREDDIT_GROUPS.values() for name in group]

# ---------------------------------------------------------------------------
# Patterns (Step 5)
# ---------------------------------------------------------------------------

REDDIT_PATTERNS = [
    ("i wish there was", S.PAIN_SIGNAL), ("i wish someone made", S.PAIN_SIGNAL),
    ("is there a tool", S.DEMAND_SIGNAL), ("is there an app", S.DEMAND_SIGNAL),
    ("is there a better way", S.DEMAND_SIGNAL), ("looking for software", S.DEMAND_SIGNAL),
    ("looking for a tool", S.DEMAND_SIGNAL), ("does anyone know", S.DEMAND_SIGNAL),
    ("alternative to", S.COMPETITION_SIGNAL), ("any alternative", S.COMPETITION_SIGNAL),
    ("too expensive", S.PAIN_SIGNAL), ("missing feature", S.FEATURE_GAP_SIGNAL),
    ("why doesn't", S.FEATURE_GAP_SIGNAL), ("i hate that", S.PAIN_SIGNAL),
    ("manual process", S.PAIN_SIGNAL), ("do this manually", S.PAIN_SIGNAL),
    ("manually", S.PAIN_SIGNAL),
    ("do this in excel", S.PAIN_SIGNAL), ("use a spreadsheet for", S.PAIN_SIGNAL),
    ("built my own workaround", S.PAIN_SIGNAL), ("how do you automate", S.DEMAND_SIGNAL),
    ("anyone else struggle", S.PAIN_SIGNAL), ("what tool do you use for", S.DEMAND_SIGNAL),
    ("how do you handle", S.DEMAND_SIGNAL), ("needs bulk export", S.FEATURE_GAP_SIGNAL),
    ("no api", S.FEATURE_GAP_SIGNAL), ("cannot export", S.FEATURE_GAP_SIGNAL),
    ("can't export", S.FEATURE_GAP_SIGNAL), ("willingness to pay", S.PAYMENT_SIGNAL),
]

# Posts that are not opportunity evidence (Step 9).
REJECT_PATTERNS = [
    "meme", "memes", "motivation", "motivational", "what business should i start",
    "ai is the future", "career advice", "resume review", "salary", "interview",
    "politics", "political", "rant about my boss", "hiring", "job posting",
    "beginner question about python", "homework",
]

SELF_PROMO_PATTERNS = ["i built my own", "check out my", "my new tool", "launching my",
                       "i made a tool", "shameless plug", "my side project is"]

PRODUCT_LAUNCH_PATTERNS = ["i launched", "we launched", "just launched my",
                           "show and tell", "i'm launching"]

# ---------------------------------------------------------------------------
# Payment confidence (Step 6)
# ---------------------------------------------------------------------------

PAYMENT_ACTUAL = "ACTUAL_SPEND"
PAYMENT_STATED = "STATED_WILLINGNESS"
PAYMENT_UNKNOWN = "UNKNOWN"

_ACTUAL_SPEND = [r"\bi pay\b", r"\bwe pay\b", r"\bi paid\b", r"\bwe paid\b",
                 r"\bi hired\b", r"\bi spend\b", r"\bwe spend\b",
                 r"\bsubscription costs?\b", r"\bper month\b", r"\ba month\b", r"/mo\b"]
_STATED_WILLINGNESS = ["would pay", "willing to pay", "i'd pay", "take my money",
                       "shut up and take my money", "happy to pay"]


def payment_confidence(text):
    """ACTUAL_SPEND requires real spending language (and a figure where present)."""
    lowered = (text or "").lower()
    has_money = bool(re.search(r"\$\s?[\d.,]+", lowered))
    if has_money and any(re.search(pattern, lowered) for pattern in _ACTUAL_SPEND):
        return PAYMENT_ACTUAL
    if any(marker in lowered for marker in _STATED_WILLINGNESS):
        return PAYMENT_STATED
    if has_money and any(re.search(pattern, lowered) for pattern in _ACTUAL_SPEND):
        return PAYMENT_ACTUAL
    return PAYMENT_UNKNOWN


# ---------------------------------------------------------------------------
# Classification, gating, engagement
# ---------------------------------------------------------------------------

def post_text(post):
    return f"{post.get('title') or ''} {post.get('selftext') or ''}".strip()


def plural_normalized(text):
    """Add simple singular variants so 'checks'/'spreadsheets' still match.

    Reddit users write plurals constantly ("checks formulas in spreadsheets");
    the shared word-boundary matcher is intentionally strict, so the Reddit
    layer normalizes locally instead of loosening the global matcher.
    """
    tokens = tokenize(text or "")
    variants = [t[:-1] if len(t) > 4 and t.endswith("s") else t for t in tokens]
    return f"{text or ''} {' '.join(variants)}"


def quality_gate(post):
    """Return (ok, reason). Rejects memes, news, career talk, pure self-promo."""
    text = post_text(post).lower()
    title = (post.get("title") or "").lower()
    if not title:
        return False, "no title"
    for pattern in REJECT_PATTERNS:
        if pattern in text:
            return False, f"off-topic pattern '{pattern}'"
    types, _ = classify_post(post)
    is_self_promo = any(pattern in text for pattern in SELF_PROMO_PATTERNS)
    if is_self_promo and not any(t in (S.PAIN_SIGNAL, S.DEMAND_SIGNAL, S.FEATURE_GAP_SIGNAL)
                                 for t in types):
        return False, "self-promotion without demand/pain evidence"
    if not types and len(tokenize(text)) < 6:
        return False, "no demand/pain pattern"
    return True, ""


def classify_post(post):
    """Return (signal_types, matched_phrases) for a Reddit post."""
    text = plural_normalized(post_text(post)).lower()
    types, matched = [], []
    for phrase, signal_type in REDDIT_PATTERNS:
        if phrase in text:
            matched.append(phrase)
            if signal_type not in types:
                types.append(signal_type)
    generic_types, generic_matched = S.detect_pain_patterns(text)
    for signal_type in generic_types:
        if signal_type not in types:
            types.append(signal_type)
    matched.extend(generic_matched)

    if any(pattern in text for pattern in PRODUCT_LAUNCH_PATTERNS):
        types.append(S.PRODUCT_SIGNAL)
    return types, sorted(set(matched))


def engagement_strength(score, comments):
    score = score or 0
    comments = comments or 0
    if score >= 200 or comments >= 100:
        return "HIGH"
    if score >= 40 or comments >= 20:
        return "MEDIUM"
    return "LOW"


def reddit_post_id(post):
    return str(post.get("id") or post.get("name") or "").strip()


def canonical_permalink(post):
    return S.canonical_url(post.get("permalink") or
                           f"https://www.reddit.com/r/{post.get('subreddit','')}/comments/{reddit_post_id(post)}")


# ---------------------------------------------------------------------------
# Signal construction (Steps 6-8, 19)
# ---------------------------------------------------------------------------

def to_signals(post, comments=()):
    """Convert one accepted Reddit post (+ top comments) into signals."""
    types, matched = classify_post(post)
    if not types:
        types = [S.PAIN_SIGNAL]
    payment = payment_confidence(post_text(post))
    if payment != PAYMENT_UNKNOWN and S.PAYMENT_SIGNAL not in types:
        types.append(S.PAYMENT_SIGNAL)

    supporting = [c for c in comments
                  if any(phrase in (c.get("body") or "").lower()
                         for phrase, _ in REDDIT_PATTERNS)]
    confirmed = len({c.get("author") for c in supporting if c.get("author")}) >= 2

    title = post.get("title") or ""
    summary = (post.get("selftext") or "").strip()[:240]
    url = post.get("permalink") or ""
    if url.startswith("/"):
        url = "https://www.reddit.com" + url

    signals = []
    for signal_type in types:
        signals.append(S.make_signal(
            "reddit", signal_type,
            title=title, description=summary, source_url=url,
            pain_point=summary[:200] or title,
            evidence_strength="MEDIUM" if confirmed else "LOW",
            raw_metadata={
                "matched_phrases": matched,
                "payment_signal_confidence": payment if signal_type == S.PAYMENT_SIGNAL else None,
                "supporting_comment_count": len(supporting),
                "confirmed_by_multiple_users": confirmed,
                "top_comments": [(c.get("body") or "")[:160] for c in supporting[:3]],
            },
            subreddit=post.get("subreddit"),
            engagement=post.get("score"),
            engagement_metric=post.get("num_comments"),
            requested_feature=summary[:120] or None,
        ))
    return signals


def enrich_metadata(signal, post):
    """Attach the Reddit-specific fields required for reporting/health."""
    signal["subreddit"] = post.get("subreddit")
    signal["score"] = post.get("score")
    signal["comment_count"] = post.get("num_comments")
    signal["created_utc"] = post.get("created_utc")
    signal["post_age_hours"] = post.get("post_age_hours")
    signal["engagement_strength"] = engagement_strength(post.get("score"), post.get("num_comments"))
    return signal


def dedup_signals(signal_list):
    """Dedup by post id, canonical permalink, then normalized title+subreddit."""
    seen_ids, seen_urls, seen_titles, result = set(), set(), set(), []
    for signal in signal_list or []:
        meta = signal.get("raw_metadata") or {}
        post_id = str(meta.get("post_id") or "")
        url = signal.get("canonical_url") or ""
        title_key = (normalize_name(signal.get("title") or ""), signal.get("subreddit"))
        if post_id and post_id in seen_ids:
            continue
        if url and url in seen_urls:
            continue
        if title_key[0] and title_key in seen_titles:
            continue
        seen_ids.add(post_id) if post_id else None
        seen_urls.add(url) if url else None
        seen_titles.add(title_key) if title_key[0] else None
        result.append(signal)
    return result


# ---------------------------------------------------------------------------
# Recurrence + demand score (Steps 13, 14)
# ---------------------------------------------------------------------------

def theme_key(signal):
    """Deterministic theme key: domain+function if classifiable, else subject."""
    text = plural_normalized(f"{signal.get('title') or ''} {signal.get('pain_point') or ''}")
    info = classify({"name": text, "description": text})
    if info["domain"] and info["function"]:
        return f"{info['domain']}:{info['function']}"
    tokens = [t for t in tokenize(signal.get("title") or "")
              if t not in ("the", "a", "an", "for", "with", "how", "to", "is", "best")]
    return "subject:" + " ".join(tokens[:3]) if tokens else "unknown"


def recurring_pain(signal_list):
    """Group signals by theme and compute persistence metrics."""
    themes = {}
    for signal in signal_list or []:
        key = theme_key(signal)
        theme = themes.setdefault(key, {
            "theme": key, "signals": [], "post_count": 0,
            "independent_post_count": 0, "subreddits": [], "days": [],
            "engagement_total": 0, "has_actual_spend": False,
        })
        theme["signals"].append(signal)
        url = signal.get("canonical_url")
        if url and url not in theme.setdefault("_urls", []):
            theme["_urls"].append(url)
            theme["independent_post_count"] += 1
        theme["post_count"] += 1
        subreddit = signal.get("subreddit")
        if subreddit and subreddit not in theme["subreddits"]:
            theme["subreddits"].append(subreddit)
        day = (signal.get("detected_at") or "")[:10]
        if day and day not in theme["days"]:
            theme["days"].append(day)
        theme["engagement_total"] += int(signal.get("score") or 0)
        confidence = (signal.get("raw_metadata") or {}).get("payment_signal_confidence")
        if confidence == PAYMENT_ACTUAL:
            theme["has_actual_spend"] = True

    for theme in themes.values():
        posts = theme["independent_post_count"]
        if posts >= 4 and len(theme["subreddits"]) >= 2:
            theme["pain_persistence"] = "PERSISTENT"
        elif posts >= 2:
            theme["pain_persistence"] = "REPEATED"
        else:
            theme["pain_persistence"] = "ONE_OFF"
        score, level = reddit_demand_score(theme)
        theme["reddit_demand_score"] = score
        theme["reddit_demand_level"] = level
        theme.pop("_urls", None)
    return sorted(themes.values(), key=lambda t: (-t["reddit_demand_score"], t["theme"]))


def reddit_demand_score(theme):
    """Informational 0-100 score. One viral post can never be HIGH."""
    posts = theme.get("independent_post_count", 0)
    subreddits = len(theme.get("subreddits") or [])
    engagement = theme.get("engagement_total", 0)
    specificity = 15 if theme.get("specificity") else 8

    recurrence = min(posts / 6, 1.0) * 30
    independence = min(posts / 5, 1.0) * 20
    diversity = min(subreddits / 3, 1.0) * 15
    engagement_points = min(engagement / 500, 1.0) * 10
    payment = 10 if theme.get("has_actual_spend") else 0

    score = int(round(recurrence + independence + diversity + specificity
                      + engagement_points + payment))
    score = max(0, min(100, score))

    if posts < 2:
        level = "LOW"                      # a single post is never HIGH/MEDIUM
    elif score >= 60:
        level = "HIGH"
    elif score >= 35:
        level = "MEDIUM"
    else:
        level = "LOW"
    return score, level


# ---------------------------------------------------------------------------
# Keyword seeds (Step 15) + unmatched pain (Step 12)
# ---------------------------------------------------------------------------

def keyword_seeds(text):
    """Deterministic keyword seeds from pain language (origin REDDIT_PAIN)."""
    normalized = plural_normalized(text)
    info = classify({"name": normalized, "description": normalized})
    domain, function = info.get("domain"), info.get("function")
    if not domain or not function:
        return []
    from analyzers.clustering import DOMAIN_FAMILIES, FUNCTION_FAMILIES
    from analyzers.keyword_quality import MATURITY_AWKWARD, MATURITY_BRAND, keyword_maturity

    domain_label = next((d["label"].lower() for d in DOMAIN_FAMILIES if d["key"] == domain), "")
    heads = next((f["head_words"] for f in FUNCTION_FAMILIES if f["key"] == function), [])
    candidates = []
    if domain_label and heads:
        candidates.append(f"{domain_label} {heads[0]}")
    subjects = [t for t in tokenize(normalized)
                if t not in ("i", "need", "something", "that", "for", "the", "a", "an", "my",
                             "is", "there", "any", "how", "do", "you", "what", "tool", "tool")]
    if heads and subjects:
        candidate = f"{' '.join(subjects[:2])} {heads[0]}"
        if 2 <= len(candidate.split()) <= 4:
            candidates.append(candidate)

    # seeds must pass the existing quality rules (§15) - no bypassing filters
    return [seed for seed in candidates
            if keyword_maturity(seed) not in (MATURITY_AWKWARD, MATURITY_BRAND)]


def unmatched_pain(themes, matched_theme_keys):
    """Themes with no matching opportunity — kept as stored demand evidence."""
    return [theme for theme in themes if theme["theme"] not in set(matched_theme_keys)]


def match_themes_to_clusters(themes, clusters):
    """Map themes to clusters by domain+function key (no loosening of rules)."""
    by_key = {}
    for cluster in clusters or []:
        if cluster.get("domain") and cluster.get("function"):
            by_key[f"{cluster['domain']}:{cluster['function']}"] = cluster
    matched = {}
    for theme in themes:
        cluster = by_key.get(theme["theme"])
        if cluster is not None:
            matched[theme["theme"]] = cluster
    return matched
