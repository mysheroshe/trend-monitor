"""Multi-source opportunity engine tests (Phase 6, Steps 2-3, 17-22, 24)."""

import types

from analyzers import signals as S
from analyzers.keyword_pool import (
    build_keyword_pool,
    build_priority_checklist,
    tier_counts,
)
from analyzers.opportunity import (
    CORROBORATION_NONE,
    CORROBORATION_STRONG,
    build_opportunities,
    canonical_key,
    evidence_matrix,
    unmatched_signals,
)


def _signal(source, signal_type, title, description="", url="", **fields):
    return S.make_signal(source, signal_type, title, description, url, **fields)


# --- signal taxonomy -------------------------------------------------------

def test_pain_and_demand_patterns_are_detected():
    types, matched = S.detect_pain_patterns("I wish there was a tool that fixes my CSVs")
    assert S.PAIN_SIGNAL in types
    assert matched

    types, _ = S.detect_pain_patterns("Looking for software to reconcile invoices")
    assert S.DEMAND_SIGNAL in types

    types, _ = S.detect_pain_patterns("The export button is missing feature, cannot export")
    assert S.FEATURE_GAP_SIGNAL in types


def test_reddit_style_pain_post_is_not_a_product_signal():
    types, _ = S.detect_pain_patterns("Alternative to Zapier? Too expensive for a solo founder")
    assert S.PRODUCT_SIGNAL not in types
    assert S.COMPETITION_SIGNAL in types or S.PAIN_SIGNAL in types


def test_signal_record_has_the_common_schema():
    signal = _signal("reddit", S.PAIN_SIGNAL, "Excel cleanup is painful",
                     "I currently do this in Excel", "https://reddit.com/r/x/1")
    for field in ("source", "source_url", "title", "description", "signal_type",
                  "canonical_url", "underlying_source_id", "evidence_strength"):
        assert field in signal
    assert signal["canonical_url"] == "reddit.com/r/x/1"


def test_verified_revenue_is_never_self_reported():
    assert S.revenue_confidence("trustmrr", self_reported=True) == S.REVENUE_PUBLIC_SELF_REPORTED
    assert S.revenue_confidence("trustmrr", self_reported=True,
                                verified_marker=True) == S.REVENUE_VERIFIED
    assert S.revenue_confidence("x", self_reported=False) == S.REVENUE_INFERRED


def test_exit_signal_typing_is_conservative():
    assert S.exit_signal_type("profitable, growing, steady MRR") == S.EXIT_HEALTHY
    assert S.exit_signal_type("distressed, shutting down") == S.EXIT_DISTRESSED
    assert S.exit_signal_type("for sale") == S.EXIT_UNKNOWN


# --- opportunity entity / merging -----------------------------------------

def test_multi_source_evidence_merges_into_one_opportunity():
    signals = [
        _signal("product_hunt", S.PRODUCT_SIGNAL, "Tattoo Generator",
                "Generate tattoo designs", "https://ph.com/1"),
        _signal("reddit", S.PAIN_SIGNAL, "Tattoo design generator needed",
                "I wish there was a tattoo generator for stencils",
                "https://reddit.com/r/tattoo/1"),
        _signal("trustmrr", S.REVENUE_SIGNAL, "Tattoo AI tool",
                "$4.2k MRR from tattoo generation", "https://trustmrr.com/1",
                pricing_or_revenue="$4.2k/mo"),
    ]
    opportunities = build_opportunities(signals)

    assert len(opportunities) == 1
    entity = opportunities[0]
    assert entity["independent_source_count"] == 3
    assert entity["corroboration_level"] in ("MEDIUM", "STRONG")
    matrix = evidence_matrix(entity)
    assert matrix["product"] == 1 and matrix["pain"] == 1 and matrix["revenue"] == 1


def test_syndicated_duplicate_does_not_double_count():
    original = "https://reddit.com/r/SaaS/1"
    signals = [
        _signal("reddit", S.PAIN_SIGNAL, "Spreadsheet consistency checker needed",
                "I wish there was a spreadsheet checker for formulas", original),
        _signal("startupideasdb", S.PAIN_SIGNAL, "Spreadsheet consistency checker needed",
                "I wish there was a spreadsheet checker for formulas",
                "https://startupideasdb.com/x",
                underlying_source_id=S.canonical_url(original),
                aggregator_source="startupideasdb", original_source="reddit"),
    ]
    entity = build_opportunities(signals)[0]
    assert entity["source_count"] == 2
    assert entity["independent_source_count"] == 1        # same underlying post


