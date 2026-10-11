"""Opportunity clustering tests (Phase 2, Steps 1-4)."""

from analyzers.clustering import classify, cluster_id_for, score_cluster
from config import cluster_weights as CW


def test_title_variations_map_to_the_same_cluster(cluster_builder, tattoo_products):
    clusters = cluster_builder(tattoo_products)

    assert len(clusters) == 1
    assert clusters[0]["cluster_id"] == "tattoo-generation"
    assert clusters[0]["cluster_key"] == "tattoo:generation"
    assert clusters[0]["cluster_label"] == "Tattoo Generator Tools"
    assert clusters[0]["member_count"] == 4


def test_unrelated_ai_tools_do_not_collapse(cluster_builder):
    clusters = cluster_builder([
        {"name": "AI Personal Assistant", "description": "A general assistant for everyday tasks.",
         "_source": "toolify", "link": "https://example.com/1"},
        {"name": "AI Image Upscaler", "description": "Upscale photos with AI.",
         "_source": "toolify", "link": "https://example.com/2"},
        {"name": "AI Tattoo Generator", "description": "Generate tattoo designs.",
         "_source": "toolify", "link": "https://example.com/3"},
    ])

    assert len(clusters) == 3
    assert all(cluster["member_count"] == 1 for cluster in clusters)
    assert "tattoo-generation" in {c["cluster_id"] for c in clusters}


def test_cluster_id_is_stable_across_input_order(cluster_builder, tattoo_products, audio_products):
    products = list(tattoo_products) + list(audio_products)

    forward = {p["name"]: classify(p)["cluster_id"] for p in products}
    backward = {p["name"]: classify(p)["cluster_id"] for p in reversed(products)}
    assert forward == backward

    ids_forward = {c["cluster_id"] for c in cluster_builder(products)}
    ids_backward = {c["cluster_id"] for c in cluster_builder(list(reversed(products)))}
    assert ids_forward == ids_backward


def test_cluster_id_is_a_stable_slug_not_a_product_name():
    assert cluster_id_for("tattoo:generation") == "tattoo-generation"
    assert cluster_id_for("tattoo:generation") == cluster_id_for("tattoo:generation")
    assert cluster_id_for("pdf:conversion") == "pdf-conversion"
    assert cluster_id_for("audio:finding") == "audio-finding"


def test_duplicate_toolify_products_do_not_inflate_member_count(cluster_builder):
    clusters = cluster_builder([
        {"name": "AI Tattoo Generator", "link": "https://example.com/same", "_source": "toolify"},
        {"name": "AI  Tattoo Generator!", "link": "https://example.com/same", "_source": "toolify"},
        {"name": "Free Tattoo Maker", "link": "https://example.com/other", "_source": "toolify"},
    ])

    assert len(clusters) == 1
    assert clusters[0]["member_count"] == 2


def test_hn_only_cluster_does_not_outrank_a_multi_source_cluster(cluster_builder, tattoo_products):
    hn_products = [
        {"title": "Show HN: BPM finder for songs",
         "url": "https://news.ycombinator.com/item?id=1", "_source": "hackernews"},
        {"title": "Show HN: Song key finder",
         "url": "https://news.ycombinator.com/item?id=2", "_source": "hackernews"},
    ]
    clusters = cluster_builder(list(tattoo_products) + hn_products)
    by_id = {c["cluster_id"]: c for c in clusters}

    assert "tattoo-generation" in by_id
    assert "audio-finding" in by_id

    hn_cluster = by_id["audio-finding"]
    assert hn_cluster["member_sources"] == ["hackernews"]
    assert "hn_only" in hn_cluster["cluster_score_breakdown"]["penalties"]
    assert hn_cluster["cluster_score"] < by_id["tattoo-generation"]["cluster_score"]
    assert clusters[0]["cluster_id"] == "tattoo-generation"


def test_member_count_bonus_is_capped():
    cluster = {
        "max_solo_builder_score": 80,
        "member_count": 40,
        "source_diversity": 1,
        "strongest_source_confidence_value": 0.5,
        "strongest_source_confidence": "Medium",
        "member_sources": ["toolify"],
        "days_seen": 1,
    }
    breakdown = score_cluster(cluster)["cluster_score_breakdown"]
    assert breakdown["member_bonus"] == CW.MEMBER_BONUS_CAP


def test_source_diversity_bonus_is_capped():
    cluster = {
        "max_solo_builder_score": 80,
        "member_count": 40,
        "source_diversity": 40,
        "strongest_source_confidence_value": 0.5,
        "strongest_source_confidence": "Medium",
        "member_sources": ["toolify"],
        "days_seen": 1,
    }
    result = score_cluster(cluster)
    assert result["cluster_score_breakdown"]["source_bonus"] == CW.SOURCE_BONUS_CAP
    assert result["cluster_score"] <= CW.CLUSTER_SCORE_MAX


def test_low_quality_cluster_gets_halved_bonuses():
    base = {
        "member_count": 5,
        "source_diversity": 3,
        "strongest_source_confidence_value": 1.0,
        "strongest_source_confidence": "High",
        "member_sources": ["toolify", "product_hunt", "ai_tools"],
        "days_seen": 1,
    }
    weak = score_cluster({**base, "max_solo_builder_score": 30})
    strong = score_cluster({**base, "max_solo_builder_score": 80})

    assert "below_quality_floor" in weak["cluster_score_breakdown"]["penalties"]
    assert "below_quality_floor" not in strong["cluster_score_breakdown"]["penalties"]

    assert (weak["cluster_score_breakdown"]["bonuses_applied"]
            == strong["cluster_score_breakdown"]["bonuses_applied"] // 2)
    assert weak["cluster_score"] < strong["cluster_score"]
