"""Constants for the Phase 3 SEO Opportunity Score and market demand gate.

Everything here is deterministic. The score uses ONLY manually enriched
Semrush data; missing values are never invented. There are no API calls, no
LLM, no embeddings and no database in Phase 3.
"""

# ---------------------------------------------------------------------------
# SEO Opportunity Score dimensions (total = 100)
# ---------------------------------------------------------------------------

DEMAND_MAX = 35          # A. Search demand (US volume)
KD_MAX = 30              # B. Keyword difficulty
WEAK_SERP_MAX = 20       # C. Weak-SERP evidence
LONGTAIL_MAX = 15        # D. Long-tail depth / multiple valid keywords

SEO_SCORE_MAX = 100

# A keyword's own score covers demand + KD + weak SERP (85). The remaining 15
# points are cluster-level (long-tail breadth).
KEYWORD_SCORE_MAX = DEMAND_MAX + KD_MAX + WEAK_SERP_MAX

# ---------------------------------------------------------------------------
# A. Search demand bands (US volume -> points, deliberately non-linear)
# ---------------------------------------------------------------------------

DEMAND_BANDS = [
    (0, 0, "none"),
    (1, 4, "very low"),
    (100, 9, "low"),
    (300, 17, "useful niche demand"),
    (1000, 25, "strong"),
    (5000, 31, "very strong"),
    (10000, DEMAND_MAX, "excellent"),
]

# ---------------------------------------------------------------------------
# B. Keyword difficulty bands
# ---------------------------------------------------------------------------

KD_BANDS = [
    (0, KD_MAX, "excellent"),
    (15, 25, "very good"),
    (30, 19, "usable"),
    (40, 12, "difficult"),
    (50, 6, "very difficult"),
    (60, 0, "poor for a new site"),
]

# Volumes/KD above these limits mean a term is not buildable for a new site.
VIABLE_MIN_VOLUME = 100
VIABLE_MAX_KD = 49

# ---------------------------------------------------------------------------
# C. Weak-SERP evidence
# ---------------------------------------------------------------------------

WEAK_SERP_NONE = 0
WEAK_SERP_BOOLEAN = 12          # weak_serp = true
WEAK_SERP_COUNT_ONE = 12        # weak_serp_count = 1
WEAK_SERP_MULTIPLE = WEAK_SERP_MAX   # weak_serp_count >= 2
WEAK_SERP_MULTIPLE_THRESHOLD = 2

# ---------------------------------------------------------------------------
# D. Long-tail depth (cluster level)
# ---------------------------------------------------------------------------

# Additional viable keywords beyond the strongest one.
SUPPORT_BONUS_PER_KEYWORD = 2
SUPPORT_BONUS_CAP = 6

# Distinct search intents beyond the strongest one.
LONGTAIL_BONUS_PER_INTENT = 3
LONGTAIL_BONUS_CAP = LONGTAIL_MAX

# ---------------------------------------------------------------------------
# SEO status conditions
# ---------------------------------------------------------------------------

# VALIDATED: enough representative keywords have been checked.
VALIDATED_MIN_CHECKED = 3
VALIDATED_MIN_VIABLE = 2

# ---------------------------------------------------------------------------
# Market demand gate
# ---------------------------------------------------------------------------

GATE_MIN_VOLUME = 300       # a single meaningful term
GATE_MAX_KD = 49
GATE_LONGTAIL_MIN_VOLUME = 100
GATE_LONGTAIL_MAX_KD = 39
GATE_LONGTAIL_MIN_COUNT = 2
GATE_NEGLIGIBLE_VOLUME = 100
GATE_PROHIBITIVE_KD = 60
