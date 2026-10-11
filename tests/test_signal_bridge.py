"""Product-signal bridge tests (Phase 6.2, Steps 1-10)."""

from analyzers import signals as S
from analyzers.indie_analyzer import rank_products
from analyzers.keyword_pool import build_keyword_pool
from analyzers.signal_bridge import (
    ORIGIN_TYPE,
    bridge_eligible,
    bridge_summary,
    bridged_products,
    signal_to_product,
)


def _signal(source, signal_type, title, description="", url="", **fields):
    return S.make_signal(source, signal_type, title, description, url, **fields)


def test_devhunt_product_signal_converts_to_a_product():
    signal = _signal("devhunt", S.PRODUCT_SIGNAL, "AstraCode",
                     "The AI-native code editor for reviewing code",
                     "https://devhunt.org/tool/astracode")
    product = signal_to_product(signal)

    assert product is not None
    assert product["name"] == "AstraCode"
    assert product["_source"] == "devhunt"
    assert product["origin_type"] == ORIGIN_TYPE
    assert product["source_list"] == ["devhunt"]


def test_betalist_product_signal_converts_to_a_product():
    signal = _signal("betalist", S.PRODUCT_SIGNAL, "Image to 3D",
                     "Turn a single image into an editable 3D model",
                     "https://betalist.com/startups/image-to-3d")
    product = signal_to_product(signal)
    assert product is not None
    assert product["origin_type"] == ORIGIN_TYPE


def test_github_search_low_likeness_does_not_enter():
    signal = _signal("github_search", S.PRODUCT_SIGNAL, "some-dev/lib",
                     "A library for parsing YAML. npm install yaml-lib",
                     "https://github.com/some-dev/lib")
    eligible, reason = bridge_eligible(signal)
    assert eligible is False
    assert "LOW" in reason or "likeness" in reason.lower()
    assert signal_to_product(signal) is None


def test_demand_and_pain_signals_never_enter_the_product_pipeline():
    for source, signal_type in [("hn_demand", S.DEMAND_SIGNAL),
                                ("hn_demand", S.PAIN_SIGNAL),
                                ("reddit", S.PAIN_SIGNAL),
                                ("build_or_skip", S.CORROBORATION_SIGNAL)]:
        signal = _signal(source, signal_type, "Some pain", "some description")
        eligible, reason = bridge_eligible(signal)
        assert eligible is False, (source, signal_type)
        assert "evidence-only" in reason


def test_revenue_only_trustmrr_record_does_not_enter():
    thin = _signal("trustmrr", S.REVENUE_SIGNAL, "fanpilott", "",
                   "https://trustmrr.com/startup/fanpilott", pricing_or_revenue="$3k")
    assert bridge_eligible(thin)[0] is False


def test_concrete_trustmrr_product_can_enter():
    rich = _signal("trustmrr", S.REVENUE_SIGNAL, "Invoice Checker",
                   "An invoice checker tool that validates invoice line items automatically",
                   "https://trustmrr.com/startup/invoice-checker",
                   pricing_or_revenue="$2k/mo")
    assert bridge_eligible(rich)[0] is True


def test_navigation_chrome_is_rejected():
    chrome = _signal("betalist", S.PRODUCT_SIGNAL, "Browse all startups",
                     "navigation", "https://betalist.com/startups")
    assert bridge_eligible(chrome)[0] is False


def test_bridge_preserves_provenance():
    signal = _signal("betalist", S.PRODUCT_SIGNAL, "SongPilot",
                     "Run your music career with distribution and marketing",
                     "https://betalist.com/startups/songpilot")
    product = signal_to_product(signal)
    assert product["source_url"] == "https://betalist.com/startups/songpilot"
    assert product["underlying_source_id"] == signal["underlying_source_id"]
    assert product["raw_metadata"] is not None


def test_bridge_summary_counts_seen_bridged_skipped():
    signals = [
        _signal("betalist", S.PRODUCT_SIGNAL, "Tool A", "A tool that checks invoices",
                "https://betalist.com/startups/a"),
        _signal("hn_demand", S.DEMAND_SIGNAL, "Pain B", "I wish there was a tool"),
    ]
    summary = bridge_summary(signals)
    assert summary["betalist"]["bridged"] == 1
    assert summary["hn_demand"]["bridged"] == 0
    assert summary["hn_demand"]["skipped"] == 1


def test_duplicate_product_from_two_sources_merges_with_two_refs():
    """BetaList + Product Hunt describing the same product = one record."""
    collector_product = {
        "name": "SongPilot", "description": "Run your music career with distribution",
        "_source": "product_hunt", "link": "https://www.producthunt.com/products/songpilot",
    }
    bridged = bridged_products([
        _signal("betalist", S.PRODUCT_SIGNAL, "SongPilot",
                "Run your music career with distribution",
                "https://betalist.com/startups/songpilot"),
    ])
    groups = {"product_hunt": [collector_product], "betalist": bridged}
    suitable, _ = rank_products(groups)

    song = [p for p in suitable if p["name"] == "SongPilot"]
    assert len(song) == 1                       # not double-counted
    assert song[0]["source_count"] == 2
    assert set(song[0]["source_list"]) == {"product_hunt", "betalist"}


def test_bridged_product_participates_in_clustering_and_keywords():
    bridged = bridged_products([
        _signal("betalist", S.PRODUCT_SIGNAL,
                "Tattoo Stencil Generator",
                "Create tattoo stencils from a photo, generator for tattoo artists",
                "https://betalist.com/startups/tattoo-stencil-generator"),
        _signal("devhunt", S.PRODUCT_SIGNAL,
                "Tattoo Design Maker",
                "Tattoo design maker for artists",
                "https://devhunt.org/tool/tattoo-design-maker"),
    ])
    suitable, _ = rank_products({"betalist": [bridged[0]], "devhunt": [bridged[1]]})
    from analyzers.clustering import analyze_clusters
    from analyzers.keyword_candidates import attach_keyword_candidates

    clusters = attach_keyword_candidates(analyze_clusters(suitable, data_dir="/tmp/none"))
    tattoo = [c for c in clusters if c["cluster_id"] == "tattoo-generation"]
    assert tattoo, "bridged products must form the normal domain+function cluster"
    keywords = {k["keyword"] for k in tattoo[0]["keyword_candidates"]}
    assert "tattoo generator" in keywords
    assert any(c["maturity"] == "NICHE" for c in tattoo[0]["keyword_candidates"])

    pool = build_keyword_pool(clusters)
    assert pool, "the bridged cluster must reach the keyword pool"


def test_brand_and_awkward_filters_still_apply_to_bridged_products():
    bridged = bridged_products([
        _signal("betalist", S.PRODUCT_SIGNAL, "Monica: All-In-One AI Assist",
                "One stop AI Assistant: Chat, Write, Translate, Summarize",
                "https://betalist.com/startups/monica"),
    ])
    from analyzers.clustering import analyze_clusters
    from analyzers.keyword_candidates import attach_keyword_candidates

    suitable, _ = rank_products({"betalist": bridged})
    for cluster in attach_keyword_candidates(analyze_clusters(suitable, data_dir="/tmp/none")):
        for candidate in cluster.get("keyword_candidates", []):
            assert "monica" not in candidate["keyword"]
            assert candidate["maturity"] in ("NICHE", "BROAD")
