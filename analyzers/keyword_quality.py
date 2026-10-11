"""Deterministic keyword-quality gate (Phase 3) + maturity model (Phase 5).

Phase 3 removed generic category phrases ("checker tool", "code editor") and
product-name-derived noise. Phase 5 adds:

  * a **category anchor** requirement - every candidate needs a meaningful
    domain/category anchor *and* a functional anchor;
  * a **maturity** label: NICHE / BROAD / BRAND / AWKWARD, so the checklist can
    prefer niche, non-brand, tool-intent phrases.
"""

from analyzers.clustering import DOMAIN_FAMILIES, FUNCTION_FAMILIES
from analyzers.text_utils import tokenize

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

# Modifiers and connective words that never identify a niche on their own.
MODIFIER_TOKENS = {
    "free", "online", "ai", "best", "top", "new", "pro", "plus", "easy",
    "simple", "fast", "quick", "instant", "smart", "auto", "automatic",
    "how", "to", "what", "is", "the", "a", "an", "for", "from", "without",
    "with", "and", "or", "of", "in", "on", "my", "your",
}

# Broad domains / category nouns that do not identify a niche by themselves.
_GENERIC_DOMAIN_TOKENS = {
    "code", "text", "data", "website", "web", "business", "productivity",
    "saas", "app", "apps", "tool", "tools", "software", "platform",
    "service", "services", "solution", "solutions", "utility", "utilities",
    "assistant", "site", "general", "misc", "product", "products", "thing",
    "stuff", "idea", "ideas",
}

# Filler head nouns: a phrase ending in one of these is a generic category
# ("ai tool", "checker tool") rather than a tool search ("ai detector").
FILLER_NOUNS = {
    "tool", "tools", "app", "apps", "software", "platform", "platforms",
    "service", "services", "solution", "solutions", "utility", "utilities",
    "assistant", "site", "website", "web", "saas", "product", "products",
    "thing", "stuff",
}

_FUNCTION_TOKENS = set()
for _family in FUNCTION_FAMILIES:
    _FUNCTION_TOKENS.add(_family["key"])
    _FUNCTION_TOKENS.add(_family["label"].lower())
    _FUNCTION_TOKENS.update(word.lower() for word in _family["head_words"])
    _FUNCTION_TOKENS.update(word.lower() for word in _family["keywords"])

_DOMAIN_TOKENS = set()
for _domain in DOMAIN_FAMILIES:
    _DOMAIN_TOKENS.add(_domain["key"])
    _DOMAIN_TOKENS.update(word.lower() for word in _domain["keywords"])

# Tokens that are too broad to prove a niche on their own.
BROAD_TOKENS = {
    "ai", "video", "image", "photo", "picture", "audio", "music", "code",
    "coding", "text", "data", "seo", "email", "website", "social", "app",
    "tool", "platform", "content", "assistant",
}

# Domains that cannot carry candidates on their own at all.
GENERIC_DOMAINS = {"code", "text", "data", "website"}

# Domains whose phrases are broad but still legitimate benchmarks.
BROAD_DOMAINS = {"audio", "video", "code", "text", "data", "website", "image", "social"}

# Broad categories that may still be paired with a function when no specific
# domain is available (e.g. "ai detector", "video summarizer").
INFERRED_CATEGORIES = {
    "ai": ["ai", "gpt", "llm", "chatgpt", "claude", "gemini", "copilot", "agent"],
    "video": ["video", "youtube", "clip", "reel"],
    "image": ["image", "photo", "picture", "art", "logo", "graphic"],
    "audio": ["audio", "music", "song", "voice", "podcast"],
    "pdf": ["pdf"],
    "excel": ["excel", "spreadsheet", "csv"],
    "seo": ["seo", "keyword", "serp", "backlink"],
    "resume": ["resume", "cv"],
    "prompt": ["prompt"],
}

GENERIC_TOKENS = MODIFIER_TOKENS | _GENERIC_DOMAIN_TOKENS | _FUNCTION_TOKENS


def vocabulary_tokens():
    """Every token the system recognises as domain/function/category language."""
    return _DOMAIN_TOKENS | _FUNCTION_TOKENS | MODIFIER_TOKENS | _GENERIC_DOMAIN_TOKENS


def domain_tokens():
    return set(_DOMAIN_TOKENS)


def function_tokens():
    return set(_FUNCTION_TOKENS)


def broad_tokens():
    return set(BROAD_TOKENS)


def inferred_categories():
    return dict(INFERRED_CATEGORIES)


# ---------------------------------------------------------------------------
# Anchors
# ---------------------------------------------------------------------------

def has_category_anchor(keyword):
    """True when the phrase contains a real domain / category anchor."""
    tokens = set(tokenize(keyword))
    return bool(tokens & (_DOMAIN_TOKENS | {"ai"}))


def has_function_anchor(keyword):
    """True when the phrase contains a functional head noun."""
    return bool(set(tokenize(keyword)) & _FUNCTION_TOKENS)


