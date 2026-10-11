"""Constants for Phase 2 opportunity clustering and keyword generation.

Separate from ``scoring_weights`` (the product-level Solo Builder Score) so the
two models can evolve independently. Everything here is deterministic; there
are no LLM calls, embeddings, databases or paid APIs in Phase 2.
"""

# ---------------------------------------------------------------------------
# Cluster ranking score
# ---------------------------------------------------------------------------

# Bonus for multiple supporting products (capped so duplicate low-quality
# products can never carry a cluster).
MEMBER_BONUS_PER_MEMBER = 3
MEMBER_BONUS_CAP = 9

# Bonus for independent product-oriented sources reporting the same cluster.
SOURCE_BONUS_PER_SOURCE = 4
SOURCE_BONUS_CAP = 12

# Reuses the Phase 1 source-confidence scale (+/-5 points).
CONFIDENCE_ADJUSTMENT_MAX = 5

# Persistence bonus, only available when historical JSON data exists.
PERSISTENCE_BONUS_PER_DAY = 1
PERSISTENCE_BONUS_CAP = 7

# A cluster supported only by Hacker News (news, weak product relevance)
# cannot rank highly.
HN_ONLY_SOURCES = ("hackernews",)
HN_ONLY_PENALTY = 20

# Clusters whose best member is below this score get their bonuses halved,
# which enforces a quality floor without discarding the cluster entirely.
QUALITY_FLOOR = 60
LOW_QUALITY_BONUS_MULTIPLIER = 0.5

# A cluster backed by a single product from a single source is weak evidence
# (no corroboration), so it ranks below clusters with real support.
SINGLETON_PENALTY = 12

CLUSTER_SCORE_MAX = 100

# Maximum clusters listed in the Markdown "Top Opportunity Clusters" table
# (the full list is always available in the HTML dashboard and in the
# per-product evidence section).
MAX_CLUSTERS_IN_TABLE = 15

# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

# data/daily is trimmed to 28 days by storage.cleanup_old_data, so history
# signals can never look further back than that.
DEFAULT_HISTORY_DAYS = 28

# ---------------------------------------------------------------------------
# Keyword candidates
# ---------------------------------------------------------------------------

MIN_KEYWORDS_PER_CLUSTER = 5
MAX_KEYWORDS_PER_CLUSTER = 15
MAX_KEYWORD_WORDS = 6

# At most this many different head words (generator / maker / creator ...) are
# emitted for one cluster, to avoid near-duplicate permutations.
MAX_HEAD_WORD_VARIANTS = 2

# ---------------------------------------------------------------------------
# Semrush Check List
# ---------------------------------------------------------------------------

SEMRUSH_MIN_KEYWORDS = 10
SEMRUSH_MAX_KEYWORDS = 20
SEMRUSH_MAX_CLUSTERS = 8

# Per-cluster coverage: at least this many before any cluster gets more, and
# never more than the maximum (avoids checking many variants of one intent).
SEMRUSH_PER_CLUSTER_MIN = 2
SEMRUSH_PER_CLUSTER_MAX = 4
