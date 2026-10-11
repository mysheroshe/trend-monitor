"""SEO Opportunity Score from manually enriched Semrush data (Phase 3).

Uses ONLY stored enrichment records. Missing values are never invented and no
external service is called. The SEO score is deliberately kept separate from
the Solo Builder Score and the Cluster Evidence Score; Phase 4/5 will decide
how (and whether) to combine them.
"""

from analyzers.keyword_candidates import intent_signature
from config import seo_weights as SW
from storage import enrichment_store as store_module

SEO_NOT_CHECKED = "NOT_CHECKED"
SEO_PARTIAL = "PARTIAL"
SEO_VALIDATED = "VALIDATED"

GATE_PASS = "PASS"
GATE_WEAK = "WEAK"
GATE_FAIL = "FAIL"
GATE_UNKNOWN = "UNKNOWN"


def _band(bands, value):
    """Return (points, label) for the highest band whose threshold is met."""
    points, label = bands[0][1], bands[0][2]
    for threshold, band_points, band_label in bands:
        if value >= threshold:
            points, label = band_points, band_label
    return points, label


def has_required_fields(record):
    """Required-for-scoring fields: US volume, global volume, KD, weak SERP."""
    if not record:
        return False
    return all(record.get(field) is not None for field in store_module.REQUIRED_FIELDS)


def _weak_serp_points(record):
    count = record.get("weak_serp_count")
    if count is not None:
        if count >= SW.WEAK_SERP_MULTIPLE_THRESHOLD:
            return SW.WEAK_SERP_MULTIPLE, "multiple low-authority sites"
        if count == 1:
            return SW.WEAK_SERP_COUNT_ONE, "at least one weak site"
        return SW.WEAK_SERP_NONE, "no weak sites"
    if record.get("weak_serp"):
        return SW.WEAK_SERP_BOOLEAN, "at least one weak site"
    return SW.WEAK_SERP_NONE, "no weak sites"


def score_keyword(record):
    """Score one enriched keyword (demand + KD + weak SERP = max 85)."""
    if not has_required_fields(record):
        return None

    us_volume = int(record.get("us_volume") or 0)
    global_volume = int(record.get("global_volume") or 0)
    kd = int(record.get("kd") or 0)

    demand_points, demand_band = _band(SW.DEMAND_BANDS, us_volume)
    kd_points, kd_band = _band(SW.KD_BANDS, kd)
    weak_points, weak_label = _weak_serp_points(record)

    total = demand_points + kd_points + weak_points
    is_viable = us_volume >= SW.VIABLE_MIN_VOLUME and kd <= SW.VIABLE_MAX_KD

    return {
        "keyword": record.get("keyword", ""),
        "cluster_id": record.get("cluster_id", ""),
        "us_volume": us_volume,
        "global_volume": global_volume,
        "kd": kd,
        "weak_serp": record.get("weak_serp"),
        "weak_serp_count": record.get("weak_serp_count"),
        "demand_points": demand_points,
        "demand_band": demand_band,
        "kd_points": kd_points,
        "kd_band": kd_band,
        "weak_serp_points": weak_points,
        "weak_serp_label": weak_label,
        "keyword_score": total,
        "is_viable": is_viable,
        "intent": intent_signature(record.get("keyword", "")),
        "checked_at": record.get("checked_at"),
    }


def market_demand_gate(keyword_scores):
    """SEO-demand-only gate: PASS / WEAK / FAIL / UNKNOWN.

    Deliberately ignores product/community signals (Phase 3, Step 7).
    """
    if not keyword_scores:
        return GATE_UNKNOWN

    for score in keyword_scores:
        if (score["us_volume"] >= SW.GATE_MIN_VOLUME
                and score["kd"] <= SW.GATE_MAX_KD):
            return GATE_PASS

    longtails = [
        score for score in keyword_scores
        if score["us_volume"] >= SW.GATE_LONGTAIL_MIN_VOLUME
        and score["kd"] <= SW.GATE_LONGTAIL_MAX_KD
    ]
    if len(longtails) >= SW.GATE_LONGTAIL_MIN_COUNT:
        return GATE_PASS

    if all(score["us_volume"] < SW.GATE_NEGLIGIBLE_VOLUME for score in keyword_scores):
        return GATE_FAIL

    if all(score["kd"] >= SW.GATE_PROHIBITIVE_KD and not score["weak_serp"]
           for score in keyword_scores):
        return GATE_FAIL

    return GATE_WEAK


