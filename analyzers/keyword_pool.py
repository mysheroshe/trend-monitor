"""Keyword pool + tiered Semrush priority checklist (Phase 6, Steps 19-22).

Two layers:
  * ``keyword_pool``            - 20-40 candidates/day, no forced minimum
  * ``semrush_priority_checklist`` - the 10-15 strongest terms to check by hand

Every entry keeps its tier (A/B/C), maturity, candidate origin and the
opportunity it belongs to. BRAND and AWKWARD phrases never appear.
"""

from analyzers.keyword_quality import MATURITY_BROAD, MATURITY_NICHE

TIER_RANK = {"A": 0, "B": 1, "C": 2}
PRIORITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

DEFAULT_POOL_LIMIT = 40
DEFAULT_CHECKLIST_LIMIT = 15

POOL_MATURITY = (MATURITY_NICHE, MATURITY_BROAD)


def _status(enrichment, cluster_id, keyword):
    if not enrichment:
        return "UNCHECKED"
    from storage.enrichment_store import get_record

    record = get_record(enrichment, cluster_id, keyword)
    if not record:
        return "UNCHECKED"
    status = record.get("status") or "UNCHECKED"
    return status if status in ("CHECKED", "REJECTED") else "UNCHECKED"


def build_keyword_pool(clusters, enrichment=None, limit=DEFAULT_POOL_LIMIT,
                       include_checked=False):
    """All usable candidates across clusters, best first (no padding needed)."""
    pool = []
    seen = set()
    for cluster in clusters:
        for candidate in cluster.get("keyword_candidates") or []:
            keyword = candidate.get("keyword")
            maturity = candidate.get("maturity")
            if not keyword or keyword in seen or maturity not in POOL_MATURITY:
                continue
            status = _status(enrichment, cluster.get("cluster_id"), keyword)
            if status != "UNCHECKED" and not include_checked:
                continue
            seen.add(keyword)
            pool.append({
                "keyword": keyword,
                "tier": candidate.get("tier", "C"),
                "maturity": maturity,
                "origin": candidate.get("origin", "CORE"),
                "priority": candidate.get("priority"),
                "type": candidate.get("type"),
                "reason": candidate.get("reason"),
                "cluster_id": cluster.get("cluster_id"),
                "cluster_label": cluster.get("cluster_label"),
                "opportunity_score": cluster.get("opportunity_score", 0),
                "discovery_quality": cluster.get("discovery_quality", "MEDIUM"),
                "corroboration_level": cluster.get("corroboration_level", "NONE"),
                "status": status,
            })
    pool.sort(key=lambda entry: (
        TIER_RANK.get(entry["tier"], 9),
        PRIORITY_RANK.get(entry["priority"], 9),
        -entry["opportunity_score"],
        entry["keyword"],
    ))
    return pool[:limit]


def build_priority_checklist(pool, limit=DEFAULT_CHECKLIST_LIMIT):
    """A-tier first, then the strongest B-tier terms (never padded with C)."""
    tier_a = [entry for entry in pool if entry["tier"] == "A"]
    tier_b = [entry for entry in pool if entry["tier"] == "B"]
    return (tier_a + tier_b)[:limit]


def tier_counts(pool):
    counts = {"A": 0, "B": 0, "C": 0}
    for entry in pool:
        counts[entry["tier"]] = counts.get(entry["tier"], 0) + 1
    return counts
