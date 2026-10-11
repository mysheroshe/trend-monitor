"""Central weights and constants for the Solo Builder Score (Phase 1).

Every numeric knob of the rule-based scoring model lives here so that
``analyzers/indie_analyzer.py`` contains rules, not magic numbers.

The model is deliberately deterministic: no LLM calls, no embeddings,
no external APIs, no dollar estimates.
"""

# ---------------------------------------------------------------------------
# Dimension weights — the weighted Solo Builder Score is out of 100 points.
# ---------------------------------------------------------------------------

# Each dimension rule returns a raw sub-score on a 0..RAW_MAX scale which is
# rescaled onto its weight below. Keeping the raw scale small keeps the rule
# functions readable while the weights stay centralised here.
RAW_MAX = 5

WEIGHTS = {
    "build_ease": 20,                # A. Build Ease
    "self_service_acquisition": 15,  # B. Self-Service Acquisition Fit
    "monetization": 15,              # C. Monetization Potential
    "low_communication": 15,         # D. Low Communication / Sales Burden
    "operating_cost": 10,            # E. Operating Cost / Maintenance
    "solo_builder_fit": 15,          # F. Solo-Builder Fit
    "tool_orchard": 10,              # G. Tool-Orchard Expansion Potential
}

TOTAL_MAX = sum(WEIGHTS.values())  # == 100

# Human-readable labels, used by the Markdown and HTML report generators.
DIMENSION_LABELS = {
    "build_ease": "Build Ease",
    "self_service_acquisition": "Self-Service Acquisition",
    "monetization": "Monetization",
    "low_communication": "Low Communication Burden",
    "operating_cost": "Operating Cost",
    "solo_builder_fit": "Solo-Builder Fit",
    "tool_orchard": "Tool-Orchard Potential",
}

# ---------------------------------------------------------------------------
# Source confidence / relevance
# ---------------------------------------------------------------------------
#
# Source confidence is a *separate* signal from product quality. It may only
# nudge the ranking by MAX_SOURCE_ADJUSTMENT points and can never rescue a
# weak product.
#
# Values are on a 0..1 scale; 0.5 means "neutral".
SOURCE_CONFIDENCE = {
    "toolify": 1.0,             # product traffic/growth signals
    "product_hunt": 0.8,        # real launches
    "ai_tools": 0.8,            # real (AI) tools
    "chrome_extensions": 0.6,   # real products, weak signals
    "github": 0.4,              # mostly libraries
    "hackernews": 0.2,          # news, weak product relevance
}

SOURCE_CONFIDENCE_LABELS = {
    "toolify": "High",
    "product_hunt": "Medium–High",
    "ai_tools": "Medium–High",
    "chrome_extensions": "Medium",
    "github": "Low–Medium",
    "hackernews": "Low",
}

DEFAULT_SOURCE_CONFIDENCE = 0.5
DEFAULT_SOURCE_CONFIDENCE_LABEL = "Unknown"

# Maximum ranking adjustment (in points) that source confidence may apply.
# toolify -> +5, hackernews -> -3, etc.
MAX_SOURCE_ADJUSTMENT = 5

# ---------------------------------------------------------------------------
# Reporting bands for the 0..100 Solo Builder Score (colour coding only).
# ---------------------------------------------------------------------------

SCORE_BANDS = {
    "high": 70,
    "mid": 50,
}

# Maximum number of short reasons attached to a scored product.
MAX_REASONS = 5
MIN_REASONS = 2
