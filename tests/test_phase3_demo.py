"""Offline demonstration with the Step 12 demo fixtures (tests only)."""

from config import seo_weights as SW
from storage import enrichment_store as es


def _by_id(clusters):
    return {cluster["cluster_id"]: cluster for cluster in clusters}


def test_demo_clusters_are_built(demo_clusters):
    by_id = _by_id(demo_clusters)
    assert set(by_id) == {"tattoo-generation", "prompt-generation", "spreadsheet-checking"}
    assert by_id["tattoo-generation"]["member_count"] == 3
    assert by_id["prompt-generation"]["member_count"] == 1
    assert by_id["spreadsheet-checking"]["member_count"] == 1


def test_demo_large_but_competitive_market(demo_clusters):
    tattoo = _by_id(demo_clusters)["tattoo-generation"]
    results = {k["keyword"]: k for k in tattoo["checked_keywords"]}

    assert results["ai tattoo generator"]["demand_band"] == "excellent"
    assert results["ai tattoo generator"]["kd_band"] == "very difficult"
    assert results["ai tattoo generator"]["is_viable"] is False
    assert results["tattoo stencil generator"]["is_viable"] is True

    # The cluster still passes because a narrower term is accessible.
    assert tattoo["seo_score_status"] == "VALIDATED"
    assert tattoo["market_demand_gate"] == "PASS"
    assert tattoo["seo_breakdown"]["best_keyword_score"] == 62
    assert tattoo["seo_breakdown"]["viable_keywords"] == 2


def test_demo_tiny_demand_despite_easy_kd(demo_clusters):
    excel = _by_id(demo_clusters)["spreadsheet-checking"]
    assert excel["seo_score_status"] == "PARTIAL"
    assert excel["market_demand_gate"] == "FAIL"
    checked = excel["checked_keywords"][0]
    assert checked["kd_band"] == "excellent"
    assert checked["demand_band"] == "very low"
    assert excel["seo_score"] < 50


def test_demo_small_but_accessible_niche(demo_clusters):
    prompt = _by_id(demo_clusters)["prompt-generation"]
    assert prompt["seo_score_status"] == "PARTIAL"
    assert prompt["market_demand_gate"] == "PASS"
    checked = prompt["checked_keywords"][0]
    assert checked["demand_band"] == "useful niche demand"
    assert checked["kd_band"] == "excellent"


def test_demo_orders_easy_to_build_last(demo_clusters):
    """Built for easy markets the ranking is SEO-first; the scores stay separate."""
    by_id = _by_id(demo_clusters)
    tattoo = by_id["tattoo-generation"]
    prompt = by_id["prompt-generation"]

    # easy-to-build does not imply a good market: SEO < Solo Builder here
    assert tattoo["seo_score"] < tattoo["max_solo_builder_score"]
    assert prompt["seo_score"] < prompt["max_solo_builder_score"]

    # large-but-competitive beats tiny-demand, and accessible niche beats tiny demand
    assert tattoo["seo_score"] > by_id["spreadsheet-checking"]["seo_score"]
    assert prompt["seo_score"] > by_id["spreadsheet-checking"]["seo_score"]


def test_demo_values_are_only_in_the_test_fixture(demo_store_path):
    """The demo numbers must never live in production data files."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    production = repo_root / "data" / "enrichment"
    for path in production.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        assert "18100" not in text
        assert "random art prompt generator" not in text

    store = es.load_store(demo_store_path)
    assert store["records"]["tattoo-generation|ai tattoo generator"]["us_volume"] == 18100
    assert SW.SEO_SCORE_MAX == 100
