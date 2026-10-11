"""Structural brand / product-name detection (Phase 5, Step 1).

Product names must not leak into SEO keyword candidates ("monica all one
summarizer"). The primary signal is **structural** - case shape, digits, colon-
separated leading names, single-word names, and tokens the vocabulary does not
recognise - with only a small stoplist for very common platform brands.

Deliberately NOT used: "appears in only one member" alone, because real
use-case modifiers ("stencil", "sleeve") also appear in a single member and must
stay.
"""

import re

from analyzers.keyword_quality import vocabulary_tokens
from analyzers.text_utils import tokenize

# Small stoplist: only very common platform / brand names.
KNOWN_BRANDS = {
    "monica", "sider", "harpa", "gptzero", "chatgpt", "openai", "anthropic",
    "claude", "gemini", "deepseek", "grok", "copilot", "midjourney", "notion",
    "canva", "adobe", "zapier", "shopify", "hubspot", "salesforce", "grammarly",
    "jasper", "perplexity", "cursor", "figma", "airtable", "slack", "stripe",
    "vercel", "supabase", "windsurf", "devin", "perplexity",
}

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*")
_ACRONYM_RE = re.compile(r"^[A-Z][A-Z0-9]{2,}$")            # HARPA, GPT, IRC
_CAMEL_RE = re.compile(r"^[a-z]+[A-Z]|^[A-Z][a-z]+[A-Z]")   # TattooGenie, GPTZero
_DIGIT_MIX_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]+$")


def name_tokens(name):
    """Tokens of a product name, preserving original case."""
    return [token for token in _TOKEN_RE.findall(name or "") if token]


def _is_brand_token(raw, vocabulary):
    low = raw.lower()
    if low in vocabulary:
        return False
    if low in KNOWN_BRANDS:
        return True
    if _CAMEL_RE.match(raw):
        return True
    if _ACRONYM_RE.match(raw):
        return True
    if len(raw) >= 4 and _DIGIT_MIX_RE.match(raw):
        return True
    return False


def brand_tokens(name, vocabulary=None):
    """Brand-like tokens of one product name (lowercased, de-duplicated)."""
    vocab = vocabulary if vocabulary is not None else vocabulary_tokens()
    tokens = name_tokens(name)
    found = []

    for token in tokens:
        if _is_brand_token(token, vocab) and token.lower() not in found:
            found.append(token.lower())

    # A single-word name that is not vocabulary is a brand ("Agibot").
    if len(tokens) == 1:
        low = tokens[0].lower()
        if low not in vocab and low not in found:
            found.append(low)

    # "Monica: ..." / "Sider: Chat with all AI" - a leading name followed by a
    # colon, or by known vocabulary, is the product's brand.
    if len(tokens) >= 2:
        first = tokens[0]
        low = first.lower()
        if low not in vocab and low not in found:
            head = (name or "").split(first, 1)[-1].lstrip()
            if head.startswith((":", "|", "-", "–")):
                found.append(low)
            elif tokens[1].lower() in vocab and len(tokens) >= 3:
                found.append(low)

    return found


def cluster_brand_tokens(cluster):
    """Union of the brand tokens of every member name (+ a safe uniqueness pass)."""
    vocab = vocabulary_tokens()
    brands = set()
    names = []
    for member in cluster.get("members") or []:
        name = member.get("name") or member.get("title") or ""
        names.append(name)
        brands.update(brand_tokens(name, vocab))

    # A proper-noun-looking token unique to one member is brand-like, but only
    # when it is not vocabulary and never appears anywhere else in the cluster.
    if len(names) >= 2:
        counts = {}
        for name in names:
            for token in set(token.lower() for token in name_tokens(name)):
                counts[token] = counts.get(token, 0) + 1
        for token, count in counts.items():
            if count != 1 or token in vocab or len(token) < 5 or not token.isalpha():
                continue
            if token in KNOWN_BRANDS:
                brands.add(token)

    return sorted(brands)


def strip_brand_tokens(subject, brands):
    """Remove brand tokens from a derived subject phrase."""
    blocked = {token.lower() for token in (brands or ())}
    kept = [token for token in tokenize(subject) if token not in blocked]
    return " ".join(kept)
