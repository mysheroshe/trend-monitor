"""Deterministic opportunity clustering (Phase 2).

Groups related products into stable, search-intent-relevant opportunity
clusters. No LLM calls, embeddings, vector databases or paid APIs.

Clustering is intentionally conservative: a product only joins a cluster when
it shares an explicit functional term (generator/converter/finder/...) and/or a
specific domain term (tattoo/pdf/audio/...). Products that cannot be
confidently grouped stay in their own singleton cluster.
"""

import hashlib
import json
from pathlib import Path

from analyzers.text_utils import has_phrase, normalize_name, normalize_url, product_text
from config import cluster_weights as CW
from config import scoring_weights as SW
from config import timeutil


# ---------------------------------------------------------------------------
# Functional head terms — the "what does it do" half of a cluster key
# ---------------------------------------------------------------------------

FUNCTION_FAMILIES = [
    {
        "key": "conversion",
        "label": "Converter",
        "head_words": ["converter", "convert"],
        "keywords": ["converter", "convert", "conversion", "transcode", "transcoder"],
        "problem": "how to convert {domain}",
    },
    {
        "key": "removal",
        "label": "Remover",
        "head_words": ["remover", "eraser", "cleaner"],
        "keywords": ["remover", "remove", "eraser", "erase", "cleaner", "cleanup", "stripper", "strip"],
        "problem": "how to remove {domain}",
    },
    {
        "key": "enhancement",
        "label": "Enhancer",
        "head_words": ["enhancer", "upscaler", "improver"],
        "keywords": ["enhancer", "enhance", "upscaler", "upscale", "improver", "improve", "booster", "boost", "sharpen"],
        "problem": "how to enhance {domain}",
    },
    {
        "key": "extraction",
        "label": "Extractor",
        "head_words": ["extractor", "parser", "scraper"],
        "keywords": ["extractor", "extract", "parser", "parse", "scraper", "scrape", "reader"],
        "problem": "how to extract data from {domain}",
    },
    {
        "key": "summarization",
        "label": "Summarizer",
        "head_words": ["summarizer", "summary"],
        "keywords": ["summarizer", "summarize", "summarise", "summary", "tldr"],
        "problem": "how to summarize {domain}",
    },
    {
        "key": "translation",
        "label": "Translator",
        "head_words": ["translator", "translation"],
        "keywords": ["translator", "translate", "translation"],
        "problem": "how to translate {domain}",
    },
    {
        "key": "formatting",
        "label": "Formatter",
        "head_words": ["formatter", "beautifier", "minifier"],
        "keywords": ["formatter", "format", "beautifier", "beautify", "minifier", "minify", "prettifier", "pretty print"],
        "problem": "how to format {domain}",
    },
    {
        "key": "changing",
        "label": "Changer",
        "head_words": ["changer", "shifter", "modifier"],
        "keywords": ["changer", "change", "shifter", "shift", "modifier", "modify", "replacer", "replace"],
        "problem": "how to change {domain}",
    },
    {
        "key": "comparison",
        "label": "Comparison",
        "head_words": ["comparison", "comparator"],
        "keywords": ["comparison", "compare", "diff", "versus"],
        "problem": "how to compare {domain}",
    },
    {
        "key": "checking",
        "label": "Checker",
        "head_words": ["checker", "validator", "detector", "scanner"],
        "keywords": ["checker", "check", "validator", "validate", "verifier", "verify", "detector",
                     "detect", "scanner", "scan", "tester", "grader", "audit"],
        "problem": "how to check {domain}",
    },
    {
        "key": "analysis",
        "label": "Analyzer",
        "head_words": ["analyzer", "analysis"],
        "keywords": ["analyzer", "analyser", "analyze", "analyse", "analysis", "insights", "scorer", "reviewer"],
        "problem": "how to analyze {domain}",
    },
    {
        "key": "finding",
        "label": "Finder",
        "head_words": ["finder", "locator", "search"],
        "keywords": ["finder", "find", "locator", "locate", "lookup", "search", "explorer"],
        "problem": "how to find {domain}",
    },
    {
        "key": "tracking",
        "label": "Tracker",
        "head_words": ["tracker", "monitor", "logger"],
        "keywords": ["tracker", "track", "monitor", "monitoring", "logger", "journal", "diary"],
        "problem": "how to track {domain}",
    },
    {
        "key": "planning",
        "label": "Planner",
        "head_words": ["planner", "scheduler", "organizer"],
        "keywords": ["planner", "plan", "scheduler", "schedule", "organizer", "organize"],
        "problem": "how to plan {domain}",
    },
    {
        "key": "editing",
        "label": "Editor",
        "head_words": ["editor", "trimmer", "cropper"],
        "keywords": ["editor", "edit", "trimmer", "trim", "cropper", "crop", "annotator", "annotate"],
        "problem": "how to edit {domain}",
    },
    {
        "key": "generation",
        "label": "Generator",
        "head_words": ["generator", "maker", "creator"],
        "keywords": ["generator", "generate", "maker", "creator", "create", "designer", "design",
                     "builder", "builder", "build", "render", "draw", "sketch"],
        "problem": "how to make a {domain}",
    },
    {
        "key": "writing",
        "label": "Writer",
        "head_words": ["writer", "rewriter", "paraphraser"],
        "keywords": ["writer", "writing", "copywriter", "rewriter", "rewrite", "paraphraser", "paraphrase"],
        "problem": "how to write {domain}",
    },
    {
        "key": "calculation",
        "label": "Calculator",
        "head_words": ["calculator", "estimator"],
        "keywords": ["calculator", "calculate", "estimator", "estimate", "compute"],
        "problem": "how to calculate {domain}",
    },
    {
        "key": "directory",
        "label": "Directory",
        "head_words": ["directory", "catalog", "index"],
        "keywords": ["directory", "listing", "catalog", "index of"],
        "problem": "",
    },
]

