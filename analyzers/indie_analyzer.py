"""Rule-based solo-builder opportunity analysis (Phase 1).

Pipeline:
    normalize + de-duplicate -> hard filters -> weighted 0-100 Solo Builder
    Score -> optional +/-5 source-confidence ranking adjustment.

Everything here is deterministic: no LLM calls, no embeddings, no paid APIs,
no dollar estimates. All numeric constants live in
``config/scoring_weights.py``.
"""

import re

from analyzers.text_utils import (
    has_phrase as _has,
    normalize_name,
    normalize_url,
    product_text as _get_text,
)
from analyzers.clustering import analyze_clusters
from analyzers.keyword_candidates import attach_keyword_candidates, build_semrush_checklist
from analyzers.keyword_pool import build_keyword_pool, build_priority_checklist, tier_counts
from analyzers.opportunity import (
    attach_opportunities,
    build_opportunities,
    evidence_matrix,
    unmatched_signals,
)
from analyzers.seo_score import attach_seo
from analyzers.signal_bridge import bridge_summary, bridged_products
from analyzers.reddit_demand import (
    PAYMENT_ACTUAL,
    keyword_seeds,
    match_themes_to_clusters,
    recurring_pain,
    unmatched_pain,
)
from analyzers.source_quality import (
    DQ_LOW,
    GH_LOW,
    HN_DEMAND,
    HN_PRODUCT,
    classify_hn_item,
    discovery_quality,
    github_product_likeness,
    novelty_signal,
    source_health,
)
from analyzers.verdict import attach_verdict
from config import cluster_weights as CW
from config import scoring_weights as SW
from config import verdict_weights as VW
from config import timeutil
from storage import enrichment_store
from storage import validation_store


# ---------------------------------------------------------------------------
# Domain detection table
# (domain_id, keywords, user_persona, pain_description)
# Checked in priority order against name + description (lowercased).
# ---------------------------------------------------------------------------

_DOMAIN_TABLE = [
    ("fortune_telling",
     ["fortune", "tarot", "astrology", "horoscope", "fate", "zodiac",
      "psychic", "divination", "palm reading", "numerology", "birth chart", "crystal ball"],
     "spirituality enthusiasts and people curious about fortune telling or astrology",
     "They want personalised spiritual guidance or entertainment without expensive readings"),

    ("browser_extension",
     ["chrome extension", "browser extension", "firefox addon", "firefox extension", "manifest v3"],
     "everyday browser users who want to enhance their web experience",
     "They repeat tedious browser actions daily that a one-click extension could eliminate"),

    ("image_generation",
     ["image generation", "text to image", "generate image", "ai art",
      "stable diffusion", "dall-e", "midjourney", "art generator", "ai image"],
     "designers, content creators, and non-artists who need visuals quickly",
     "Creating custom images is slow and expensive; AI cuts this to seconds"),

    ("video_ai",
     ["video", "youtube", "subtitles", "transcript", "caption", "clip", "reel", "short video"],
     "content creators, video editors, and YouTubers",
     "Video production and editing takes enormous time; AI compresses the workflow"),

    ("writing_ai",
     ["copywriting", "essay", "blog post", "draft", "proofread", "grammar check",
      "text generation", "ai writer", "ai writing"],
     "writers, marketers, students, and professionals who produce written content regularly",
     "Writing from scratch is slow and mentally draining; they need a starting point or polishing"),

    ("social_media",
     ["twitter", "instagram", "tiktok", "linkedin", "social media",
      "post scheduler", "tweet", "followers", "engagement"],
     "social media managers, creators, and marketers",
     "Consistent posting is exhausting; they need scheduling, idea generation, or analytics"),

    ("developer_tool",
     ["developer", "engineer", "programmer", "coder", "devops",
      "git", "debug", "terminal", "cli", "ide", "vscode", "api client", "open source tool"],
     "software developers and engineers",
     "Developer workflow has constant friction - this removes one specific bottleneck"),

    ("productivity",
     ["productivity", "focus", "pomodoro", "task manager", "todo",
      "organize", "planner", "habit tracker", "time management", "deep work"],
     "knowledge workers and students who struggle with focus or task organisation",
     "Distraction and poor prioritisation kill output; they need a simple, frictionless system"),

    ("health_wellness",
     ["health", "fitness", "meditation", "wellness", "sleep tracker",
      "nutrition", "workout", "mindfulness", "mental health"],
     "health-conscious individuals and fitness enthusiasts",
     "Tracking habits and staying consistent is hard without personalised, gentle nudges"),

    ("language_learning",
     ["language learning", "vocabulary", "grammar", "learn spanish", "learn japanese",
      "flashcard", "anki", "language practice", "translation app"],
     "language learners at all levels",
     "Traditional language apps feel like homework; they want bite-sized, fun practice"),

    ("finance",
     ["budget", "expense tracker", "personal finance", "invest", "tax", "invoice", "accounting"],
     "individuals and freelancers managing personal or small-business finances",
     "Tracking money manually is tedious and error-prone; they want automatic clarity"),

    ("ecommerce",
     ["ecommerce", "shopify", "dropship", "amazon seller", "product listing", "online store"],
     "e-commerce store owners and online sellers",
     "Running a store involves constant manual tasks that eat into profit margins"),

    ("data_viz",
     ["chart", "dashboard", "data visualization", "spreadsheet", "csv", "data analysis", "report builder"],
     "analysts and data-curious non-technical users who need clear insights",
     "Raw data is overwhelming; they need clean visualisations without writing code"),

    ("entertainment",
     ["game", "quiz", "trivia", "fun", "entertainment", "puzzle", "interactive story"],
     "casual users looking for engaging entertainment or fun interactive experiences",
     "Generic entertainment is passive; they want personalised, interactive experiences"),
]


# ---------------------------------------------------------------------------
# Step 3 - hard exclusion rules
# ---------------------------------------------------------------------------
#
# Multi-word phrases are preferred over single broad keywords. Generic words
# such as "analytics", "platform" or "AI" are deliberately NOT filtered on
# their own (the audit flagged them as false positives).

_EXCLUSION_RULES = [
    ("Enterprise-only / workplace-B2B product", [
        "enterprise", "workplace", "for enterprises", "enterprise-grade",
        "sso", "single sign-on", "saml", "scim", "soc 2",
        "employee management", "hr platform",
    ]),
    ("Enterprise sales / demo-gated product", [
        "contact sales", "book a demo", "request a demo", "schedule a demo",
        "talk to sales", "get a quote", "custom pricing", "enterprise pricing",
        "book a call", "sales-led", "request pricing",
    ]),
    ("CRM / sales-ops / RevOps product", [
        "crm", "sales pipeline", "sales ops", "sales operations", "revops",
        "revenue operations", "lead scoring", "lead generation", "deal desk",
        "account management", "churn", "salesforce", "hubspot",
        "pipeline management", "outbound sequencing",
    ]),
    ("Agency / consulting / done-for-you service", [
        "agency", "consulting", "consultancy", "done-for-you", "done for you",
        "managed service", "professional services", "white glove",
        "white-glove", "custom development", "we build it for you",
    ]),
    ("Two-sided marketplace", [
        "marketplace", "two-sided", "supply and demand", "buyers and sellers",
        "connect freelancers", "match freelancers", "vendor marketplace",
    ]),
    ("Hardware product", [
        "hardware", "wearable", "robotics", "iot device", "firmware",
        "microcontroller", "smart speaker",
    ]),
    ("Crypto / blockchain product", [
        "blockchain", "crypto", "web3", "nft", "defi", "smart contract",
        "tokenomics",
    ]),
    ("Infrastructure-heavy tooling", [
        "kubernetes", "distributed system", "infrastructure", "on-premise",
        "on-prem", "data pipeline", "etl platform", "orchestration platform",
        "message queue",
    ]),
    ("Regulated domain", [
        "hipaa", "pci dss", "sox compliance", "gdpr compliance", "bank-grade",
        "regulated industry", "clinical trial", "medical device",
    ]),
    ("Requires large human service delivery", [
        "implementation services", "onboarding services", "dedicated manager",
        "account manager", "customer-specific", "bespoke implementation",
        "migration services",
    ]),
    ("Requires a multi-person team to build or run", [
        "multi-person team", "engineering team", "dev team required",
        "team of engineers", "full team",
    ]),
    ("Depends on expensive proprietary data", [
        "proprietary dataset", "licensed data", "exclusive dataset",
        "proprietary database", "proprietary data", "paid data feed",
        "bloomberg",
    ]),
    ("Very high recurring inference cost", [
        "real-time video", "live video generation", "continuous inference",
        "train your own model", "fine-tune a model", "gpu cluster",
        "render farm", "real-time voice cloning",
    ]),
    ("Requires heavy ongoing community moderation", [
        "community moderation", "moderator tools", "forum moderation",
        "social network for",
    ]),
]

# Compound phrases: a single generic word is fine, but a dominated combination
# is a strong enterprise/B2B signal.
_EXCLUSION_PAIRS = [
    ("Enterprise team analytics", ("analytics", "team")),
    ("Enterprise analytics platform", ("analytics", "enterprise")),
    ("B2B SaaS platform", ("saas", "b2b")),
    ("SaaS for enterprises", ("saas", "enterprise")),
    ("Platform for enterprises", ("platform", "enterprise")),
]