def score_cluster(cluster, store=None):
    """Derive a cluster's SEO Opportunity Score from its checked keywords.

    Not a simple average: the strongest primary keyword leads, supported by
    viable secondary keywords and a capped long-tail breadth bonus.
    """
    cluster_id = cluster.get("cluster_id")
    records = store_module.records_for(store, cluster_id=cluster_id) if store else []

    checked = [r for r in records
               if r.get("status") == store_module.STATUS_CHECKED and has_required_fields(r)]
    rejected = [r for r in records if r.get("status") == store_module.STATUS_REJECTED]

    keyword_scores = [score_keyword(record) for record in checked]
    keyword_scores = [score for score in keyword_scores if score]
    keyword_scores.sort(key=lambda s: (-s["keyword_score"], s["keyword"]))

    if not keyword_scores:
        return {
            "seo_score": 0,
            "seo_score_status": SEO_NOT_CHECKED,
            "market_demand_gate": GATE_UNKNOWN,
            "keyword_scores": [],
            "checked_keywords": [],
            "rejected_keywords": [r.get("keyword", "") for r in rejected],
            "seo_breakdown": {
                "best_keyword_score": 0,
                "support_bonus": 0,
                "longtail_bonus": 0,
                "viable_keywords": 0,
                "distinct_intents": 0,
                "checked_keywords": 0,
            },
            "seo_reasons": ["no enriched keywords yet - run scripts/enrich.py"],
        }

    best = keyword_scores[0]
    viable = [score for score in keyword_scores if score["is_viable"]]
    intents = {score["intent"] for score in viable if score["intent"]}

    # Both bonuses count DISTINCT intents, never raw keyword count: duplicate
    # permutations ("tattoo generator" / "free tattoo generator") add nothing.
    extra_intents = max(len(intents) - 1, 0)
    support_bonus = min(extra_intents * SW.SUPPORT_BONUS_PER_KEYWORD,
                        SW.SUPPORT_BONUS_CAP)
    longtail_bonus = min(extra_intents * SW.LONGTAIL_BONUS_PER_INTENT,
                         SW.LONGTAIL_BONUS_CAP)
    seo_score = max(0, min(SW.SEO_SCORE_MAX,
                           best["keyword_score"] + support_bonus + longtail_bonus))

    if (len(keyword_scores) >= SW.VALIDATED_MIN_CHECKED
            and len(viable) >= SW.VALIDATED_MIN_VIABLE):
        status = SEO_VALIDATED
    else:
        status = SEO_PARTIAL

    gate = market_demand_gate(keyword_scores)

    reasons = [
        f"best keyword '{best['keyword']}' scores {best['keyword_score']}/85 "
        f"(US {best['us_volume']:,}, KD {best['kd']}, {best['weak_serp_label']})",
        f"{len(viable)} viable keyword(s) of {len(keyword_scores)} checked",
    ]
    if support_bonus:
        reasons.append(f"secondary viable keywords add +{support_bonus}")
    if longtail_bonus:
        reasons.append(f"{len(intents)} distinct intents add +{longtail_bonus}")
    if not viable:
        reasons.append("no keyword clears the viability bar (>=100 US volume, KD <= 49)")

    return {
        "seo_score": seo_score,
        "seo_score_status": status,
        "market_demand_gate": gate,
        "keyword_scores": keyword_scores,
        "checked_keywords": keyword_scores,
        "rejected_keywords": [r.get("keyword", "") for r in rejected],
        "seo_breakdown": {
            "best_keyword_score": best["keyword_score"],
            "support_bonus": support_bonus,
            "longtail_bonus": longtail_bonus,
            "viable_keywords": len(viable),
            "distinct_intents": len(intents),
            "checked_keywords": len(keyword_scores),
        },
        "seo_reasons": reasons,
    }


def attach_seo(clusters, store=None):
    """Attach SEO fields to each cluster (mutates and returns the list)."""
    for cluster in clusters:
        cluster.update(score_cluster(cluster, store))
    return clusters