# Domains whose products are essentially always "create an X" tools, so a
# domain-only product joins the generation cluster instead of a vague bucket.
DEFAULT_GENERATION_DOMAINS = {
    "tattoo", "logo", "avatar", "meme", "wallpaper", "thumbnail", "sticker",
    "icon", "qr", "barcode", "password", "prompt", "font",
}

# Domains that are too generic to form a useful bucket on their own: without a
# functional term these products stay as separate clusters.
GENERIC_DOMAIN_ONLY_DOMAINS = {"text", "data", "code", "website"}


# ---------------------------------------------------------------------------
# Domain terms — the "what is it about" half of a cluster key
# ---------------------------------------------------------------------------

DOMAIN_FAMILIES = [
    {"key": "tattoo", "label": "Tattoo", "keywords": ["tattoo", "tattoos", "sleeve tattoo"]},
    {"key": "logo", "label": "Logo", "keywords": ["logo", "logos", "brand mark"]},
    {"key": "avatar", "label": "Avatar", "keywords": ["avatar", "profile picture", "pfp"]},
    {"key": "meme", "label": "Meme", "keywords": ["meme", "memes"]},
    {"key": "wallpaper", "label": "Wallpaper", "keywords": ["wallpaper", "background image"]},
    {"key": "thumbnail", "label": "Thumbnail", "keywords": ["thumbnail", "cover image"]},
    {"key": "sticker", "label": "Sticker", "keywords": ["sticker", "stickers"]},
    {"key": "icon", "label": "Icon", "keywords": ["icon", "icons", "favicon"]},
    {"key": "qr", "label": "QR Code", "keywords": ["qr code", "qrcode", "qr"]},
    {"key": "barcode", "label": "Barcode", "keywords": ["barcode"]},
    {"key": "password", "label": "Password", "keywords": ["password", "passphrase"]},
    {"key": "prompt", "label": "Prompt", "keywords": ["prompt", "prompts"]},
    {"key": "resume", "label": "Resume", "keywords": ["resume", "cv", "cover letter"]},
    {"key": "pdf", "label": "PDF", "keywords": ["pdf", "document", "docx", "ebook", "epub"]},
    {"key": "spreadsheet", "label": "Spreadsheet", "keywords": ["spreadsheet", "excel", "csv", "xlsx", "google sheet"]},
    {"key": "data", "label": "Data", "keywords": ["json", "xml", "yaml", "sql", "dataset", "database", "regex"]},
    {"key": "seo", "label": "SEO", "keywords": ["seo", "backlink", "serp", "keyword research", "meta description", "sitemap"]},
    {"key": "email", "label": "Email", "keywords": ["email", "newsletter", "inbox", "gmail", "outlook"]},
    {"key": "audio", "label": "Audio", "keywords": ["audio", "music", "song", "bpm", "tempo", "pitch", "vocal",
                                                    "mp3", "wav", "midi", "chord", "lyrics", "podcast", "sound", "beat"]},
    {"key": "video", "label": "Video", "keywords": ["video", "movie", "reel", "clip", "youtube", "subtitle",
                                                    "caption", "transcript"]},
    {"key": "image", "label": "Image", "keywords": ["image", "photo", "picture", "selfie", "portrait",
                                                    "illustration", "artwork", "gif", "art"]},
    {"key": "code", "label": "Code", "keywords": ["code", "coding", "programming", "developer", "github",
                                                  "repository", "unit test", "api client"]},
    {"key": "website", "label": "Website", "keywords": ["website", "landing page", "html", "css", "web page"]},
    {"key": "mockup", "label": "Mockup", "keywords": ["mockup", "wireframe", "prototype", "ui design", "ui kit"]},
    {"key": "presentation", "label": "Presentation", "keywords": ["slide", "slides", "presentation", "powerpoint", "deck"]},
    {"key": "finance", "label": "Finance", "keywords": ["finance", "budget", "expense", "invoice", "tax",
                                                        "payroll", "accounting", "investment", "stock"]},
    {"key": "currency", "label": "Currency", "keywords": ["currency", "exchange rate", "forex"]},
    {"key": "unit", "label": "Unit", "keywords": ["unit", "measurement", "temperature", "imperial", "metric conversion"]},
    {"key": "time", "label": "Time", "keywords": ["timezone", "clock", "timer", "countdown", "stopwatch"]},
    {"key": "calendar", "label": "Calendar", "keywords": ["calendar", "meeting", "appointment", "scheduling link"]},
    {"key": "travel", "label": "Travel", "keywords": ["travel", "flight", "hotel", "itinerary", "trip"]},
    {"key": "food", "label": "Food", "keywords": ["recipe", "food", "meal", "cooking", "ingredient"]},
    {"key": "health", "label": "Health", "keywords": ["health", "fitness", "workout", "nutrition", "calorie",
                                                      "diet", "sleep", "meditation"]},
    {"key": "education", "label": "Education", "keywords": ["study", "homework", "flashcard", "quiz", "exam",
                                                            "language learning"]},
    {"key": "social", "label": "Social", "keywords": ["instagram", "tiktok", "twitter", "linkedin",
                                                      "social media", "hashtag"]},
    {"key": "ecommerce", "label": "E-commerce", "keywords": ["shopify", "ecommerce", "e-commerce",
                                                             "product listing", "amazon seller", "dropship"]},
    {"key": "legal", "label": "Legal", "keywords": ["legal", "contract", "nda", "terms of service", "privacy policy"]},
    {"key": "color", "label": "Color", "keywords": ["color", "colour", "palette", "hex code", "gradient"]},
    {"key": "font", "label": "Font", "keywords": ["font", "typeface", "typography"]},
    {"key": "text", "label": "Text", "keywords": ["text", "article", "blog post", "essay", "paragraph", "copywriting"]},
]

