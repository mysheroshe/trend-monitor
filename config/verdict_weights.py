"""Constants for the Phase 4 final decision layer (BUILD/TEST/WATCH/SKIP).

No Semrush/Ahrefs API, no paid datasets, no embeddings, no database, and no
mandatory LLM. The deterministic pipeline must work fully offline.
"""

# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------

VERDICT_BUILD = "BUILD"
VERDICT_TEST = "TEST"
VERDICT_WATCH = "WATCH"
VERDICT_SKIP = "SKIP"

# Reporting / sorting order (BUILD first).
VERDICT_ORDER = {
    VERDICT_BUILD: 0,
    VERDICT_TEST: 1,
    VERDICT_WATCH: 2,
    VERDICT_SKIP: 3,
}

# ---------------------------------------------------------------------------
# Opportunity Score (supporting metric only - hard gates are separate)
# ---------------------------------------------------------------------------

OPPORTUNITY_MAX = 100

WEIGHTS = {
    "solo_builder_fit": 20,
    "market_demand": 20,
    "opportunity_evidence": 15,
    "competition_accessibility": 10,
    "monetization_confidence": 10,
    "acquisition_fit": 10,
    "operating_cost": 5,
    "tool_orchard": 5,
    "substitution_risk": 5,
}

# Points per classified value.
MONETIZATION_POINTS = {"HIGH": 10, "MEDIUM": 6, "LOW": 2, "UNKNOWN": 0}
ACQUISITION_POINTS = {"STRONG": 10, "MEDIUM": 6, "WEAK": 2, "UNKNOWN": 0}
COST_POINTS = {"LOW": 5, "MEDIUM": 3, "HIGH": 1, "SEVERE": 0}
SUBSTITUTION_POINTS = {"LOW": 5, "MEDIUM": 3, "HIGH": 1, "SEVERE": 0}

# Competition accessibility: best viable keyword's KD -> points.
COMPETITION_KD_POINTS = [(14, 10), (29, 8), (39, 6), (49, 4)]
COMPETITION_KD_FALLBACK = 2
COMPETITION_WEAK_SERP_BONUS = 1          # weak_serp = true
COMPETITION_MULTI_WEAK_BONUS = 2         # weak_serp_count >= 2

# Opportunity evidence: distinct positive evidence types.
EVIDENCE_POINTS_PER_POSITIVE_TYPE = 5
EVIDENCE_NEGATIVE_PENALTY = 5
EVIDENCE_MAX_POSITIVE_TYPES = 3          # -> 15 points

# Types that count as demand evidence when SEO data is missing.
STRONG_NON_SEO_EVIDENCE_TYPES = ("COMMUNITY_PAIN", "PAYMENT_SIGNAL", "TREND_SIGNAL")
STRONG_NON_SEO_MIN_EVIDENCE = 2

# ---------------------------------------------------------------------------
# BUILD gating
# ---------------------------------------------------------------------------

BUILD_MIN_SOLO_BUILDER = 75
BUILD_BLOCK_SOLO_BUILDER = 70        # below this BUILD is never allowed
BUILD_REQUIRED_SUBSTITUTION = ("LOW", "MEDIUM")
BUILD_REQUIRED_COST_RISK = ("LOW", "MEDIUM")
BUILD_REQUIRED_MONETIZATION = ("HIGH", "MEDIUM")
BUILD_REQUIRED_ACQUISITION_FIT = ("STRONG", "MEDIUM")

# BUILD also needs either high inferred monetization confidence or at least one
# human-verified payment/competitor signal.
BUILD_TRUSTED_EVIDENCE_TYPES = ("PAYMENT_SIGNAL", "COMPETITOR")

# ---------------------------------------------------------------------------
# SKIP / WATCH thresholds
# ---------------------------------------------------------------------------

SKIP_BELOW_SOLO_BUILDER = 50
WATCH_BELOW_SOLO_BUILDER = 70
WATCH_MIN_DAYS_SEEN = 2

# ---------------------------------------------------------------------------
# Substitution risk levels
# ---------------------------------------------------------------------------

SUBSTITUTION_LOW = "LOW"
SUBSTITUTION_MEDIUM = "MEDIUM"
SUBSTITUTION_HIGH = "HIGH"
SUBSTITUTION_SEVERE = "SEVERE"

SUBSTITUTION_LEVELS = (
    SUBSTITUTION_LOW, SUBSTITUTION_MEDIUM, SUBSTITUTION_HIGH, SUBSTITUTION_SEVERE,
)

# ---------------------------------------------------------------------------
# Acquisition
# ---------------------------------------------------------------------------

CHANNEL_SEO = "SEO"
CHANNEL_SOCIAL = "SOCIAL"
CHANNEL_COMMUNITY = "COMMUNITY"
CHANNEL_PLATFORM = "PLATFORM_MARKETPLACE"
CHANNEL_DIRECT_SALES = "DIRECT_SALES"
CHANNEL_PAID_ADS = "PAID_ADS"
CHANNEL_MIXED = "MIXED"
CHANNEL_UNKNOWN = "UNKNOWN"

CHANNELS = (
    CHANNEL_SEO, CHANNEL_SOCIAL, CHANNEL_COMMUNITY, CHANNEL_PLATFORM,
    CHANNEL_DIRECT_SALES, CHANNEL_PAID_ADS, CHANNEL_MIXED, CHANNEL_UNKNOWN,
)

ACQUISITION_FIT_STRONG = "STRONG"
ACQUISITION_FIT_MEDIUM = "MEDIUM"
ACQUISITION_FIT_WEAK = "WEAK"

# ---------------------------------------------------------------------------
# Monetization
# ---------------------------------------------------------------------------

MONETIZATION_MODELS = (
    "one-time payment", "credits", "subscription", "ads", "affiliate",
    "freemium", "lead generation", "marketplace", "enterprise sales",
)

MONETIZATION_CONFIDENCE_LEVELS = ("HIGH", "MEDIUM", "LOW", "UNKNOWN")

# ---------------------------------------------------------------------------
# Operating cost risk
# ---------------------------------------------------------------------------

COST_RISK_LOW = "LOW"
COST_RISK_MEDIUM = "MEDIUM"
COST_RISK_HIGH = "HIGH"
COST_RISK_SEVERE = "SEVERE"