# GitHub repos that are developer libraries, not usable products.
GITHUB_LIBRARY_SIGNALS = [
    "npm install", "pip install", "cargo add", "gem install",
    "library for", "framework for", "use as a dependency",
    "import from", "package for", "#include", "sdk for", "boilerplate",
]

# ---------------------------------------------------------------------------
# Hacker News typing now lives in analyzers/source_quality.py (Phase 5):
# PRODUCT / DEMAND_SIGNAL / NEWS_DISCUSSION / UNKNOWN.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Step 4 / 7 / 8 - signal vocabularies
# ---------------------------------------------------------------------------

_UTILITY_TERMS = [
    "generator", "calculator", "checker", "converter", "finder", "analyzer",
    "directory", "template", "utility", "editor", "tracker", "scanner",
    "translator", "formatter", "extractor", "summarizer", "lookup",
    "comparison",
]

_EXTENSION_TERMS = [
    "chrome extension", "browser extension", "extension", "addon", "add-on",
    "plugin", "bookmarklet", "userscript",
]

_NOCODE_TERMS = [
    "no-code", "nocode", "no code", "drag and drop", "template",
    "out-of-the-box",
]

_AI_TERMS = [
    "ai", "gpt", "llm", "openai", "claude", "anthropic", "gemini",
    "ai-powered", "machine learning",
]

_HEAVY_TERMS = [
    "distributed", "real-time", "compiler", "kernel", "embedded", "streaming",
    "websocket", "microservice", "low-level", "concurrency",
]

_SELF_SERVICE_TERMS = [
    "self-service", "self service", "no sign-up", "no signup", "no login",
    "free online", "online tool", "web tool", "free tool", "try it free",
    "no account",
]

_VIRAL_TERMS = ["share", "viral", "referral", "invite friends", "social proof"]

_SALES_BURDEN_TERMS = [
    "contact sales", "book a demo", "request a demo", "schedule a demo",
    "talk to sales", "get a quote", "custom pricing", "enterprise pricing",
    "book a call", "sales call", "request pricing", "demo required",
]

_SERVICE_TERMS = [
    "agency", "consulting", "consultancy", "done-for-you", "done for you",
    "managed service", "professional services", "custom development",
    "white-glove", "white glove",
]

_TEAM_TERMS = [
    "for teams", "team plan", "team collaboration", "workspace for teams",
    "multiplayer", "collaborative workspace", "team workspace",
]

_HEAVY_INFERENCE_TERMS = [
    "video generation", "image generation", "voice cloning", "fine-tune",
    "fine tuning", "continuous inference", "real-time translation", "render",
]

_LOCAL_TERMS = [
    "browser-only", "runs in your browser", "client-side", "client side",
    "local processing", "offline", "on-device", "without uploading",
    "in-browser",
]

_DETERMINISTIC_TERMS = [
    "calculator", "converter", "checker", "formatter", "parser", "validator",
    "rule-based", "regex", "deterministic", "lookup table",
]

_CHEAP_LLM_TERMS = [
    "ai-powered", "gpt", "llm", "openai", "claude", "anthropic", "gemini",
    "prompt",
]

_PROPRIETARY_DATA_TERMS = [
    "proprietary dataset", "licensed data", "exclusive dataset",
    "proprietary database", "proprietary data", "paid data feed", "bloomberg",
]