# Short audience roles used for AUDIENCE_SPECIFIC candidates (optional signal).
DOMAIN_AUDIENCES = {
    "tattoo": "artists",
    "resume": "job seekers",
    "seo": "marketers",
    "email": "marketers",
    "finance": "freelancers",
    "education": "students",
    "social": "creators",
    "audio": "musicians",
    "video": "creators",
    "presentation": "presenters",
}

# Tokens that never carry meaning when deriving a keyword subject.
SUBJECT_STOPWORDS = {
    "ai", "a", "an", "the", "free", "online", "best", "top", "tool", "tools",
    "app", "apps", "web", "site", "website", "platform", "for", "and", "or",
    "with", "your", "my", "new", "pro", "plus", "easy", "simple", "fast",
    "quick", "instant", "smart", "auto", "automatic", "studio", "hq", "io",
    "dev", "labs", "lab", "beta", "make", "made", "using", "use", "it", "is",
    "of", "to", "in", "on", "that", "this", "get", "now",
}

_AI_TERMS = ["ai", "gpt", "llm", "openai", "claude", "anthropic", "gemini", "machine learning"]


def _family_index():
    return {family["key"]: family for family in FUNCTION_FAMILIES}


def _domain_index():
    return {domain["key"]: domain for domain in DOMAIN_FAMILIES}