def test_repeated_signals_from_one_source_are_not_independent():
    signals = [
        _signal("reddit", S.PAIN_SIGNAL, "CSV cleanup pain", "manual process", "https://reddit.com/a"),
        _signal("reddit", S.PAIN_SIGNAL, "CSV cleanup pain 2", "takes too long", "https://reddit.com/b"),
        _signal("reddit", S.PAIN_SIGNAL, "CSV cleanup pain 3", "workaround", "https://reddit.com/c"),
    ]
    entity = build_opportunities(signals)[0]
    assert entity["source_count"] == 3
    assert entity["independent_source_count"] == 3        # 3 distinct URLs
    assert entity["corroboration_level"] != CORROBORATION_STRONG


def test_multiple_families_raise_the_corroboration_level():
    one_family = build_opportunities([
        _signal("reddit", S.PAIN_SIGNAL, "Invoice checker is missing",
                "I wish there was an invoice checker tool", "https://reddit.com/1"),
    ])[0]
    many_families = build_opportunities([
        _signal("reddit", S.PAIN_SIGNAL, "Invoice checker is missing",
                "I wish there was an invoice checker tool", "https://reddit.com/1"),
        _signal("github", S.PRODUCT_SIGNAL, "Invoice checker",
                "Tool for checking invoices", "https://github.com/a/b"),
        _signal("trustmrr", S.REVENUE_SIGNAL, "Invoice checker",
                "$2k MRR", "https://trustmrr.com/2"),
        _signal("hn_demand", S.TREND_SIGNAL, "Invoice checker growth",
                "growing fast", "https://news.ycombinator.com/item?id=1"),
        _signal("github_search", S.COMPETITION_SIGNAL, "Invoice checker alternatives",
                "alternative to legacy tools", "https://github.com/c/d"),
    ])[0]

    assert many_families["corroboration_score"] > one_family["corroboration_score"]
    assert many_families["corroboration_level"] == CORROBORATION_STRONG


def test_unanchored_demand_is_evidence_not_an_opportunity():
    signals = [
        _signal("hn_demand", S.DEMAND_SIGNAL, "Ask HN: what do you use for note taking?",
                "just curious", "https://news.ycombinator.com/item?id=2"),
        _signal("product_hunt", S.PRODUCT_SIGNAL, "Tattoo Generator",
                "Generate tattoo designs", "https://ph.com/2"),
    ]
    opportunities = build_opportunities(signals)
    assert len(opportunities) == 1
    assert opportunities[0]["category"] == "tattoo"
    assert len(unmatched_signals(signals)) == 1
    assert canonical_key(signals[0]) is None


def test_github_product_merges_with_matching_demand():
    signals = [
        _signal("github_search", S.PRODUCT_SIGNAL, "pdf-checker",
                "Tool for checking PDF files offline", "https://github.com/x/pdf-checker"),
        _signal("hn_demand", S.DEMAND_SIGNAL, "Looking for a PDF checker tool",
                "is there a tool that checks PDFs?", "https://news.ycombinator.com/item?id=3"),
    ]
    entity = build_opportunities(signals)[0]
    assert entity["category"] == "pdf"
    assert entity["independent_source_count"] == 2
    assert "demand" in entity["evidence_families"]


def test_different_functions_in_the_same_domain_do_not_merge():
    """Over-merging guard: the same domain with different functions stays apart."""
    checking = _signal("github_search", S.PRODUCT_SIGNAL, "pdf-checker",
                       "Tool for checking PDF files", "https://github.com/x/checker")
    converting = _signal("github_search", S.PRODUCT_SIGNAL, "pdf-converter",
                         "Tool for converting PDF files", "https://github.com/x/converter")

    assert canonical_key(checking) == "pdf:checking"
    assert canonical_key(converting) == "pdf:conversion"
    assert len(build_opportunities([checking, converting])) == 2


def test_corroboration_alone_does_not_create_a_verdict():
    """Evidence never sets a verdict; the Phase 4 layer owns verdicts."""
    signals = [_signal("build_or_skip", S.CORROBORATION_SIGNAL, "Tattoo generators",
                       "their verdict: build", "https://buildorskip.com/x")]
    opportunities = build_opportunities(signals)
    assert opportunities, "corroboration evidence still creates an entity"
    entity = opportunities[0]
    assert "verdict" not in entity
    assert "verdict_reasons" not in entity
    assert entity["corroboration_level"] != CORROBORATION_NONE


