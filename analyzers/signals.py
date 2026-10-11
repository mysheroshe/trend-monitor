"""Common signal taxonomy for the multi-source opportunity engine (Phase 6).

Every incoming item - from a product feed, a pain discussion, a revenue
directory or an exit marketplace - is normalized into a signal record. Sources
contribute the evidence type they are naturally good at; nothing here changes
the Phase 1-5 scoring, thresholds or verdict logic.

Deterministic, offline, no LLM, no paid API.
"""

import re

from analyzers.text_utils import normalize_url

# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------

PRODUCT_SIGNAL = "PRODUCT_SIGNAL"
PAIN_SIGNAL = "PAIN_SIGNAL"
DEMAND_SIGNAL = "DEMAND_SIGNAL"
PAYMENT_SIGNAL = "PAYMENT_SIGNAL"
REVENUE_SIGNAL = "REVENUE_SIGNAL"
TREND_SIGNAL = "TREND_SIGNAL"
COMPETITION_SIGNAL = "COMPETITION_SIGNAL"
FEATURE_GAP_SIGNAL = "FEATURE_GAP_SIGNAL"
EXIT_SIGNAL = "EXIT_SIGNAL"
SEARCH_SIGNAL = "SEARCH_SIGNAL"
CORROBORATION_SIGNAL = "CORROBORATION_SIGNAL"

SIGNAL_TYPES = (
    PRODUCT_SIGNAL, PAIN_SIGNAL, DEMAND_SIGNAL, PAYMENT_SIGNAL, REVENUE_SIGNAL,
    TREND_SIGNAL, COMPETITION_SIGNAL, FEATURE_GAP_SIGNAL, EXIT_SIGNAL,
    SEARCH_SIGNAL, CORROBORATION_SIGNAL,
)

# Evidence families used for corroboration (signal type -> family).
SIGNAL_FAMILY = {
    PRODUCT_SIGNAL: "product",
    PAIN_SIGNAL: "demand",
    DEMAND_SIGNAL: "demand",
    FEATURE_GAP_SIGNAL: "demand",
    PAYMENT_SIGNAL: "money",
    REVENUE_SIGNAL: "money",
    TREND_SIGNAL: "trend",
    COMPETITION_SIGNAL: "competition",
    EXIT_SIGNAL: "exit",
    SEARCH_SIGNAL: "search",
    CORROBORATION_SIGNAL: "corroboration",
}

EVIDENCE_STRENGTH_HIGH = "HIGH"
EVIDENCE_STRENGTH_MEDIUM = "MEDIUM"
EVIDENCE_STRENGTH_LOW = "LOW"

REVENUE_VERIFIED = "VERIFIED"
REVENUE_PUBLIC_SELF_REPORTED = "PUBLIC_SELF_REPORTED"
REVENUE_INFERRED = "INFERRED"
REVENUE_UNKNOWN = "UNKNOWN"

EXIT_HEALTHY = "HEALTHY_EXIT"
EXIT_DISTRESSED = "DISTRESSED_OR_UNCLEAR"
EXIT_UNKNOWN = "UNKNOWN"

# ---------------------------------------------------------------------------
# Pain / demand phrase patterns (Step 8, 9, 11, 13)
# ---------------------------------------------------------------------------

_PAIN_PATTERNS = [
    ("i wish there was", PAIN_SIGNAL),
    ("wish there was", PAIN_SIGNAL),
    ("someone should build", PAIN_SIGNAL),
    ("is there a tool", DEMAND_SIGNAL),
    ("is there an app", DEMAND_SIGNAL),
    ("any tool for", DEMAND_SIGNAL),
    ("looking for software", DEMAND_SIGNAL),
    ("looking for a tool", DEMAND_SIGNAL),
    ("does anyone know an app", DEMAND_SIGNAL),
    ("i hate that", PAIN_SIGNAL),
    ("alternative to", COMPETITION_SIGNAL),
    ("too expensive", PAIN_SIGNAL),
    ("missing feature", FEATURE_GAP_SIGNAL),
    ("no api", FEATURE_GAP_SIGNAL),
    ("cannot export", FEATURE_GAP_SIGNAL),
    ("can't export", FEATURE_GAP_SIGNAL),
    ("no bulk", FEATURE_GAP_SIGNAL),
    ("manual process", PAIN_SIGNAL),
    ("takes too long", PAIN_SIGNAL),
    ("i currently do this in excel", PAIN_SIGNAL),
    ("i built my own workaround", PAIN_SIGNAL),
    ("workaround", PAIN_SIGNAL),
    ("slow", FEATURE_GAP_SIGNAL),
    ("no mobile support", FEATURE_GAP_SIGNAL),
    ("bad integration", FEATURE_GAP_SIGNAL),
]

