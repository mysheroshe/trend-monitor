"""SEO Opportunity Score + market demand gate tests (Phase 3, Steps 5-7)."""

from analyzers.seo_score import (
    GATE_FAIL,
    GATE_PASS,
    GATE_UNKNOWN,
    GATE_WEAK,
    SEO_NOT_CHECKED,
    SEO_PARTIAL,
    SEO_VALIDATED,
    market_demand_gate,
    score_cluster,
    score_keyword,
)
from storage import enrichment_store as es


def _record(keyword, us, kd, weak=True, count=None, cluster_id="demo-cluster"):
    return {
        "cluster_id": cluster_id,
        "keyword": keyword,
        "status": "CHECKED",
        "rejection_reason": "",
        "us_volume": us,
        "global_volume": us * 2,
        "kd": kd,
        "weak_serp": weak,
        "weak_serp_count": count,
        "cpc": None,
        "intent": "",
        "notes": "",
        "checked_at": "2026-10-11T00:00:00-07:00",
        "history": [],
    }


def _store(records):
    return {
        "version": 1,
        "updated_at": None,
        "records": {es.record_key(r["cluster_id"], r["keyword"]): r for r in records},
    }


def _cluster(cluster_id="demo-cluster"):
    return {"cluster_id": cluster_id, "cluster_label": "Demo Tools", "member_count": 2,
            "source_diversity": 1, "cluster_score": 80}


def test_seo_score_always_stays_within_range():
    extremes = [
        _record("a", 0, 0, weak=False),
        _record("b", 1_000_000, 0, weak=True, count=5),
        _record("c", 50, 45, weak=False),
        _record("d", 999, 59, weak=True),
    ]
    for record in extremes:
        score = score_cluster(_cluster(), _store([record]))
        assert 0 <= score["seo_score"] <= 100
    for us in (0, 1, 99, 100, 299, 300, 999, 1000, 4999, 5000, 9999, 10000, 250000):
        score = score_keyword(_record("x", us, 25, weak=False))
        assert 0 <= score["keyword_score"] <= 85


def test_higher_volume_scores_substantially_higher_at_equal_kd():
    strong = score_keyword(_record("x", 5000, 15))
    weak = score_keyword(_record("x", 50, 15))

    assert strong["kd_points"] == weak["kd_points"]      # KD held constant
    assert strong["keyword_score"] - weak["keyword_score"] >= 15


def test_lower_kd_scores_better_at_equal_volume():
    easy = score_keyword(_record("x", 1200, 10))
    hard = score_keyword(_record("x", 1200, 70))

    assert easy["demand_points"] == hard["demand_points"]
    assert easy["keyword_score"] > hard["keyword_score"]
    assert hard["kd_points"] == 0


def test_weak_serp_helps_but_cannot_rescue_zero_demand():
    with_weak = score_keyword(_record("x", 0, 5, weak=True, count=3))
    without_weak = score_keyword(_record("x", 0, 5, weak=False))
    real_demand = score_keyword(_record("x", 500, 5, weak=True, count=3))

    assert with_weak["demand_points"] == 0
    assert with_weak["keyword_score"] > without_weak["keyword_score"]
    # zero demand caps the keyword at KD + weak-SERP points
    assert with_weak["keyword_score"] == 50
    assert real_demand["keyword_score"] > with_weak["keyword_score"]
    assert market_demand_gate([with_weak]) == GATE_FAIL
    assert score_cluster(_cluster(), _store([_record("x", 0, 5, weak=True, count=3)]))["seo_score"] < 60


def test_more_weak_sites_beat_a_single_one():
    many = score_keyword(_record("x", 800, 20, weak=True, count=3))
    one = score_keyword(_record("x", 800, 20, weak=True, count=1))
    none = score_keyword(_record("x", 800, 20, weak=False))

    assert many["weak_serp_points"] > one["weak_serp_points"] > none["weak_serp_points"]