# --- adapters / source health ---------------------------------------------

def test_fetch_all_survives_a_crashing_adapter(monkeypatch):
    from collectors import adapters

    class _Boom:
        TIER = 1
        SIGNAL_TYPES = (S.PRODUCT_SIGNAL,)
        LAST_ERROR = ""

        @staticmethod
        def fetch(limit=15, timeout=None):
            raise RuntimeError("source exploded")

    monkeypatch.setitem(adapters.IMPLEMENTED, "boom", _Boom)
    # only the stubbed adapter runs, so this test stays offline
    signals, rows = adapters.fetch_all(limit_per_source=1, enabled=["boom"])

    boom_row = [row for row in rows if row["source"] == "boom"][0]
    assert boom_row["status"] == "error"
    assert "source exploded" in boom_row["last_error"]
    assert isinstance(signals, list)            # pipeline continues


def test_adapter_registry_reports_blocks_honestly():
    from collectors.adapters import DECLARED_SOURCES

    by_source = {entry["source"]: entry for entry in DECLARED_SOURCES}
    # Phase 7 integrated Reddit through the official API (HTML stays unreachable)
    assert by_source["reddit"]["status"] == "official_api"
    assert "official Reddit API" in by_source["reddit"]["detail"]
    assert by_source["upwork"]["status"] == "blocked"
    assert by_source["g2"]["status"] == "blocked"
    assert by_source["x_twitter"]["status"] == "blocked"
    assert by_source["devhunt"]["status"] == "html_only"
    for entry in DECLARED_SOURCES:
        assert entry["detail"]          # every declaration carries a reason


def test_source_health_rows_carry_signal_types():
    from collectors.adapters import DECLARED_SOURCES

    for entry in DECLARED_SOURCES:
        assert isinstance(entry["signal_types"], list)
        assert entry["signal_types"]


# --- keyword pool / tiers / origins ---------------------------------------

def test_keyword_pool_is_larger_than_the_priority_checklist(cluster_builder, tattoo_products, audio_products):
    clusters = cluster_builder(list(tattoo_products) + list(audio_products))
    pool = build_keyword_pool(clusters)
    checklist = build_priority_checklist(pool)

    assert len(pool) >= len(checklist)
    assert len(checklist) <= 15
    assert all(entry["tier"] in ("A", "B", "C") for entry in pool)
    assert all(entry["origin"] for entry in pool)


def test_multiple_long_tail_variants_per_cluster(cluster_builder, tattoo_products):
    clusters = cluster_builder(tattoo_products)
    pool = build_keyword_pool(clusters)
    per_cluster = {}
    for entry in pool:
        per_cluster.setdefault(entry["cluster_id"], []).append(entry["keyword"])

    assert max(len(v) for v in per_cluster.values()) >= 3


def test_pool_never_contains_brand_or_awkward(cluster_builder):
    clusters = cluster_builder([
        {"name": "Monica: All-In-One AI Assist & Smartest  AI Agent",
         "description": "One stop AI Assistant: Chat, Write, Translate, Summarize.",
         "_source": "chrome_extensions", "link": "https://example.com/monica"},
    ])
    pool = build_keyword_pool(clusters)
    for entry in pool:
        assert entry["maturity"] in ("NICHE", "BROAD")
        assert "monica" not in entry["keyword"]


def test_pool_is_not_padded(cluster_builder):
    clusters = cluster_builder([
        {"name": "Excel Consistency Checker", "description": "Check spreadsheet formulas.",
         "_source": "product_hunt", "link": "https://example.com/excel"},
    ])
    pool = build_keyword_pool(clusters)
    assert len(pool) <= 15           # no padding towards a target


def test_candidate_origin_is_stored_per_angle(cluster_builder, tattoo_products):
    clusters = cluster_builder(tattoo_products)
    origins = {c["origin"] for cluster in clusters
               for c in cluster.get("keyword_candidates", [])}
    assert origins & {"CORE", "USE_CASE", "USER_TYPE", "PROBLEM_PHRASE",
                      "ADJACENT_TOOL", "BROAD_BENCHMARK"}


def test_tier_counts_are_reported(cluster_builder, tattoo_products, audio_products):
    pool = build_keyword_pool(cluster_builder(list(tattoo_products) + list(audio_products)))
    counts = tier_counts(pool)
    assert set(counts) == {"A", "B", "C"}
    assert sum(counts.values()) == len(pool)