# ---------------------------------------------------------------------------
# Signal records
# ---------------------------------------------------------------------------

_SIGNAL_FIELDS = (
    "source", "source_url", "title", "description", "detected_at", "signal_type",
    "product_name", "domain", "category", "function", "target_user", "pain_point",
    "pricing_or_revenue", "growth_metric", "engagement_metric", "evidence_strength",
    "raw_metadata", "canonical_url", "underlying_source_id", "aggregator_source",
    "original_source", "revenue_confidence", "exit_signal_type", "subreddit",
    "engagement", "requested_feature", "complained_about",
)


def make_signal(source, signal_type, title, description="", source_url="", **fields):
    """Build a normalized signal record (unset fields stay ``None``)."""
    if signal_type not in SIGNAL_TYPES:
        raise ValueError(f"unknown signal_type: {signal_type}")
    signal = {field: None for field in _SIGNAL_FIELDS}
    signal.update({
        "source": source,
        "signal_type": signal_type,
        "title": title or "",
        "description": description or "",
        "source_url": source_url or "",
        "canonical_url": canonical_url(source_url),
        "evidence_strength": EVIDENCE_STRENGTH_MEDIUM,
        "raw_metadata": {},
    })
    for key, value in fields.items():
        if key in signal:
            signal[key] = value
        else:
            signal["raw_metadata"][key] = value
    if not signal["underlying_source_id"]:
        signal["underlying_source_id"] = signal["canonical_url"] or f"{source}:{title}"
    if not signal["original_source"]:
        signal["original_source"] = source
    return signal


def canonical_url(url):
    """Comparable URL for lineage/dedup (no scheme, no fragment, no trailing /)."""
    return normalize_url(url)


def signal_family(signal_type):
    return SIGNAL_FAMILY.get(signal_type, "other")


def detect_pain_patterns(text):
    """Return (signal_types, matched_phrases) for a piece of text."""
    lowered = (text or "").lower()
    types, matched = [], []
    for phrase, signal_type in _PAIN_PATTERNS:
        if phrase in lowered:
            matched.append(phrase)
            if signal_type not in types:
                types.append(signal_type)
    return types, matched


def revenue_confidence(source, self_reported=True, verified_marker=False):
    """Never label self-reported revenue as verified."""
    text = f"{source} {'verified' if verified_marker else ''}".lower()
    if verified_marker and "verified" in text:
        return REVENUE_VERIFIED
    if self_reported:
        return REVENUE_PUBLIC_SELF_REPORTED
    if source:
        return REVENUE_INFERRED
    return REVENUE_UNKNOWN


_DISTRESSED_MARKERS = ["distressed", "shutting down", "no revenue", "declining",
                       "for sale urgently", "selling due", "burned out", "abandoned"]
_HEALTHY_MARKERS = ["profitable", "growing", "steady mrr", "healthy", "acquired"]


def exit_signal_type(text):
    """Conservative classification of a marketplace listing."""
    lowered = (text or "").lower()
    if any(marker in lowered for marker in _DISTRESSED_MARKERS):
        return EXIT_DISTRESSED
    if any(marker in lowered for marker in _HEALTHY_MARKERS):
        return EXIT_HEALTHY
    return EXIT_UNKNOWN


def parse_money(text):
    """Extract a numeric money amount from text ('$4.2k MRR' -> 4200.0)."""
    match = re.search(r"\$\s?([\d.,]+)\s?([km])?", (text or "").lower())
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return value * {"k": 1_000, "m": 1_000_000}.get(match.group(2) or "", 1)