def _find_match(text, entries):
    """Return (entry, matched_term) for the first entry whose keywords match."""
    for entry in entries:
        matched = has_phrase(text, entry["keywords"])
        if matched:
            return entry, matched
    return None, None


def detect_function(product):
    """Return (family_key, matched_term) or (None, None)."""
    name = (product.get("name") or product.get("title") or "").lower()
    entry, matched = _find_match(name, FUNCTION_FAMILIES)
    if entry:
        return entry["key"], matched
    entry, matched = _find_match(product_text(product), FUNCTION_FAMILIES)
    if entry:
        return entry["key"], matched
    return None, None


def detect_domain(product):
    """Return (domain_key, matched_term) or (None, None)."""
    name = (product.get("name") or product.get("title") or "").lower()
    entry, matched = _find_match(name, DOMAIN_FAMILIES)
    if entry:
        return entry["key"], matched
    entry, matched = _find_match(product_text(product), DOMAIN_FAMILIES)
    if entry:
        return entry["key"], matched
    return None, None


def cluster_id_for(cluster_key):
    """Deterministic, stable slug for a cluster key (never a product name)."""
    slug = cluster_key.replace(":", "-")
    slug = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in slug.lower())
    slug = "-".join(part for part in slug.split("-") if part)
    if not slug:
        slug = "misc-" + hashlib.sha1(cluster_key.encode("utf-8")).hexdigest()[:10]
    return slug