_PLATFORM_SCOPE_TERMS = ["platform", "ecosystem", "suite", "infrastructure platform"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _detect_domain(product):
    """Return (domain_id, user_persona, pain_description) for a product."""
    name = (product.get("name") or product.get("title") or "").lower()
    desc = (product.get("description") or product.get("tagline") or "").lower()
    combined = name + " " + desc
    source = product.get("_source", "")

    for domain_id, keywords, persona, pain in _DOMAIN_TABLE:
        # Word-boundary aware matching: the previous substring check matched
        # "reel" inside "freelancers" and "ai" inside "email".
        if _has(combined, keywords):
            return domain_id, persona, pain

    if source == "github":
        return ("developer_tool",
                "software developers and open-source contributors",
                "They have a recurring pain in their development workflow that "
                "existing tools don't solve cleanly")

    return ("general",
            "general consumers looking for a specific solution",
            "They have a daily friction point with no good existing solution")


def _first_sentence(text):
    """Extract the first meaningful sentence from a description."""
    if not text:
        return ""
    parts = re.split(r"[.!?]", text)
    for part in parts:
        part = part.strip()
        if len(part) > 15:
            return part
    return text[:120].strip()


def _level(raw, low_cut=4, mid_cut=3):
    """Map a 0..5 raw sub-score onto LOW / MEDIUM / HIGH."""
    if raw >= low_cut:
        return "LOW"
    if raw >= mid_cut:
        return "MEDIUM"
    return "HIGH"


def _to_points(raw, weight):
    """Rescale a 0..RAW_MAX sub-score onto its configured weight."""
    raw = max(0, min(SW.RAW_MAX, raw))
    return int(round(raw / SW.RAW_MAX * weight))


# ---------------------------------------------------------------------------
# Step 6 - normalization + de-duplication
# ---------------------------------------------------------------------------

_SOURCE_ORDER = [
    "toolify", "product_hunt", "ai_tools", "chrome_extensions",
    "github", "hackernews",
]


def _merge_missing(target, duplicate):
    """Copy non-empty fields the keep-record is missing from its duplicate."""
    for key, value in duplicate.items():
        if key.startswith("_") or value in (None, "", [], {}):
            continue
        if not target.get(key):
            target[key] = value
    other = duplicate.get("_source")
    if other and other != target.get("_source"):
        target.setdefault("_also_in", [])
        if other not in target["_also_in"]:
            target["_also_in"].append(other)

    # Phase 6.2: keep provenance for bridged/duplicated products so one product
    # seen on two sources stays ONE product with two source references.
    sources = target.setdefault(
        "source_list", [target["_source"]] if target.get("_source") else []
    )
    for source in list(duplicate.get("source_list") or []) + ([other] if other else []):
        if source and source not in sources:
            sources.append(source)
    target["source_count"] = len(sources)

    ids = target.setdefault("underlying_source_ids", [])
    for uid in list(duplicate.get("underlying_source_ids") or []) + [
            duplicate.get("underlying_source_id")]:
        if uid and uid not in ids:
            ids.append(uid)


def normalize_products(all_products):
    """Attach source tags, normalize names/URLs and drop same-day duplicates.

    Duplicates are merged (richer record wins) and returned in a single list:
      * identical normalized names are merged
      * identical normalized URLs are dropped
      * the Toolify "new" + "trending" overlap is merged into one record
    """
    keys = [k for k in _SOURCE_ORDER if k in all_products]
    keys += [k for k in all_products if k not in _SOURCE_ORDER]

    by_name = {}
    seen_urls = set()
    result = []

    for source in keys:
        products = all_products.get(source) or []
        if not isinstance(products, list):
            continue
        for product in products:
            if not isinstance(product, dict):
                continue
            item = dict(product)
            item["_source"] = item.get("_source") or source
            item.setdefault("source_list", [item["_source"]])
            item.setdefault("source_count", 1)
            item.setdefault("underlying_source_ids",
                            [item["underlying_source_id"]] if item.get("underlying_source_id") else [])
            item["name"] = re.sub(
                r"\s+", " ", str(item.get("name") or item.get("title") or "")
            ).strip()

            norm_name = normalize_name(item.get("name") or item.get("title"))
            norm_url = normalize_url(
                item.get("link") or item.get("url") or item.get("website")
            )
            item["_norm_name"] = norm_name
            item["_norm_url"] = norm_url

            existing = by_name.get(norm_name) if norm_name else None
            if existing is not None:
                _merge_missing(existing, item)
                continue
            if norm_url and norm_url in seen_urls:
                continue

            if norm_name:
                by_name[norm_name] = item
            if norm_url:
                seen_urls.add(norm_url)
            result.append(item)

    return result


# ---------------------------------------------------------------------------
# Step 3 - filtering
# ---------------------------------------------------------------------------

def filter_reason(product):
    """Return a human-readable exclusion reason, or ``None`` if suitable."""
    text = _get_text(product)

    for reason, phrases in _EXCLUSION_RULES:
        found = _has(text, phrases)
        if found:
            return f"{reason}: '{found}'"

    for reason, (first, second) in _EXCLUSION_PAIRS:
        if _has(text, [first]) and _has(text, [second]):
            return f"{reason}: '{first}' + '{second}'"

    source = product.get("_source")

    # Hacker News: only genuine product posts enter the opportunity pipeline.
    if source == "hackernews":
        kind, why = classify_hn_item(product)
        product["hn_content_type"] = kind
        product["hn_content_reason"] = why
        if kind != HN_PRODUCT:
            if kind == HN_DEMAND:
                return f"HN demand signal (not a product): {why}"
            return f"Hacker News article/news item, not a product: {why}"

    # GitHub: only end-user-product repos enter the opportunity pipeline.
    if source == "github":
        level, why = github_product_likeness(product)
        product["github_product_likeness"] = level
        if level == GH_LOW:
            return f"GitHub product likeness {level}: {why}"
        desc = (product.get("description") or "").lower()
        for signal in GITHUB_LIBRARY_SIGNALS:
            if signal in desc:
                return f"GitHub library/package, not a product: '{signal}'"

    # Novelty + discovery quality (used for shortlist ordering, not scoring).
    novelty, novelty_why = novelty_signal(product, source)
    quality, quality_why = discovery_quality(product, source)
    product["novelty_signal"] = novelty
    product["novelty_reason"] = novelty_why
    product["discovery_quality"] = quality
    product["discovery_quality_reason"] = quality_why
    if quality == DQ_LOW:
        return f"Low discovery quality: {quality_why}"

    return None


def filter_unsuitable_products(all_products):
    """Normalize, de-duplicate and split products into suitable / filtered.

    Returns (suitable_list, filtered_out_list); filtered items carry an extra
    ``filter_reason`` key.
    """
    suitable = []
    filtered_out = []

    for product in normalize_products(all_products):
        reason = filter_reason(product)
        if reason:
            item = dict(product)
            item["filter_reason"] = reason
            filtered_out.append(item)
        else:
            suitable.append(product)

    return suitable, filtered_out


# ---------------------------------------------------------------------------
# Step 1 / 2 / 7 / 8 - dimension scoring
# ---------------------------------------------------------------------------

def score_build_ease(product):
    """A. Build Ease - 5 = very easy for a solo builder, 1 = very hard."""
    reasons = []
    domain = _detect_domain(product)[0]
    source = product.get("_source", "")
    text = _get_text(product)

    if domain == "browser_extension" or source == "chrome_extensions":
        raw = 5
        reasons.append("browser extension - HTML/JS/CSS scope, shippable by one person")
    elif _has(text, _UTILITY_TERMS):
        raw = 4
        reasons.append("single-purpose utility (generator/calculator/checker style)")
    elif domain in ("fortune_telling", "entertainment", "language_learning"):
        raw = 4
        reasons.append("content/UI-driven product with simple data needs")
    elif domain in ("image_generation", "video_ai", "ecommerce", "finance", "developer_tool"):
        raw = 3
        reasons.append("moderate build complexity for a solo MVP")
    else:
        raw = 3
        reasons.append("typical MVP scope for a solo builder")

    if _has(text, _NOCODE_TERMS):
        raw += 1
        reasons.append("no-code/template lever reduces build effort")
    if _has(text, _HEAVY_TERMS):
        raw -= 2
        reasons.append("heavy technical signals (distributed/real-time/low-level)")
    elif _has(text, _AI_TERMS) and not (
        domain == "browser_extension" or source == "chrome_extensions"
    ):
        raw -= 1
        reasons.append("requires AI/LLM integration work")

    return max(1, min(SW.RAW_MAX, raw)), reasons


def score_self_service_acquisition(product):
    """B. Self-Service Acquisition Fit - can users arrive without a sales team?"""
    reasons = []
    domain = _detect_domain(product)[0]
    source = product.get("_source", "")
    text = _get_text(product)

    if domain in ("browser_extension", "fortune_telling", "entertainment") \
            or source == "chrome_extensions":
        raw = 5
        reasons.append("store/viral distribution needs no sales team")
    elif domain in ("writing_ai", "image_generation", "video_ai", "social_media",
                    "productivity", "language_learning", "general"):
        raw = 4
        reasons.append("directory + SEO/community acquisition fits self-service")
    else:
        raw = 3
        reasons.append("needs targeted content/community effort to acquire users")

    found = _has(text, _VIRAL_TERMS)
    if found:
        raw += 1
        reasons.append(f"built-in sharing/virality signal ('{found}')")
    found = _has(text, _SELF_SERVICE_TERMS)
    if found:
        raw += 1
        reasons.append(f"explicit self-service signal ('{found}')")
    found = _has(text, _SALES_BURDEN_TERMS)
    if found:
        raw -= 3
        reasons.append(f"sales-gated acquisition ('{found}')")
    found = _has(text, _TEAM_TERMS)
    if found:
        raw -= 1
        reasons.append(f"team-oriented positioning ('{found}')")

    return max(0, min(SW.RAW_MAX, raw)), reasons


def score_monetization(product):
    """C. Monetization Potential."""
    reasons = []
    domain = _detect_domain(product)[0]
    text = _get_text(product)

    if _has(text, ["subscription", "monthly", "annual", "/mo", "per month", "/month"]):
        raw = 5
        reasons.append("clear subscription revenue model")
    elif _has(text, ["freemium", "free plan", "free tier", "upgrade", "premium"]):
        raw = 4
        reasons.append("freemium upgrade path")
    elif _has(text, ["one-time", "lifetime", "pay once", "one time payment"]):
        raw = 3
        reasons.append("one-time purchase model (lower lifetime value)")
    elif domain in ("finance", "ecommerce", "productivity"):
        raw = 4
        reasons.append("audience with proven willingness to pay")
    elif domain in ("fortune_telling", "entertainment"):
        raw = 3
        reasons.append("impulse / micro-purchase monetisation")
    else:
        raw = 3
        reasons.append("monetisation not explicit - assume freemium")

    if re.search(r"\$\d", text) or _has(text, ["pricing", "per seat", "per user"]):
        raw += 1
        reasons.append("explicit pricing signal")
    if _has(text, ["free forever", "completely free", "100% free", "totally free"]) \
            and not _has(text, ["premium", "subscription", "upgrade"]):
        raw -= 1
        reasons.append("positioned as permanently free (weaker monetisation)")

    return max(0, min(SW.RAW_MAX, raw)), reasons


def score_low_communication(product):
    """D. Low Communication / Sales Burden - 5 = no customer contact needed."""
    reasons = []
    domain = _detect_domain(product)[0]
    text = _get_text(product)

    if _has(text, _SERVICE_TERMS):
        raw = 1
        reasons.append("service/consulting delivery - high per-customer communication")
    elif _has(text, _SALES_BURDEN_TERMS):
        raw = 2
        reasons.append("sales call / demo required - high communication burden")
    elif _has(text, _TEAM_TERMS):
        raw = 3
        reasons.append("team-oriented product - more onboarding and support contact")
    elif domain in ("browser_extension", "fortune_telling", "entertainment",
                    "language_learning", "writing_ai", "image_generation",
                    "video_ai", "productivity", "general"):
        raw = 5
        reasons.append("self-service consumer tool - no customer contact required")
    else:
        raw = 4
        reasons.append("self-service prosumer tool - minimal support burden")

    return max(0, min(SW.RAW_MAX, raw)), reasons


def score_operating_cost(product):
    """E. Operating Cost / Maintenance - 5 = nearly free to run."""
    reasons = []
    domain = _detect_domain(product)[0]
    text = _get_text(product)

    if _has(text, _LOCAL_TERMS) or _has(text, _EXTENSION_TERMS):
        raw = 5
        reasons.append("browser-only / local processing - near-zero marginal cost")
    elif _has(text, _PROPRIETARY_DATA_TERMS):
        raw = 1
        reasons.append("depends on proprietary/paid datasets - expensive to operate")
    elif _has(text, _HEAVY_INFERENCE_TERMS) or domain == "video_ai":
        raw = 2
        reasons.append("generation-heavy inference - high recurring compute cost")
    elif _has(text, _CHEAP_LLM_TERMS):
        raw = 4
        reasons.append("occasional cheap LLM call - low but non-zero cost")
    elif _has(text, _DETERMINISTIC_TERMS):
        raw = 5
        reasons.append("deterministic processing - cheap to run at scale")
    else:
        raw = 4
        reasons.append("moderate serving cost")

    if raw == 4 and domain == "image_generation":
        raw = 3
        reasons.append("image generation adds per-use API cost")

    return max(0, min(SW.RAW_MAX, raw)), reasons


def score_solo_builder_fit(product):
    """F. Solo-Builder Fit - can one person ship and maintain this?"""
    reasons = []
    domain = _detect_domain(product)[0]
    source = product.get("_source", "")
    text = _get_text(product)

    if domain == "browser_extension" or source == "chrome_extensions":
        raw = 5
        reasons.append("extension distribution and scope suit a single builder")
    elif _has(text, _PLATFORM_SCOPE_TERMS):
        raw = 2
        reasons.append("platform/ecosystem scope is hard to maintain solo")
    elif _has(text, _SERVICE_TERMS):
        raw = 2
        reasons.append("service-shaped business needs people, not just code")
    elif _has(text, _TEAM_TERMS):
        raw = 3
        reasons.append("team product - solo maintenance is harder")
    elif source == "github":
        raw = 4
        reasons.append("OSS core + hosted layer is a proven solo path")
    else:
        raw = 4
        reasons.append("single-purpose scope suits one maintainer")

    if _has(text, _NOCODE_TERMS):
        raw += 1
        reasons.append("template/no-code shortcuts reduce solo effort")

    return max(1, min(SW.RAW_MAX, raw)), reasons


def score_tool_orchard(product):
    """G. Tool-Orchard Expansion Potential - could it become many tool pages?"""
    reasons = []
    domain = _detect_domain(product)[0]
    text = _get_text(product)

    if _has(text, ["converter", "convert", "conversion"]):
        raw = 5
        reasons.append("converter family - many adjacent format/target pages")
    elif _has(text, ["calculator", "calculate", "estimate"]):
        raw = 5
        reasons.append("calculator family - expands into many niche variations")
    elif _has(text, ["checker", "validator", "scanner", "detector"]):
        raw = 4
        reasons.append("checker family - natural per-domain expansion")
    elif _has(text, ["generator", "generate"]):
        raw = 4
        reasons.append("generator family - multiple use-case pages")
    elif _has(text, ["image", "photo", "audio", "video", "pdf", "file"]):
        raw = 4
        reasons.append("media/file utility - adjacent tool pages available")
    elif _has(text, ["directory", "listing", "catalog"]):
        raw = 4
        reasons.append("directory format - expands by niche/category")
    elif _has(text, _SERVICE_TERMS):
        raw = 1
        reasons.append("service business - no productized tool orchard")
    elif domain in ("entertainment", "fortune_telling"):
        raw = 3
        reasons.append("some adjacent pages (signs/topics) but narrow")
    else:
        raw = 3
        reasons.append("modest expansion potential")

    if _has(text, ["suite", "collection", "multiple tools", "toolbox", "all-in-one"]):
        raw += 1
        reasons.append("multi-tool positioning already present")
    if _has(text, ["one-off", "novelty", "just for fun", "toy project"]):
        raw -= 1
        reasons.append("novelty/single-shot product")

    return max(1, min(SW.RAW_MAX, raw)), reasons


# (dimension id, label, rule function)
_DIMENSION_SPECS = [
    ("build_ease", "Build Ease", score_build_ease),
    ("self_service_acquisition", "Self-Service Acquisition", score_self_service_acquisition),
    ("monetization", "Monetization", score_monetization),
    ("low_communication", "Low Communication Burden", score_low_communication),
    ("operating_cost", "Operating Cost", score_operating_cost),
    ("solo_builder_fit", "Solo-Builder Fit", score_solo_builder_fit),
    ("tool_orchard", "Tool-Orchard Potential", score_tool_orchard),
]


def source_confidence(source):
    """Return (label, numeric confidence 0..1) for a source key."""
    value = SW.SOURCE_CONFIDENCE.get(source, SW.DEFAULT_SOURCE_CONFIDENCE)
    label = SW.SOURCE_CONFIDENCE_LABELS.get(source, SW.DEFAULT_SOURCE_CONFIDENCE_LABEL)
    return label, value


def source_adjustment(source):
    """Ranking adjustment in points, clamped to +/- MAX_SOURCE_ADJUSTMENT."""
    _, value = source_confidence(source)
    raw = (value - 0.5) * 2 * SW.MAX_SOURCE_ADJUSTMENT
    return max(-SW.MAX_SOURCE_ADJUSTMENT,
               min(SW.MAX_SOURCE_ADJUSTMENT, int(round(raw))))


def _select_reasons(entries, label, adjustment):
    """Pick 2-5 short reasons: strongest + weakest dimensions, then signals."""
    sign = f"+{adjustment}" if adjustment >= 0 else str(adjustment)
    reasons = [f"source confidence {label} ({sign} ranking points)"]

    ranked = sorted(entries, key=lambda e: (e[2] / e[3], e[0]))
    worst, best = ranked[0], ranked[-1]

    if best[4]:
        reasons.append(f"strongest: {best[1]} {best[2]}/{best[3]} - {best[4][0]}")
    if worst[0] != best[0] and worst[4]:
        reasons.append(f"weakest: {worst[1]} {worst[2]}/{worst[3]} - {worst[4][0]}")

    for _, _, _, _, rule_reasons in reversed(ranked):
        for reason in rule_reasons[1:]:
            if len(reasons) >= SW.MAX_REASONS:
                break
            reasons.append(reason)
        if len(reasons) >= SW.MAX_REASONS:
            break

    return reasons[:SW.MAX_REASONS]


def score_product(product):
    """Compute the weighted 0-100 Solo Builder Score for one product.

    Returns a dict with the per-dimension breakdown, the source-confidence
    adjustment, the ranking score and 2-5 short reasons.
    """
    dimensions = {}
    entries = []

    for key, label, rule in _DIMENSION_SPECS:
        raw, rule_reasons = rule(product)
        weight = SW.WEIGHTS[key]
        dimensions[key] = {
            "label": label,
            "raw": raw,
            "points": _to_points(raw, weight),
            "max": weight,
            "reasons": rule_reasons,
        }
        entries.append((key, label, dimensions[key]["points"], weight, rule_reasons))

    total = sum(d["points"] for d in dimensions.values())
    total = max(0, min(SW.TOTAL_MAX, total))

    source = product.get("_source", "")
    label, confidence = source_confidence(source)
    adjustment = source_adjustment(source)
    ranking = max(0, min(SW.TOTAL_MAX, total + adjustment))

    return {
        "total_score": total,
        "ranking_score": ranking,
        "source_confidence": label,
        "source_confidence_value": confidence,
        "source_adjustment": adjustment,
        "dimensions": dimensions,
        # convenience flat values (raw 0..5 sub-scores)
        "build_ease": dimensions["build_ease"]["raw"],
        "self_service_acquisition": dimensions["self_service_acquisition"]["raw"],
        "monetization": dimensions["monetization"]["raw"],
        "low_communication": dimensions["low_communication"]["raw"],
        "operating_cost": dimensions["operating_cost"]["raw"],
        "solo_builder_fit": dimensions["solo_builder_fit"]["raw"],
        "tool_orchard": dimensions["tool_orchard"]["raw"],
        "operating_cost_level": _level(dimensions["operating_cost"]["raw"]),
        "communication_burden": _level(dimensions["low_communication"]["raw"]),
        "reasons": _select_reasons(entries, label, adjustment),
    }


def rank_products(all_products):
    """Normalize, filter, score and rank a dict of source -> product list.

    Returns (ranked_suitable, filtered_out). Products are sorted by
    ``ranking_score`` (base score plus the +/-5 source adjustment).
    """
    suitable, filtered_out = filter_unsuitable_products(all_products)
    for product in suitable:
        product["_scores"] = score_product(product)
    suitable.sort(key=lambda p: (-p["_scores"]["ranking_score"], p.get("name", "")))
    return suitable, filtered_out


# ---------------------------------------------------------------------------
# Step 9 - deep dive (same framework; buildability now driven by build_ease)
# ---------------------------------------------------------------------------

def deep_analyze_product(product, rank):
    """Generate a detailed, product-specific markdown analysis section."""
    name = product.get("name") or product.get("title") or "Unknown Product"
    description = product.get("description") or product.get("tagline") or "No description available."
    url = product.get("url") or product.get("link") or product.get("website") or ""
    source = product.get("_source", "unknown")
    scores = product.get("_scores", {})

    url_line = f"[{url}]({url})" if url else "_URL not available_"
    text = _get_text(product)

    domain_id, user_persona, pain_description = _detect_domain(product)
    core_sentence = _first_sentence(description)

    # 1. Who are the users?
    if domain_id in ("developer_tool",) or source == "github":
        audience_type = "B2C prosumer / B2B small teams"
    elif domain_id in ("ecommerce", "data_viz"):
        audience_type = "B2C prosumers and small business owners (not enterprise)"
    else:
        audience_type = "B2C - individual users making a personal purchase decision"
    users = f"**{user_persona.capitalize()}** ({audience_type})."

    # 2. Why do they need it?
    pain_point = pain_description
    if core_sentence:
        pain_point += f'\n\n  > What the product says: _"{core_sentence}"_'

    # 3. How does it find users?
    if source == "chrome_extensions" or domain_id == "browser_extension":
        distribution = (
            "**Chrome Web Store** organic search is the primary channel - users search for a task "
            "and your extension appears. Submit to extension directories (extlib.io, alternativeto). "
            "Zero ongoing CAC once listed."
        )
    elif source == "github":
        distribution = (
            "**GitHub Trending** -> HN 'Show HN' post -> dev Twitter/X. The README *is* the landing page. "
            "Stars compound: once it trends, press coverage follows automatically."
        )
    elif domain_id == "fortune_telling":
        distribution = (
            "**Viral sharing** is the engine - users share their reading results on social media. "
            "Target SEO keywords like 'free tarot reading online', 'daily horoscope [zodiac]'. "
            "TikTok/Reels short demos can explode in the spirituality niche."
        )
    elif domain_id == "entertainment":
        distribution = (
            "**Shareable results** drive organic growth (quiz results, game scores). "
            "Post short demo clips on TikTok/Instagram Reels. "
            "Reddit communities (r/quiz, niche hobby subreddits) for targeted seeding."
        )
    elif domain_id in ("writing_ai", "image_generation", "video_ai"):
        distribution = (
            "**AI tool directories** (There's An AI For That, Futurepedia, Toolify) drive high-intent "
            "passive traffic. Product Hunt launch for initial spike. "
            "Before/after demos on Twitter/X - the output is inherently shareable."
        )
    elif source == "product_hunt":
        distribution = (
            "**Product Hunt community** for launch momentum. "
            "Follow with SEO content targeting the core use case and directory submissions. "
            "The PH badge adds credibility for cold outreach."
        )
    else:
        distribution = (
            "**SEO + community seeding**: write content targeting the core pain-point keyword, "
            "then engage in the niche's Reddit / Discord / Facebook Group. "
            "Direct DMs to potential users for early feedback and word-of-mouth."
        )

    # 4. Business model & revenue estimate
    if _has(text, ["subscription", "monthly", "annual", "/mo", "per month"]):
        biz_model = (
            "Subscription SaaS. In this niche, $7-$29/month is typical. "
            "At **500 paying users -> $42K-$174K ARR**. Watch monthly churn - keep below 5%."
        )
    elif _has(text, ["freemium", "free plan", "upgrade", "free tier"]):
        biz_model = (
            "Freemium. Free tier creates a large user base; paid tier unlocks limits or power features. "
            "Industry average: **2-5% free->paid conversion**. "
            "A $9-$19/month Pro plan is the sweet spot for this audience."
        )
    elif _has(text, ["one-time", "lifetime", "pay once"]):
        biz_model = (
            "One-time purchase. Excellent for AppSumo / LTD deals to bootstrap early revenue. "
            "Lower LTV, but great launch momentum and zero churn overhead."
        )
    elif domain_id in ("fortune_telling", "entertainment"):
        biz_model = (
            "Free with credits / microtransactions, or freemium with a **$2.99-$4.99/month** "
            "'unlimited readings' tier. This audience converts well on impulse micro-purchases. "
            "Ad-supported free tier also viable at scale."
        )
    elif source == "github":
        biz_model = (
            "**Open-source core + hosted SaaS layer**. Revenue comes from the managed/hosted version "
            "($10-$50/month). The OSS version builds credibility, backlinks, and a user base "
            "that eventually upgrades for convenience."
        )
    else:
        biz_model = (
            "Monetisation model not explicit from public info. "
            "For indie viability, target freemium with a **$9-$29/month** paid tier. "
            "Validate willingness to pay before building the billing system."
        )

    # 5. What can I learn?
    learnings = []
    if domain_id == "fortune_telling":
        learnings.append(
            "Spiritual / entertainment niches are vastly underserved by developers - "
            "most builders ignore them, leaving them wide open."
        )
        learnings.append(
            "Users come back *daily* if the content feels personalised and fresh - "
            "retention is built-in if you add variety (daily draws, moon phases, etc.)."
        )
    elif domain_id in ("browser_extension",) or source == "chrome_extensions":
        learnings.append(
            "The Chrome Web Store is a search engine most developers forget to compete in - "
            "a well-optimised listing gets passive, recurring installs with zero ad spend."
        )
        learnings.append(
            "Extensions have structurally better retention than web apps: "
            "uninstalling requires deliberate effort, so users stick around."
        )
    elif domain_id in ("writing_ai", "image_generation", "video_ai"):
        learnings.append(
            "AI wrapper products succeed on UX, not model quality - the underlying AI is a commodity. "
            "The product is the workflow, the UI, and the presets."
        )
    elif source == "github":
        learnings.append(
            "OSS projects that solve a real pain can convert GitHub stars to paying SaaS users - "
            "the repo *is* the marketing funnel."
        )
    if not learnings:
        learnings.append(
            "Tight niche focus beats broad reach - the more specific the problem, "
            "the easier it is to find users who will pay."
        )
        learnings.append(
            "This product's single-purpose approach is the right indie instinct: "
            "one problem, one solution, one clear CTA."
        )

    # 6. One-sentence pitch
    if core_sentence:
        pitch = (
            f"{name} helps {user_persona} by letting them "
            f"{core_sentence.lower().rstrip('.')}."
        )
    else:
        pitch = (
            f"{name} is the simplest way for {user_persona} "
            f"to {pain_description.lower().rstrip('.')}."
        )

    # 7. Can I build it? (build_ease: 5 = easy, 1 = hard)
    build_ease = scores.get("build_ease", 3)
    if source == "chrome_extensions" or domain_id == "browser_extension":
        buildable = (
            "**Yes** - Chrome extensions are HTML/CSS/JS. Any web developer can ship an MVP "
            "in a weekend. Google's Manifest V3 docs are excellent."
        )
    elif source == "github":
        buildable = (
            "**Yes, and the hard part is done** - it's open source. You can fork it, "
            "add a hosted layer (auth + Stripe billing), and launch a SaaS in 2-4 weeks."
        )
    elif build_ease >= 4:
        buildable = (
            "**Yes** - low technical complexity. "
            "A solo developer could ship an MVP in 1-2 weeks using existing APIs and a simple UI."
        )
    elif build_ease == 3:
        buildable = (
            "**Probably** - moderate complexity (AI API calls + basic UI). "
            "Use OpenAI / Claude API + a simple React or Next.js frontend. "
            "Expect 2-4 weeks for a solid, shippable MVP."
        )
    else:
        buildable = (
            "**Maybe** - higher complexity. Scope ruthlessly: build only the single core feature first, "
            "ignore everything else. Budget 1-3 months solo, or find a technical co-founder."
        )

    # 8. How do I find users?
    acquisition = scores.get("self_service_acquisition", 2)
    if domain_id == "fortune_telling":
        find_users = (
            "Post on **r/astrology**, **r/tarot**, **r/spirituality** - these are massive, "
            "active communities hungry for tools. Create TikTok videos showing a live reading. "
            "Target '[zodiac sign] daily horoscope' SEO - millions of monthly searches."
        )
    elif source == "chrome_extensions" or domain_id == "browser_extension":
        find_users = (
            "Optimise your **Chrome Web Store listing** (title + description for search terms). "
            "Post in subreddits relevant to the use case. "
            "Submit to ProductHunt and extension directories (extlib.io, chromeextensions.dev)."
        )
    elif source == "github" or domain_id == "developer_tool":
        find_users = (
            "Post a **'Show HN'** on Hacker News, tweet with a demo GIF, "
            "and post in relevant subreddits (r/programming, r/devtools, tool-specific subs). "
            "Write a blog post about the problem you solved - SEO + dev community sharing."
        )
    elif domain_id in ("writing_ai", "image_generation", "video_ai"):
        find_users = (
            "Submit to **There's An AI For That**, **Futurepedia**, and **Toolify** - "
            "these directories drive passive, high-intent traffic. "
            "Post a compelling before/after demo on Twitter/X to seed virality."
        )
    elif domain_id == "productivity":
        find_users = (
            "Post on **r/productivity** and **r/getdisciplined**. "
            "Write a 'how I fixed my workflow' blog post that naturally features the tool. "
            "Reach out to productivity-focused YouTubers or newsletter writers for an honest review."
        )
    elif acquisition >= 4:
        find_users = (
            "The built-in viral loop or SEO potential does the heavy lifting. "
            "Kick-start with a Product Hunt launch and submissions to relevant directories. "
            "Then let organic growth compound."
        )
    else:
        find_users = (
            "Write **SEO content** targeting the core pain-point keyword. "
            "Engage in niche Discord / Slack / Reddit communities where your target users hang out. "
            "Cold-DM 10-20 potential users on Twitter/LinkedIn and offer free beta access."
        )

    # First step recommendation
    if domain_id == "fortune_telling":
        first_step = (
            "Check Google Trends for 'free tarot reading online' and 'daily horoscope'. "
            "If trending, build a dead-simple landing page with ONE free reading - no login required - "
            "and post the link on r/astrology tonight."
        )
    elif source == "github":
        first_step = (
            "Star the repo and run it locally. If it solves a real pain you have, "
            "build a hosted version with a free tier and post 'Show HN'. "
            "Let real usage tell you what to charge."
        )
    elif domain_id == "browser_extension" or source == "chrome_extensions":
        first_step = (
            "Search the Chrome Web Store for similar extensions and read the **1-star reviews** - "
            "that's your feature backlog. Build one clear improvement over the top competitor and launch."
        )
    else:
        first_step = (
            f"Search Reddit and Twitter for '{name}' or the core pain point. "
            f"Find 5-10 threads where people wish this existed or complain about current solutions. "
            f"DM those users - offer free early access in exchange for a 15-minute call."
        )

    lines = [
        f"## #{rank} \u2014 {name}",
        f"> Source: `{source}` | {url_line}",
        "",
        f"**Description:** {description}",
        "",
        "---",
        "",
        "### 1. Who are the users?",
        users,
        "",
        "### 2. Why do they need it?",
        pain_point,
        "",
        "### 3. How does it find users?",
        distribution,
        "",
        "### 4. Does it make money? How much?",
        biz_model,
        "",
        "### 5. What can I learn from this?",
        "\n".join(f"- {l}" for l in learnings),
        "",
        "### 6. One-sentence pitch",
        f"_{pitch}_",
        "",
        "### 7. Can I build it?",
        buildable,
        "",
        "### 8. How do I find users?",
        find_users,
        "",
        "---",
        "",
        f"\U0001F4A1 **First Step:** {first_step}",
        "",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step 9 - markdown report
# ---------------------------------------------------------------------------

def _fmt_dim(score, key):
    dim = score["dimensions"][key]
    return f"{dim['points']}/{dim['max']}"


_STORED_SOURCE_KEYS = {"github_trending": "github", "hacker_news": "hackernews"}


def clusters_for_day(day_data, enrichment_path=None, validation_path=None, today=None):
    """Rebuild ranked clusters (with keywords + SEO) from one stored day's JSON.

    Used by ``scripts/enrich.py`` so the manual workflow sees exactly the same
    clusters and keyword candidates as the daily report.
    """
    groups = {}
    for stored_key, products in (day_data or {}).items():
        if not isinstance(products, list):
            continue
        source = _STORED_SOURCE_KEYS.get(stored_key, stored_key)
        groups.setdefault(source, []).extend(products)

    suitable, _ = rank_products(groups)
    store = enrichment_store.load_store(enrichment_path)
    clusters = attach_keyword_candidates(analyze_clusters(suitable, today=today))
    attach_seo(clusters, store)
    validation = validation_store.load_store(
        validation_path if validation_path is not None else validation_store.default_path()
    )
    attach_verdict(clusters, validation, record_history=False, today=today)
    return clusters


def _score_table(suitable):
    lines = [
        "| # | Product | Source | Confidence | Score | Build Ease | Self-Serve "
        "| Monetize | Comms | Op Cost | Solo Fit | Orchard |",
        "|---|---|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|",
    ]
    for i, product in enumerate(suitable, 1):
        name = (product.get("name") or product.get("title") or "Unknown").replace("|", "/")
        score = product["_scores"]
        adjustment = score["source_adjustment"]
        sign = f"+{adjustment}" if adjustment >= 0 else str(adjustment)
        confidence = f"{score['source_confidence']} ({sign})"
        lines.append(
            f"| {i} | {name} | {product.get('_source', '?')} | {confidence} "
            f"| **{score['ranking_score']}** | {_fmt_dim(score, 'build_ease')} "
            f"| {_fmt_dim(score, 'self_service_acquisition')} "
            f"| {_fmt_dim(score, 'monetization')} "
            f"| {_fmt_dim(score, 'low_communication')} "
            f"| {_fmt_dim(score, 'operating_cost')} ({score['operating_cost_level']}) "
            f"| {_fmt_dim(score, 'solo_builder_fit')} "
            f"| {_fmt_dim(score, 'tool_orchard')} |"
        )
    return lines


def _reasons_section(suitable):
    lines = ["### Why these scores", ""]
    for i, product in enumerate(suitable, 1):
        score = product["_scores"]
        name = product.get("name") or product.get("title") or "Unknown"
        link = product.get("link") or product.get("url") or ""
        if product.get("_source") == "github" and not link:
            link = f"https://github.com/{name}"
        name_str = f"[{name}]({link})" if link else name
        lines.append(
            f"**#{i} {name_str} - {score['ranking_score']}/100** "
            f"(base {score['total_score']}, source {score['source_confidence']}, "
            f"operating cost {score['operating_cost_level']}, "
            f"communication {score['communication_burden']})"
        )
        lines.append("")
        for reason in score["reasons"]:
            lines.append(f"- {reason}")
        lines.append("")
    return lines


def _cluster_section(clusters, detail_limit=10):
    """Section A: the cluster-level opportunity radar."""
    lines = ["## Top Opportunity Clusters", ""]
    if not clusters:
        lines += ["_No clusters were produced._", ""]
        return lines

    lines += [
        "| # | Cluster | Solo Builder | Cluster Evidence | SEO | Opportunity | Market Gate "
        "| Verdict | Products | Sources |",
        "|---|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|",
    ]
    for cluster in clusters[:CW.MAX_CLUSTERS_IN_TABLE]:
        label = str(cluster["cluster_label"]).replace("|", "/")
        seo = (str(cluster.get("seo_score", 0))
               if cluster.get("seo_score_status") != "NOT_CHECKED" else "-")
        lines.append(
            f"| {cluster['cluster_rank']} | {label} "
            f"| {cluster['max_solo_builder_score']}/100 | {cluster['cluster_score']}/100 "
            f"| {seo} | {cluster.get('opportunity_score', 0)}/100 "
            f"| {cluster.get('market_demand_gate', 'UNKNOWN')} "
            f"| **{cluster.get('verdict', '-')}** "
            f"| {cluster['member_count']} | {cluster['source_diversity']} |"
        )
    lines.append("")
    if len(clusters) > CW.MAX_CLUSTERS_IN_TABLE:
        lines += [
            f"_Showing the top {CW.MAX_CLUSTERS_IN_TABLE} of {len(clusters)} clusters. "
            "Lower-ranked single-product clusters are still listed in the "
            "Individual Product Evidence section below._",
            "",
        ]

    for cluster in clusters[:detail_limit]:
        seen = f"{cluster['days_seen']} day(s)"
        if cluster.get("first_seen"):
            seen += f" (first {cluster['first_seen']}, latest {cluster['latest_seen']})"
        if cluster.get("history_note"):
            seen += f" - {cluster['history_note']}"

        lines += [
            f"### #{cluster['cluster_rank']} {cluster['cluster_label']} - "
            f"{cluster['cluster_score']}/100",
            "",
            f"- **Cluster id:** `{cluster['cluster_id']}` (key `{cluster['cluster_key']}`)",
            f"- **Why grouped:** {cluster['cluster_reason']}",
            f"- **Evidence:** {cluster['evidence_summary']}",
            f"- **Solo Builder Score:** best {cluster['max_solo_builder_score']}/100, "
            f"average {cluster['avg_solo_builder_score']}/100",
            f"- **Cluster Evidence Score:** {cluster['cluster_score']}/100 "
            f"(best member {cluster['max_solo_builder_score']}/100, "
            f"{cluster['member_count']} product(s) from {cluster['source_diversity']} source(s))",
            f"- **Tool-Orchard potential:** {cluster['tool_orchard_potential']}/10",
            f"- **Sources:** {', '.join(cluster['member_sources'])} "
            f"(strongest confidence: {cluster['strongest_source_confidence']})",
            f"- **Seen:** {seen}",
            f"- **Representative product:** "
            f"{cluster['member_names'][0] if cluster['member_names'] else 'n/a'}",
            f"- **Members:** {', '.join(str(n).replace('|', '/') for n in cluster['member_names'])}",
            "- **Cluster score:** " + "; ".join(cluster["cluster_score_reasons"]),
            "",
        ]
        lines += [
            f"- **SEO Opportunity Score:** {cluster.get('seo_score', 0)}/100 "
            f"({cluster.get('seo_score_status', 'NOT_CHECKED')})",
            f"- **Market Demand Gate:** {cluster.get('market_demand_gate', 'UNKNOWN')}",
            "- **SEO basis:** " + "; ".join(cluster.get("seo_reasons", [])),
            "",
        ]
        checked = cluster.get("checked_keywords") or []
        if checked:
            lines += [
                "| Checked keyword | US volume | Global volume | KD | Weak SERP | Score |",
                "|---|---:|---:|---:|---|---:|",
            ]
            for keyword in checked:
                weak = "yes" if keyword.get("weak_serp") else "no"
                if keyword.get("weak_serp_count") is not None:
                    weak = f"yes ({keyword['weak_serp_count']} weak sites)"
                lines.append(
                    f"| {keyword['keyword']} | {keyword['us_volume']:,} "
                    f"| {keyword['global_volume']:,} | {keyword['kd']} | {weak} "
                    f"| {keyword['keyword_score']}/85 |"
                )
            lines.append("")
        else:
            lines += ["_No keywords enriched yet - run `python scripts/enrich.py`._", ""]
        rejected = cluster.get("rejected_keywords") or []
        if rejected:
            lines += [f"- **Rejected keywords:** {', '.join(rejected)}", ""]

        lines += [
            f"- **Opportunity Score:** {cluster.get('opportunity_score', 0)}/100",
            f"- **Verdict:** **{cluster.get('verdict', '-')}**",
            f"- **Substitution risk:** {cluster.get('substitution_risk', 'MEDIUM')} "
            f"({'; '.join(cluster.get('substitution_reasons', [])[:1]) or '-'})",
            f"- **Primary acquisition:** "
            f"{cluster.get('primary_acquisition_channel', 'UNKNOWN')} "
            f"(fit {cluster.get('acquisition_fit', 'WEAK')})",
            f"- **Monetization:** {cluster.get('monetization_model', 'unknown')} "
            f"(confidence {cluster.get('monetization_confidence', 'UNKNOWN')})",
            f"- **Operating-cost risk:** {cluster.get('operating_cost_risk', 'MEDIUM')}",
            "- **Why:** " + "; ".join(cluster.get("verdict_reasons", []) or ["-"]),
        ]
        blocking = cluster.get("blocking_reasons") or []
        if blocking:
            lines.append("- **Not BUILD because:** " + "; ".join(blocking))
        gaps = cluster.get("validation_gaps") or []
        if gaps:
            lines.append("- **Next actions:**")
            for index, gap in enumerate(gaps, 1):
                lines.append(f"  {index}. {gap}")
        history = cluster.get("verdict_history") or []
        if history:
            chain = [history[0].get("previous_verdict") or "NEW"]
            chain += [entry.get("new_verdict") for entry in history]
            lines.append(f"- **Verdict history:** {' -> '.join(chain)} "
                         f"(last change {history[-1].get('date')})")
        lines.append("")

        candidates = cluster.get("keyword_candidates", [])
        if candidates:
            lines += [
                "- **Keyword candidates:**",
                "",
                "| Keyword | Maturity | Priority | Type | Why |",
                "|---|---|---|---|---|",
            ]
            for candidate in candidates:
                lines.append(
                    f"| {candidate['keyword']} | {candidate.get('maturity', '-')} "
                    f"| {candidate['priority']} "
                    f"| {candidate['type']} | {candidate['reason']} |"
                )
            lines.append("")
    return lines


def _source_health_section(rows):
    """Phase 5, Step 10: distinguish 'no opportunity today' from 'broken source'."""
    lines = [
        "## Source Health",
        "",
        "| Source | Fetched | Accepted as product | Filtered | Status | Note |",
        "|---|---:|---:|---:|---|---|",
    ]
    for row in rows:
        note = row.get("note") or ""
        if row.get("error"):
            note = (note + " | " if note else "") + str(row["error"])
        lines.append(
            f"| {row['label']} | {row['fetched']} | {row['accepted']} | "
            f"{row['filtered']} | {row['status']} | {note.replace('|', '/')} |"
        )
    lines += [
        "",
        "_0 fetched means the collector returned nothing (source problem); items fetched but "
        "0 accepted simply means nothing product-like was found today._",
        "",
    ]
    return lines


def _reddit_section(reddit_signals, clusters, health=None):
    """Phase 7: what Reddit contributed to demand evidence."""
    from analyzers.keyword_quality import MATURITY_AWKWARD, MATURITY_BRAND, keyword_maturity

    themes = recurring_pain(reddit_signals)
    matched = match_themes_to_clusters(themes, clusters)
    unmatched = unmatched_pain(themes, matched.keys())
    spend = [s for s in reddit_signals
             if (s.get("raw_metadata") or {}).get("payment_signal_confidence") == PAYMENT_ACTUAL]

    lines = ["## Reddit Demand Signals", ""]
    if health:
        lines += [
            f"- Status: **{health.get('status')}** · auth: {health.get('auth_status')} · "
            f"requests: {health.get('requests_made')} · posts fetched: "
            f"{health.get('posts_fetched')} · accepted: {health.get('posts_accepted')} · "
            f"comments: {health.get('comments_fetched')}",
            "",
        ]
    if not reddit_signals:
        lines += ["_No Reddit demand signals this run "
                  "(configure REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET to enable)._", ""]
        return lines

    lines += [
        f"- Accepted Reddit signals: **{len(reddit_signals)}** · matched themes: "
        f"**{len(matched)}** · unmatched pain themes: **{len(unmatched)}** · "
        f"actual-spend signals: **{len(spend)}**",
        "",
        "| Theme | Signals | Independent posts | Subreddits | Persistence "
        "| Demand score | Matched opportunity |",
        "|---|---:|---:|---|---|---:|---|",
    ]
    for theme in themes[:12]:
        cluster = matched.get(theme["theme"])
        lines.append(
            f"| {theme['theme']} | {theme['post_count']} | {theme['independent_post_count']} "
            f"| {', '.join(theme['subreddits'][:3])} | {theme['pain_persistence']} "
            f"| {theme['reddit_demand_score']} ({theme['reddit_demand_level']}) "
            f"| {cluster['cluster_label'] if cluster else '-'} |"
        )
    lines.append("")

    seeds = []
    for signal in reddit_signals[:20]:
        for seed in keyword_seeds(signal.get("pain_point") or signal.get("title") or ""):
            if seed in seeds:
                continue
            maturity = keyword_maturity(seed)
            if maturity in (MATURITY_AWKWARD, MATURITY_BRAND):
                continue
            seeds.append(seed)
    if seeds:
        lines += ["**Keyword seeds from Reddit pain (origin `REDDIT_PAIN`)**:", ""]
        for seed in seeds[:10]:
            lines.append(f"- `{seed}` — {keyword_maturity(seed)}")
        lines.append("")

    if unmatched:
        lines += ["**Unmatched Reddit pain signals** (evidence only — never a verdict):", ""]
        for theme in unmatched[:8]:
            sample = theme["signals"][0] if theme["signals"] else {}
            lines.append(
                f"- {str(sample.get('title'))[:70]} — r/{sample.get('subreddit')} · "
                f"{theme['pain_persistence']} · score {theme['reddit_demand_score']} · "
                f"{sample.get('source_url')}"
            )
        lines.append("")
    lines += ["_Reddit evidence never sets BUILD / TEST / WATCH / SKIP._", ""]
    return lines


def _signal_bridge_section(bridge_rows, bridged):
    """Phase 6.2: which PRODUCT_SIGNALs entered the product pipeline."""
    lines = [
        "## Product Signal Bridge",
        "",
        "| Source | Signals seen | Bridged as products | Skipped (evidence-only) |",
        "|---|---:|---:|---:|",
    ]
    for source, row in sorted(bridge_rows.items()):
        lines.append(f"| {source} | {row['signals']} | {row['bridged']} | {row['skipped']} |")
    lines += [
        "",
        f"**{len(bridged)}** bridged product(s) joined the same clustering and "
        "keyword pipeline as the collectors. Demand/pain, revenue-only, exit and "
        "corroboration signals stay evidence-only.",
        "",
    ]
    return lines


def _adapter_health_section(rows):
    """Phase 6: Source Health for the signal adapters."""
    lines = [
        "## Adapter Health",
        "",
        "| Adapter | Tier | Fetched | Status | Signal types | Last error |",
        "|---|---|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('source')} | {row.get('tier', '-')} "
            f"| {row.get('items_fetched', 0)} | {row.get('status')} "
            f"| {', '.join(row.get('signal_types') or [])} "
            f"| {str(row.get('last_error') or '')[:70].replace('|', '/')} |"
        )
    lines += [
        "",
        "_A blocked or empty adapter is reported here and never fails the run. "
        "Sources that were probed and found unusable are listed in the final report._",
        "",
    ]
    return lines


def _executive_summary_section(all_products, suitable, clusters, opportunities,
                               checklist, pool, adapter_rows=None, unmatched=0,
                               bridged=0):
    """Section A (Phase 6): one screen that says what arrived and what survived."""
    adapter_rows = adapter_rows or []
    counts = {}
    for cluster in clusters:
        verdict = cluster.get("verdict", "SKIP")
        counts[verdict] = counts.get(verdict, 0) + 1
    live_sources = sum(1 for row in adapter_rows if row.get("items_fetched"))
    lines = [
        "## Executive Summary",
        "",
        f"- Raw items from the 6 product collectors: **{sum(len(v) for v in all_products.values())}**",
        f"- Accepted products: **{len(suitable)}**",
        f"- Unique opportunities (clusters): **{len(clusters)}**",
        f"- Opportunity entities from the signal engine: **{len(opportunities)}**",
        f"- Unmatched demand/pain signals kept as evidence: **{unmatched}**",
        f"- Product signals bridged into the pipeline: **{bridged}**",
        f"- Adapters with live signal data: **{live_sources}** of {len(adapter_rows)} attempted",
        f"- Verdicts: **{counts.get('BUILD', 0)} BUILD · {counts.get('TEST', 0)} TEST · "
        f"{counts.get('WATCH', 0)} WATCH · {counts.get('SKIP', 0)} SKIP**",
        f"- Keyword pool: **{len(pool)}** candidates · priority checklist: **{len(checklist)}**",
        "",
    ]
    return lines


def _evidence_matrix_section(clusters, limit=5):
    """Section C (Phase 6): which evidence families support each top opportunity."""
    lines = [
        "## Evidence Matrix",
        "",
        "Counts are signals per family (product / pain+demand / revenue+payment / "
        "trend / competition+feature gap / exit / search).",
        "",
        "| Opportunity | Product | Pain | Revenue | Trend | Competition | Exit | Search "
        "| Independent sources | Corroboration |",
        "|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|---|",
    ]
    for cluster in clusters[:limit]:
        entity = cluster.get("_opportunity")
        if not entity:
            continue
        matrix = evidence_matrix(entity)
        lines.append(
            f"| {str(cluster.get('cluster_label'))[:44]} | {matrix['product']} "
            f"| {matrix['pain'] + matrix['demand']} | {matrix['revenue']} "
            f"| {matrix['trend']} | {matrix['competition']} | {matrix['exit']} "
            f"| {matrix['search']} | {entity['independent_source_count']} "
            f"| {entity['corroboration_level']} ({entity['corroboration_score']}) |"
        )
    lines.append("")
    return lines


def _priority_checklist_section(checklist):
    """Section D (Phase 6): tiered, capped at 10-15, no padding."""
    lines = [
        "## Semrush Priority Checklist",
        "",
        f"**{len(checklist)}** strongest terms, A-tier first. No padding; "
        "BRAND and AWKWARD phrases never appear.",
        "",
        "| Keyword | Tier | Maturity | Origin | Opportunity | Reason | Status |",
        "|---|---|:-:|---|---|---|---|",
    ]
    for entry in checklist:
        lines.append(
            f"| {entry['keyword']} | **{entry['tier']}** | {entry['maturity']} "
            f"| {entry['origin']} | {str(entry['cluster_label'])[:30]} "
            f"| {str(entry.get('reason'))[:60]} | {entry['status']} |"
        )
    lines.append("")
    return lines


def _keyword_pool_section(pool):
    """Section E (Phase 6): the expanded pool grouped by opportunity."""
    lines = ["## Expanded Keyword Pool", ""]
    if not pool:
        lines += ["_No usable keyword candidates today._", ""]
        return lines
    counts = tier_counts(pool)
    lines += [f"_{len(pool)} candidates · {counts.get('A', 0)} A · {counts.get('B', 0)} B "
              f"· {counts.get('C', 0)} C_", ""]
    grouped = {}
    for entry in pool:
        grouped.setdefault(entry["cluster_label"], []).append(entry)
    for label, entries in grouped.items():
        lines.append(f"- **{label}** ({len(entries)})")
        for entry in entries:
            lines.append(f"  - `{entry['keyword']}` — {entry['tier']}/{entry['maturity']}"
                         f"/{entry['origin']}")
    lines.append("")
    return lines


def _top_opportunities_section(clusters, limit=5):
    """Daily shortlist: top clusters ordered by verdict, then opportunity score."""
    lines = ["## Top Opportunities Today", ""]
    if not clusters:
        lines += ["_No clusters were produced._", ""]
        return lines

    ranked = sorted(
        clusters,
        key=lambda c: (
            VW.VERDICT_ORDER.get(c.get("verdict"), 9),
            {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(c.get("discovery_quality"), 1),
            -c.get("opportunity_score", 0),
            c["cluster_id"],
        ),
    )
    lines += [
        "| # | Verdict | Cluster | Discovery | Opportunity | Solo Builder | SEO "
        "| Market Gate | Acquire | Substitution |",
        "|---|---|---|:-:|:-:|:-:|:-:|:-:|:-:|---|",
    ]
    for index, cluster in enumerate(ranked[:limit], 1):
        label = str(cluster["cluster_label"]).replace("|", "/")
        seo = (str(cluster.get("seo_score", 0))
               if cluster.get("seo_score_status") != "NOT_CHECKED" else "-")
        lines.append(
            f"| {index} | **{cluster.get('verdict', '-')}** | {label} "
            f"| {cluster.get('discovery_quality', 'MEDIUM')} "
            f"| {cluster.get('opportunity_score', 0)}/100 "
            f"| {cluster['max_solo_builder_score']}/100 | {seo} "
            f"| {cluster.get('market_demand_gate', 'UNKNOWN')} "
            f"| {cluster.get('primary_acquisition_channel', 'UNKNOWN')} "
            f"({cluster.get('acquisition_fit', 'WEAK')}) "
            f"| {cluster.get('substitution_risk', 'MEDIUM')} |"
        )
    lines.append("")

    counts = {}
    for cluster in clusters:
        verdict = cluster.get("verdict", VW.VERDICT_SKIP)
        counts[verdict] = counts.get(verdict, 0) + 1
    lines.append(
        f"_{counts.get('BUILD', 0)} BUILD · {counts.get('TEST', 0)} TEST · "
        f"{counts.get('WATCH', 0)} WATCH · {counts.get('SKIP', 0)} SKIP across "
        f"{len(clusters)} clusters._"
    )
    lines.append("")
    if not counts.get("BUILD", 0):
        lines += [
            "_No opportunity met the BUILD bar today. That is the expected default: "
            "BUILD requires validated demand, monetization evidence, low substitution "
            "risk and low operating cost._",
            "",
        ]
    return lines


def _checklist_section(checklist):
    """Section B: the daily Semrush Check List."""
    lines = [
        "## Semrush Check List",
        "",
        f"**{len(checklist)}** candidate keywords from the highest-ranked clusters. "
        "These are pre-Semrush candidates only: no search volume, KD or SERP data is included.",
        "",
        "Enter the numbers with `python scripts/enrich.py` "
        "(**US Volume**, **Global Volume**, **KD**, **weak sites in SERP (yes/no)**). "
        "Checked and rejected keywords are skipped here.",
        "",
    ]
    if not checklist:
        lines += ["_No candidates were generated._", ""]
        return lines

    lines += [
        "| Keyword | Cluster | Maturity | Priority | Type | SEO status "
        "| Why it is worth checking |",
        "|---|---|---|---|---|---|---|",
    ]
    for entry in checklist:
        lines.append(
            f"| {entry['keyword']} | {entry['cluster_label']} "
            f"| {entry.get('maturity', '-')} | {entry['priority']} "
            f"| {entry['type']} | {entry.get('seo_status', 'NOT_CHECKED')} | {entry['why']} |"
        )
    lines.append("")
    return lines


def generate_indie_report(
    product_hunt_data,
    toolify_data,
    ai_tools_data,
    chrome_extensions_data,
    github_data,
    hn_data,
    enrichment_path=None,
    validation_path=None,
    record_verdicts=False,
    source_errors=None,
    signals=None,
    adapter_rows=None,
    reddit_health=None,
):
    """Generate the full indie opportunity report in Markdown.

    ``enrichment_path`` overrides the manual Semrush store location (tests and
    alternate workspaces); by default ``data/enrichment/keywords.json`` is used.
    ``validation_path`` overrides the evidence/verdict-history store
    (``data/validation/evidence.json``). ``record_verdicts`` persists verdict
    changes; it is off by default so report generation stays side-effect free.
    ``source_errors`` maps a source key to the last collector error (optional).
    ``signals`` is the Phase 6 signal list from the source adapters;
    ``adapter_rows`` is their Source Health telemetry.
    """
    if isinstance(toolify_data, dict):
        toolify_list = toolify_data.get("new", []) + toolify_data.get("trending", [])
    elif isinstance(toolify_data, list):
        toolify_list = toolify_data
    else:
        toolify_list = []

    all_products = {
        "product_hunt": product_hunt_data or [],
        "toolify": toolify_list,
        "ai_tools": ai_tools_data or [],
        "chrome_extensions": chrome_extensions_data or [],
        "github": github_data or [],
        "hackernews": hn_data or [],
    }

    # Phase 6.2: eligible PRODUCT_SIGNALs from the evidence layer join the SAME
    # product pipeline (the evidence layer keeps its own copy).
    bridge_rows = bridge_summary(signals or [])
    bridged = bridged_products(signals or [])
    for product in bridged:
        all_products.setdefault(product["_source"], []).append(product)

    suitable, filtered_out = rank_products(all_products)
    health_rows = source_health(all_products, suitable, filtered_out, errors=source_errors or {})
    top5 = suitable[:5]
    today = timeutil.today_str()
    total_input = sum(len(v) for v in all_products.values())
    unique = len(suitable) + len(filtered_out)
    store = enrichment_store.load_store(enrichment_path)
    clusters = attach_keyword_candidates(analyze_clusters(suitable, today=today))
    attach_seo(clusters, store)
    validation_store_path = (validation_path if validation_path is not None
                             else validation_store.default_path())
    validation = validation_store.load_store(validation_store_path)
    attach_verdict(
        clusters, validation, path=validation_store_path,
        record_history=record_verdicts, today=today,
    )
    opportunities = build_opportunities(signals or [])
    attach_opportunities(clusters, opportunities)
    checklist = build_semrush_checklist(clusters, enrichment=store)
    pool = build_keyword_pool(clusters, enrichment=store)
    priority_checklist = build_priority_checklist(pool)

    sections = [
        f"# Indie Hacker Opportunity Report - {today}",
        "",
        f"Collected **{total_input}** items across 6 sources; **{unique}** unique after "
        f"de-duplication. **{len(suitable)}** passed the solo-builder filter and were scored; "
        f"**{len(filtered_out)}** were excluded. These products were grouped into "
        f"**{len(clusters)}** opportunity clusters.",
        "",
        "Scores are a weighted **Solo Builder Score out of 100** "
        "(Build Ease 20, Self-Service Acquisition 15, Monetization 15, "
        "Low Communication 15, Operating Cost 10, Solo-Builder Fit 15, "
        "Tool-Orchard 10), plus a **+/-5 source-confidence adjustment** used for ranking.",
        "",
    ]

    # --- SECTION A: executive summary (Phase 6) ---
    sections += ["---", ""]
    sections += _executive_summary_section(
        all_products, suitable, clusters, opportunities,
        priority_checklist, pool, adapter_rows,
        unmatched=len(unmatched_signals(signals or [])),
        bridged=len(bridged),
    )
    if bridge_rows:
        sections += ["---", ""]
        sections += _signal_bridge_section(bridge_rows, bridged)

    reddit_signals = [s for s in (signals or []) if s.get("source") == "reddit"]
    if reddit_signals or reddit_health:
        sections += ["---", ""]
        sections += _reddit_section(reddit_signals, clusters, reddit_health)

    # --- SECTION A: opportunity clusters ---
    sections += ["---", ""]
    sections += _top_opportunities_section(clusters)

    sections += ["---", ""]
    sections += _cluster_section(clusters)

    # --- SECTION B: Semrush Check List ---
    sections += ["---", ""]
    sections += _checklist_section(checklist)

    # --- Phase 6 sections: evidence matrix, tiered checklist, keyword pool ---
    sections += ["---", ""]
    sections += _evidence_matrix_section(clusters)
    if priority_checklist:
        sections += ["---", ""]
        sections += _priority_checklist_section(priority_checklist)
    sections += ["---", ""]
    sections += _keyword_pool_section(pool)

    # --- Source health (input diagnostics) ---
    sections += ["---", ""]
    sections += _source_health_section(health_rows)
    if adapter_rows:
        sections += ["---", ""]
        sections += _adapter_health_section(adapter_rows)

    # --- SECTION C: individual product evidence ---
    sections += ["---", "", "## Individual Product Evidence", ""]
    sections += ["### Filtered Out", ""]
    if filtered_out:
        sections.append("| Product | Source | Reason |")
        sections.append("|---------|--------|--------|")
        for product in filtered_out:
            name = (product.get("name") or product.get("title") or "Unknown").replace("|", "/")
            src = product.get("_source", "?")
            reason = str(product.get("filter_reason", "N/A")).replace("|", "/")
            sections.append(f"| {name} | {src} | {reason} |")
    else:
        sections.append("_No products were filtered out._")
    sections.append("")

    # --- Section 2: Solo Builder Score table ---
    sections += [
        "---", "",
        "## Solo Builder Score - All Suitable Products", "",
        "Values are `points/max` per dimension. `Score` = weighted total (0-100) "
        "plus the source-confidence adjustment.",
        "",
    ]
    sections += _score_table(suitable)
    sections.append("")

    # --- Section 3: Reasons ---
    sections += ["---", ""]
    sections += _reasons_section(suitable)

    # --- Section 4: Top 5 Deep Dive ---
    sections += ["---", "", "## Top 5 Deep Dive", ""]
    for rank, product in enumerate(top5, 1):
        sections.append(deep_analyze_product(product, rank))

    return "\n".join(sections)