def test_several_useful_long_tails_improve_the_cluster_score():
    base = [_record("tattoo generator", 1000, 20, weak=False)]
    extended = base + [
        _record("tattoo stencil generator", 500, 15, weak=False),
        _record("tattoo sleeve generator", 400, 18, weak=False),
    ]

    one = score_cluster(_cluster(), _store(base))
    many = score_cluster(_cluster(), _store(extended))

    assert many["seo_score"] > one["seo_score"]
    assert many["seo_breakdown"]["support_bonus"] > 0
    assert many["seo_breakdown"]["longtail_bonus"] > 0


def test_many_zero_volume_keywords_do_not_inflate_the_score():
    base = [_record("tattoo generator", 1000, 20, weak=False)]
    padded = base + [_record(f"filler keyword {i}", 0, 5, weak=False) for i in range(10)]

    assert (score_cluster(_cluster(), _store(padded))["seo_score"]
            == score_cluster(_cluster(), _store(base))["seo_score"])


def test_duplicate_intent_keywords_do_not_inflate_long_tail_depth():
    base = [_record("tattoo generator", 1000, 20, weak=False)]
    duplicate_intent = base + [_record("free tattoo generator", 900, 20, weak=False)]

    base_score = score_cluster(_cluster(), _store(base))
    dup_score = score_cluster(_cluster(), _store(duplicate_intent))

    assert dup_score["seo_breakdown"]["distinct_intents"] == 1
    assert dup_score["seo_score"] == base_score["seo_score"]


def test_one_huge_but_impossible_keyword_does_not_score_well():
    impossible = score_cluster(_cluster(), _store([_record("huge keyword", 50000, 80, weak=False)]))
    assert impossible["seo_score"] < 50
    assert impossible["market_demand_gate"] == GATE_FAIL


def test_seo_status_not_checked_partial_validated():
    empty = score_cluster(_cluster(), None)
    assert empty["seo_score"] == 0
    assert empty["seo_score_status"] == SEO_NOT_CHECKED
    assert empty["market_demand_gate"] == GATE_UNKNOWN

    partial = score_cluster(_cluster(), _store([_record("tattoo generator", 1000, 20)]))
    assert partial["seo_score_status"] == SEO_PARTIAL

    validated = score_cluster(_cluster(), _store([
        _record("tattoo generator", 1200, 20),
        _record("tattoo stencil generator", 500, 15),
        _record("tattoo idea generator", 300, 30),
    ]))
    assert validated["seo_score_status"] == SEO_VALIDATED


def test_seo_status_is_not_validated_by_many_zero_volume_keywords():
    records = [_record(f"tiny keyword {i}", 10, 5) for i in range(6)]
    result = score_cluster(_cluster(), _store(records))

    assert result["seo_score_status"] == SEO_PARTIAL
    assert result["market_demand_gate"] == GATE_FAIL


def test_rejected_keywords_do_not_score():
    checked = _record("tattoo generator", 1200, 20)
    rejected = _record("tattoo stencil generator", 5000, 10)
    rejected["status"] = "REJECTED"
    rejected["rejection_reason"] = "too broad"

    result = score_cluster(_cluster(), _store([checked, rejected]))

    assert [k["keyword"] for k in result["keyword_scores"]] == ["tattoo generator"]
    assert result["rejected_keywords"] == ["tattoo stencil generator"]


def test_market_demand_gate_states():
    assert market_demand_gate([]) == GATE_UNKNOWN
    assert market_demand_gate([score_keyword(_record("a", 500, 30))]) == GATE_PASS
    assert market_demand_gate([score_keyword(_record("a", 150, 55))]) == GATE_WEAK
    assert market_demand_gate([score_keyword(_record("a", 40, 10))]) == GATE_FAIL
    assert market_demand_gate([score_keyword(_record("a", 40000, 80, weak=False))]) == GATE_FAIL
    # several smaller long-tails together still pass
    assert market_demand_gate([
        score_keyword(_record("a", 150, 20)),
        score_keyword(_record("b", 200, 25)),
    ]) == GATE_PASS