def classify(product):
    """Assign a product to a cluster and return the descriptive fields."""
    function_key, function_term = detect_function(product)
    domain_key, domain_term = detect_domain(product)
    effective_function = function_key

    if domain_key and function_key:
        key = f"{domain_key}:{function_key}"
        label = f"{_domain_index()[domain_key]['label']} {_family_index()[function_key]['label']} Tools"
        reason = f"domain '{domain_term}' + function '{function_term}'"
        theme = _domain_index()[domain_key]["label"]
    elif domain_key and domain_key in DEFAULT_GENERATION_DOMAINS:
        key = f"{domain_key}:generation"
        label = f"{_domain_index()[domain_key]['label']} Generator Tools"
        reason = f"domain '{domain_term}' (creation-style domain: default function 'generation')"
        theme = _domain_index()[domain_key]["label"]
        # The implicit function is real: it drives keyword generation too.
        effective_function = "generation"
    elif domain_key and domain_key not in GENERIC_DOMAIN_ONLY_DOMAINS:
        # A specific domain is a safe, search-relevant grouping on its own.
        key = f"{domain_key}:general"
        label = f"{_domain_index()[domain_key]['label']} Tools"
        reason = f"domain '{domain_term}' (no specific functional term)"
        theme = _domain_index()[domain_key]["label"]
    else:
        # Conservative fallback: without BOTH a domain and a functional term we
        # cannot confidently assert two products share search intent, so each
        # product becomes its own cluster (keyed by a hash, never by its name).
        name = product.get("name") or product.get("title") or ""
        digest = hashlib.sha1(normalize_name(name).encode("utf-8")).hexdigest()[:10]
        part_domain = domain_key or "general"
        part_function = function_key or "general"
        key = f"single:{part_domain}:{part_function}:{digest}"
        short_name = (name or "Unnamed")[:40]
        if domain_key:
            theme = _domain_index()[domain_key]["label"]
            label = f'{theme} Tools - "{short_name}"'
            reason = (f"domain '{domain_term}' only - no functional term, "
                      "so it is kept as its own cluster")
        elif function_key:
            theme = "General"
            label = f'{_family_index()[function_key]["label"]} Tools - "{short_name}"'
            reason = (f"function '{function_term}' only - no domain term, "
                      "so it is kept as its own cluster")
        else:
            theme = "Unclustered"
            label = f'"{short_name}" (unclustered)'
            reason = "no shared functional/domain signal - kept as a separate cluster"

    return {
        "cluster_key": key,
        "cluster_id": cluster_id_for(key),
        "cluster_label": label,
        "cluster_theme": theme,
        "cluster_reason": reason,
        "domain": domain_key,
        "domain_term": domain_term,
        "function": effective_function,
        "function_term": function_term,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _member_score(member):
    return (member.get("_scores") or {}).get("ranking_score", 0)


def _member_orchard(member):
    dims = (member.get("_scores") or {}).get("dimensions") or {}
    if "tool_orchard" in dims:
        return dims["tool_orchard"]["points"]
    return 0


def build_cluster(info, members):
    """Aggregate one cluster from its member products."""
    members = sorted(members, key=lambda m: (-_member_score(m), m.get("name", "")))
    sources = []
    for member in members:
        source = member.get("_source", "unknown")
        if source not in sources:
            sources.append(source)

    scores = [_member_score(m) for m in members]
    confidence_values = [SW.SOURCE_CONFIDENCE.get(s, SW.DEFAULT_SOURCE_CONFIDENCE) for s in sources]
    strongest = max(confidence_values) if confidence_values else SW.DEFAULT_SOURCE_CONFIDENCE
    strongest_source = max(sources, key=lambda s: SW.SOURCE_CONFIDENCE.get(s, SW.DEFAULT_SOURCE_CONFIDENCE)) \
        if sources else "unknown"

    # Phase 5: discovery novelty + discovery quality, aggregated from members
    # (the per-item signals are attached during filtering).
    novelty_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNKNOWN": 3}
    novelties = [m.get("novelty_signal") or "UNKNOWN" for m in members]
    best_novelty = min(novelties, key=lambda n: novelty_order.get(n, 3)) if novelties else "UNKNOWN"
    discoveries = [m.get("discovery_quality") or "MEDIUM" for m in members]
    if "HIGH" in discoveries:
        cluster_discovery = "HIGH"
    elif "MEDIUM" in discoveries:
        cluster_discovery = "MEDIUM"
    else:
        cluster_discovery = "LOW"

    cluster = dict(info)
    cluster.update({
        "novelty_signal": best_novelty,
        "discovery_quality": cluster_discovery,
        "member_count": len(members),
        "member_names": [m.get("name") or m.get("title") or "Unknown" for m in members],
        "member_sources": sources,
        "source_diversity": len(sources),
        "strongest_source_confidence": SW.SOURCE_CONFIDENCE_LABELS.get(
            strongest_source, SW.DEFAULT_SOURCE_CONFIDENCE_LABEL),
        "strongest_source_confidence_value": strongest,
        "avg_solo_builder_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        "max_solo_builder_score": max(scores) if scores else 0,
        "tool_orchard_potential": max((_member_orchard(m) for m in members), default=0),
        "representative_product": members[0] if members else None,
        "members": members,
        # history defaults (overwritten by analyze_clusters when data exists)
        "days_seen": 1,
        "first_seen": None,
        "latest_seen": None,
        "repeat_appearances": 0,
    })
    cluster["evidence_summary"] = (
        f"{cluster['member_count']} product(s) from {cluster['source_diversity']} source(s); "
        f"best Solo Builder Score {cluster['max_solo_builder_score']}/100; "
        f"top member: {cluster['member_names'][0] if cluster['member_names'] else 'n/a'}"
    )
    cluster.update(score_cluster(cluster))
    return cluster


def assign_clusters(products):
    """Group products into clusters (duplicates are ignored, not counted twice)."""
    seen_names = set()
    seen_urls = set()
    groups = {}

    for product in products:
        if not isinstance(product, dict):
            continue
        name = product.get("name") or product.get("title") or ""
        norm_name = normalize_name(name)
        norm_url = normalize_url(
            product.get("link") or product.get("url") or product.get("website")
        )
        if norm_name and norm_name in seen_names:
            continue
        if norm_url and norm_url in seen_urls:
            continue
        if norm_name:
            seen_names.add(norm_name)
        if norm_url:
            seen_urls.add(norm_url)

        info = classify(product)
        groups.setdefault(info["cluster_id"], {"info": info, "members": []})
        groups[info["cluster_id"]]["members"].append(product)

    return [build_cluster(g["info"], g["members"]) for g in groups.values()]


# ---------------------------------------------------------------------------
# Cluster ranking
# ---------------------------------------------------------------------------

def score_cluster(cluster):
    """Deterministic cluster ranking score (0-100) plus a breakdown."""
    quality = cluster.get("max_solo_builder_score", 0)
    member_count = cluster.get("member_count", 0)
    source_diversity = cluster.get("source_diversity", 0)
    confidence = cluster.get("strongest_source_confidence_value", SW.DEFAULT_SOURCE_CONFIDENCE)
    days_seen = max(1, cluster.get("days_seen", 1) or 1)

    member_bonus = min(max(member_count - 1, 0) * CW.MEMBER_BONUS_PER_MEMBER, CW.MEMBER_BONUS_CAP)
    source_bonus = min(max(source_diversity - 1, 0) * CW.SOURCE_BONUS_PER_SOURCE, CW.SOURCE_BONUS_CAP)
    confidence_adjustment = int(round(
        max(-CW.CONFIDENCE_ADJUSTMENT_MAX,
            min(CW.CONFIDENCE_ADJUSTMENT_MAX, (confidence - 0.5) * 2 * CW.CONFIDENCE_ADJUSTMENT_MAX))
    ))
    persistence_bonus = min((days_seen - 1) * CW.PERSISTENCE_BONUS_PER_DAY, CW.PERSISTENCE_BONUS_CAP)

    penalties = {}
    sources = set(cluster.get("member_sources", []))
    if sources and sources <= set(CW.HN_ONLY_SOURCES):
        penalties["hn_only"] = -CW.HN_ONLY_PENALTY
    if member_count <= 1 and source_diversity <= 1:
        # Single product, single source: no corroborating evidence.
        penalties["singleton"] = -CW.SINGLETON_PENALTY

    bonuses = member_bonus + source_bonus + persistence_bonus
    if quality < CW.QUALITY_FLOOR:
        # Quality floor: weak clusters cannot buy their way up with volume.
        bonuses = int(bonuses * CW.LOW_QUALITY_BONUS_MULTIPLIER)
        penalties["below_quality_floor"] = 0

    novelty = cluster.get("novelty_signal", "UNKNOWN")
    novelty_adjustment = {
        "HIGH": CW.NOVELTY_ADJUSTMENT,
        "MEDIUM": 1,
        "LOW": -CW.NOVELTY_ADJUSTMENT,
        "UNKNOWN": 0,
    }.get(novelty, 0)

    raw_total = (quality + bonuses + confidence_adjustment
                 + sum(penalties.values()) + novelty_adjustment)
    final = max(0, min(CW.CLUSTER_SCORE_MAX, raw_total))

    reasons = [f"best member Solo Builder Score {quality}/100"]
    if member_bonus:
        reasons.append(f"supported by {member_count} products (+{member_bonus}, capped at +{CW.MEMBER_BONUS_CAP})")
    if source_bonus:
        reasons.append(f"seen on {source_diversity} sources (+{source_bonus}, capped at +{CW.SOURCE_BONUS_CAP})")
    if confidence_adjustment:
        sign = "+" if confidence_adjustment > 0 else ""
        reasons.append(f"source confidence {cluster.get('strongest_source_confidence', 'Unknown')} ({sign}{confidence_adjustment})")
    if persistence_bonus:
        reasons.append(f"seen on {days_seen} days (+{persistence_bonus})")
    if novelty_adjustment:
        sign = "+" if novelty_adjustment > 0 else ""
        reasons.append(f"discovery novelty {novelty} ({sign}{novelty_adjustment}, capped)")
    if "hn_only" in penalties:
        reasons.append(f"Hacker News is the only source ({penalties['hn_only']})")
    if "singleton" in penalties:
        reasons.append(f"single product from a single source ({penalties['singleton']})")
    if quality < CW.QUALITY_FLOOR:
        reasons.append(f"below the {CW.QUALITY_FLOOR}-point quality floor - bonuses halved")

    return {
        "cluster_score": final,
        "cluster_score_reasons": reasons,
        "cluster_score_breakdown": {
            "quality": quality,
            "member_bonus": member_bonus,
            "source_bonus": source_bonus,
            # bonuses_applied reflects the quality-floor halving below
            "bonuses_applied": bonuses,
            "confidence_adjustment": confidence_adjustment,
            "persistence_bonus": persistence_bonus,
            "novelty_signal": novelty,
            "novelty_adjustment": novelty_adjustment,
            "penalties": penalties,
            "raw_total": raw_total,
            "final": final,
        },
    }


def rank_clusters(clusters):
    """Sort clusters by cluster score (desc) with a stable tie-break."""
    ranked = sorted(clusters, key=lambda c: (-c["cluster_score"], c["cluster_id"]))
    for position, cluster in enumerate(ranked, 1):
        cluster["cluster_rank"] = position
    return ranked


# ---------------------------------------------------------------------------
# History / repeat signal
# ---------------------------------------------------------------------------

_HISTORY_SOURCE_KEYS = [
    "product_hunt", "toolify", "ai_tools", "chrome_extensions",
    "github_trending", "hacker_news",
]


def _history_products(day_data):
    products = []
    for key in _HISTORY_SOURCE_KEYS:
        items = day_data.get(key) or []
        if isinstance(items, list):
            products.extend(items)
    return products


def default_data_dir():
    return Path(__file__).resolve().parents[1] / "data" / "daily"


def load_history_clusters(days=CW.DEFAULT_HISTORY_DAYS, data_dir=None, today=None):
    """Map cluster_id -> {dates} using the stored JSON history.

    NOTE: history is limited to what ``data/daily`` currently holds (trimmed to
    28 days by ``storage.cleanup_old_data``). The current day is excluded here
    because it is analysed live. Days with no stored data simply contribute
    nothing - no metrics are fabricated.
    """
    base = Path(data_dir) if data_dir is not None else default_data_dir()
    today = today or timeutil.today_str()
    history = {}
    if not base.exists():
        return history

    for path in sorted(base.glob("*.json")):
        date = path.stem
        if not date or date >= today:
            continue
        try:
            day_data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(day_data, dict):
            continue
        for cluster in assign_clusters(_history_products(day_data)):
            record = history.setdefault(cluster["cluster_id"], {"dates": set()})
            record["dates"].add(date)

    return history


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def analyze_clusters(products, history_days=CW.DEFAULT_HISTORY_DAYS, data_dir=None, today=None):
    """Cluster, enrich with history signals and rank the given products."""
    today = today or timeutil.today_str()
    clusters = assign_clusters(products)
    history = load_history_clusters(days=history_days, data_dir=data_dir, today=today)

    for cluster in clusters:
        record = history.get(cluster["cluster_id"])
        past_dates = sorted(record["dates"]) if record else []
        cluster["days_seen"] = 1 + len(past_dates)
        cluster["repeat_appearances"] = len(past_dates)
        cluster["first_seen"] = past_dates[0] if past_dates else today
        cluster["latest_seen"] = today
        cluster["seen_dates"] = past_dates + [today]
        if not past_dates:
            cluster["history_note"] = (
                "only today's data available in data/daily (28-day retention)"
            )
        cluster.update(score_cluster(cluster))

    return rank_clusters(clusters)
