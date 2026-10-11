"""Unified opportunity entity + corroboration (Phase 6, Steps 3, 17, 18).

Signals from different sources that describe the same underlying product
category are merged into one opportunity instead of producing duplicate
clusters. Merging is deliberately conservative: two items only merge when they
share a canonical product key or a shared domain+function pair.

Nothing here changes Phase 1-5 scores, thresholds or verdicts.
"""

from analyzers import signals as S
from analyzers.clustering import classify
from analyzers.text_utils import normalize_name, tokenize

CORROBORATION_NONE = "NONE"
CORROBORATION_WEAK = "WEAK"
CORROBORATION_MEDIUM = "MEDIUM"
CORROBORATION_STRONG = "STRONG"

# One point-weight per evidence family; independent sources add a smaller bonus.
FAMILY_POINTS = 12
INDEPENDENT_SOURCE_POINTS = 4
INDEPENDENT_SOURCE_CAP = 16
STRONG_THRESHOLD = 55
MEDIUM_THRESHOLD = 25


def _signal_product(signal):
    """Adapt a signal to the shape clustering.classify() expects."""
    return {
        "name": signal.get("product_name") or signal.get("title") or "",
        "description": signal.get("description") or "",
        "_source": signal.get("source") or "",
    }


def canonical_key(signal):
    """Stable key used to merge signals into one opportunity.

    Returns ``None`` when the signal cannot be anchored to a product category
    (e.g. a generic Ask-HN question). Such signals stay *evidence* and must not
    become standalone opportunities.
    """
    product = _signal_product(signal)
    info = classify(product)
    if info["domain"] and info["function"]:
        return f"{info['domain']}:{info['function']}"
    if signal.get("signal_type") != S.PRODUCT_SIGNAL:
        return None
    name = normalize_name(product.get("name") or "")
    if name:
        return f"name:{name}"
    return None


def build_opportunities(signal_list):
    """Group signals into opportunity entities with lineage + corroboration."""
    entities = {}
    for signal in signal_list or []:
        key = canonical_key(signal)
        if key is None:
            continue                      # demand-only evidence, no anchor
        entity = entities.setdefault(key, _new_entity(key, signal))
        _add_signal(entity, signal)
    result = list(entities.values())
    for entity in result:
        _finalize(entity)
    result.sort(key=lambda e: (-e["corroboration_score"], e["opportunity_id"]))
    return result


def unmatched_signals(signal_list):
    """Evidence that could not be anchored to an opportunity (kept, not merged)."""
    return [signal for signal in (signal_list or []) if canonical_key(signal) is None]


def _new_entity(key, signal):
    product = _signal_product(signal)
    info = classify(product)
    return {
        "opportunity_id": key.replace(":", "-"),
        "canonical_name": product.get("name") or signal.get("title") or "",
        "category": info.get("domain"),
        "function": info.get("function"),
        "target_user": signal.get("target_user"),
        "problem_statement": signal.get("pain_point") or signal.get("description") or "",
        "product_signals": [], "pain_signals": [], "demand_signals": [],
        "payment_signals": [], "revenue_signals": [], "trend_signals": [],
        "competition_signals": [], "feature_gap_signals": [], "exit_signals": [],
        "search_signals": [], "corroboration_signals": [],
        "source_count": 0,
        "independent_source_count": 0,
        "corroboration_score": 0,
        "corroboration_level": CORROBORATION_NONE,
        "underlying_sources": [],
        "aggregator_sources": [],
    }


_BUCKETS = {
    S.PRODUCT_SIGNAL: "product_signals",
    S.PAIN_SIGNAL: "pain_signals",
    S.DEMAND_SIGNAL: "demand_signals",
    S.PAYMENT_SIGNAL: "payment_signals",
    S.REVENUE_SIGNAL: "revenue_signals",
    S.TREND_SIGNAL: "trend_signals",
    S.COMPETITION_SIGNAL: "competition_signals",
    S.FEATURE_GAP_SIGNAL: "feature_gap_signals",
    S.EXIT_SIGNAL: "exit_signals",
    S.SEARCH_SIGNAL: "search_signals",
    S.CORROBORATION_SIGNAL: "corroboration_signals",
}


def _add_signal(entity, signal):
    bucket = _BUCKETS.get(signal.get("signal_type"))
    if bucket:
        entity[bucket].append(signal)
    entity["source_count"] += 1
    underlying = signal.get("underlying_source_id")
    if underlying and underlying not in entity["underlying_sources"]:
        entity["underlying_sources"].append(underlying)
    aggregator = signal.get("aggregator_source")
    if aggregator and aggregator not in entity["aggregator_sources"]:
        entity["aggregator_sources"].append(aggregator)


def _finalize(entity):
    entity["independent_source_count"] = len(entity["underlying_sources"])
    families = set()
    for signal_type, bucket in _BUCKETS.items():
        if entity[bucket]:
            families.add(S.signal_family(signal_type))
    score = FAMILY_POINTS * len(families)
    score += min(INDEPENDENT_SOURCE_POINTS
                 * max(entity["independent_source_count"] - 1, 0),
                 INDEPENDENT_SOURCE_CAP)
    entity["corroboration_score"] = min(score, 100)
    entity["evidence_families"] = sorted(families)
    if entity["corroboration_score"] >= STRONG_THRESHOLD:
        entity["corroboration_level"] = CORROBORATION_STRONG
    elif entity["corroboration_score"] >= MEDIUM_THRESHOLD:
        entity["corroboration_level"] = CORROBORATION_MEDIUM
    elif entity["corroboration_score"] > 0:
        entity["corroboration_level"] = CORROBORATION_WEAK
    else:
        entity["corroboration_level"] = CORROBORATION_NONE


def evidence_matrix(entity):
    """Simple counts per evidence family for the report's matrix."""
    return {
        "product": len(entity.get("product_signals", [])),
        "pain": len(entity.get("pain_signals", [])),
        "demand": len(entity.get("demand_signals", [])),
        "revenue": len(entity.get("revenue_signals", [])) + len(entity.get("payment_signals", [])),
        "trend": len(entity.get("trend_signals", [])),
        "competition": len(entity.get("competition_signals", []))
                       + len(entity.get("feature_gap_signals", [])),
        "exit": len(entity.get("exit_signals", [])),
        "search": len(entity.get("search_signals", [])),
    }


def attach_opportunities(clusters, opportunities):
    """Link product clusters to opportunity entities by cluster key/name."""
    by_id = {}
    for entity in opportunities:
        by_id[entity["opportunity_id"]] = entity
        by_id[entity["opportunity_id"].replace("-", ":")] = entity

    for cluster in clusters:
        entity = by_id.get(cluster.get("cluster_id")) or by_id.get(cluster.get("cluster_key"))
        if entity is None:
            name = normalize_name(cluster.get("cluster_label") or "")
            for candidate in opportunities:
                if name and normalize_name(candidate["canonical_name"]) == name:
                    entity = candidate
                    break
        if entity is not None:
            cluster["opportunity_id"] = entity["opportunity_id"]
            cluster["opportunity_entity_ids"] = [entity["opportunity_id"]]
            cluster["corroboration_score"] = entity["corroboration_score"]
            cluster["corroboration_level"] = entity["corroboration_level"]
            cluster["independent_source_count"] = entity["independent_source_count"]
            cluster["evidence_families"] = entity["evidence_families"]
            cluster["evidence_family_count"] = len(entity["evidence_families"])
    return clusters
