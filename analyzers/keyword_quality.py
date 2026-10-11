"""Deterministic keyword-quality gate (Phase 3, Step 3).

Removes candidates that are technically valid but useless as an opportunity
signal: generic category phrases ("checker tool", "code editor", "ai tool"),
detached function nouns, obvious brand/name queries from single products, and
awkward generated phrases.

The gate deliberately keeps useful broad head terms when they genuinely
describe the cluster ("prompt generator", "tattoo generator").
"""

from analyzers.clustering import FUNCTION_FAMILIES
from analyzers.text_utils import tokenize

# Modifiers and connective words that never identify a niche on their own.
_MODIFIER_TOKENS = {
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


def _function_tokens():
    tokens = set()
    for family in FUNCTION_FAMILIES:
        tokens.add(family["key"])
        tokens.add(family["label"].lower())
        tokens.update(word.lower() for word in family["head_words"])
        tokens.update(word.lower() for word in family["keywords"])
    return tokens


GENERIC_TOKENS = _MODIFIER_TOKENS | _GENERIC_DOMAIN_TOKENS | _function_tokens()

# Domains too broad to anchor a keyword without a specific subject.
BROAD_DOMAINS = {"audio", "video", "code", "text", "data", "website", "image", "social"}

# Domains that cannot carry candidates on their own at all.
GENERIC_DOMAINS = {"code", "text", "data", "website"}


def is_generic_phrase(keyword):
    """True when every token is a modifier, category noun or function word."""
    tokens = tokenize(keyword)
    if not tokens:
        return True
    return all(token in GENERIC_TOKENS for token in tokens)


def is_awkward_phrase(keyword):
    """True for malformed or repetitive generated phrases."""
    tokens = tokenize(keyword)
    if not tokens:
        return True
    if len(tokens) > 6:
        return True
    if len(set(tokens)) != len(tokens):
        return True                      # repeated token
    if any(token.isdigit() for token in tokens):
        return True                      # "composer 2 ..."
    if any(len(token) > 20 for token in tokens):
        return True
    if tokens[0] in {"for", "and", "or", "of", "to", "with"}:
        return True
    if len({"free", "online", "ai", "best"} & set(tokens)) > 1:
        return True                      # stacked modifiers
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
    """Classify a candidate keyword: OK / GENERIC / AWKWARD.

    Obvious brand/name queries are handled upstream by
    ``member_derived_allowed`` (a single product with no domain anchor is not
    treated as a search intent); finer brand detection stays heuristic.
    """
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
    return bool(tokens) and not tokens <= BROAD_DOMAINS