def has_specific_anchor(keyword):
    """True when the anchor is a specific (non-broad) domain term."""
    tokens = set(tokenize(keyword))
    return bool(tokens & (_DOMAIN_TOKENS - BROAD_TOKENS))


# ---------------------------------------------------------------------------
# Quality rules
# ---------------------------------------------------------------------------

_ARTIFACT_BIGRAMS = [
    "all one", "one stop", "all in", "in one", "one click", "me finder",
    "me checker", "me analyzer", "me generator", "one summarizer",
]


def is_generic_phrase(keyword):
    """True for generic category phrases that cannot reveal an opportunity.

    Generic when the phrase ends in a filler noun ("checker tool", "ai tool")
    or when it carries no real category anchor ("free checker"), or when its
    only anchor is a generic domain ("code editor").
    """
    tokens = tokenize(keyword)
    if not tokens:
        return True
    if any(token in FILLER_NOUNS for token in tokens):
        return True
    usable_anchors = (_DOMAIN_TOKENS - GENERIC_DOMAINS) | {"ai"}
    return not (set(tokens) & usable_anchors)


def is_awkward_phrase(keyword):
    """True for malformed, repetitive or concatenation-artifact phrases."""
    tokens = tokenize(keyword)
    if not tokens:
        return True
    if len(tokens) > 6:
        return True
    if len(set(tokens)) != len(tokens):
        return True                      # repeated token ("ai ai video generator")
    if any(token.isdigit() for token in tokens):
        return True                      # "composer 2 ..."
    if any(len(token) > 20 for token in tokens):
        return True
    if tokens[0] in {"for", "and", "or", "of", "to", "with", "me"}:
        return True
    if len({"free", "online", "ai", "best"} & set(tokens)) > 1:
        return True                      # stacked modifiers
    lowered = " ".join(tokens)
    if any(bigram in lowered for bigram in _ARTIFACT_BIGRAMS):
        return True                      # "monica all one summarizer"
    # a dangling one/two-letter token before a function noun is an artifact
    # ("shippedit me analyzer"); real modifiers such as "ai" are fine
    if (len(tokens) >= 2 and tokens[0] not in MODIFIER_TOKENS
            and len(tokens[0]) <= 2 and tokens[1] in _FUNCTION_TOKENS):
        return True
    return False


def member_derived_allowed(cluster):
    """Whether per-product ('member-derived') keywords may be generated.

    A single product with no meaningful domain anchor is a product name, not a
    search intent ("WA WorkFlow" -> "wa workflow enhancer"). Clusters with two
    or more members, or a specific domain, are allowed.
    """
    if cluster.get("member_count", 0) >= 2:
        return True
    domain = cluster.get("domain")
    return bool(domain) and domain not in GENERIC_DOMAINS


def keyword_quality(keyword, cluster):
    """Classify a candidate keyword: OK / GENERIC / AWKWARD."""
    if is_awkward_phrase(keyword):
        return "AWKWARD"
    if is_generic_phrase(keyword):
        return "GENERIC"
    return "OK"


def passes_quality(keyword, cluster):
    """True when the keyword is worth showing to the user."""
    return keyword_quality(keyword, cluster) == "OK"


def is_domain_specific(keyword, cluster):
    """True when the keyword carries a specific (non-broad) subject."""
    tokens = set(tokenize(keyword)) - GENERIC_TOKENS
    return bool(tokens) and not tokens <= BROAD_TOKENS


# ---------------------------------------------------------------------------
# Phase 5: maturity
# ---------------------------------------------------------------------------

MATURITY_NICHE = "NICHE"
MATURITY_BROAD = "BROAD"
MATURITY_BRAND = "BRAND"
MATURITY_AWKWARD = "AWKWARD"

MATURITY_LEVELS = (MATURITY_NICHE, MATURITY_BROAD, MATURITY_BRAND, MATURITY_AWKWARD)
CHECKLIST_MATURITY = (MATURITY_NICHE, MATURITY_BROAD)


def keyword_maturity(keyword, cluster=None, brand_tokens=()):
    """NICHE / BROAD / BRAND / AWKWARD for one candidate phrase."""
    tokens = set(tokenize(keyword))
    if is_awkward_phrase(keyword):
        return MATURITY_AWKWARD
    if tokens & {token.lower() for token in (brand_tokens or ())}:
        return MATURITY_BRAND
    if is_generic_phrase(keyword):
        return MATURITY_AWKWARD
    if not has_category_anchor(keyword) or not has_function_anchor(keyword):
        # without both anchors the phrase is not a tool search
        return MATURITY_AWKWARD
    if has_specific_anchor(keyword):
        return MATURITY_NICHE
    extra = tokens - GENERIC_TOKENS - _DOMAIN_TOKENS
    if extra:
        return MATURITY_NICHE
    return MATURITY_BROAD
