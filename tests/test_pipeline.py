"""End-to-end smoke test for the Markdown + HTML report generation."""

from pathlib import Path

from analyzers.clustering import analyze_clusters
from analyzers.indie_analyzer import generate_indie_report
from analyzers.indie_html_generator import generate_indie_html
from analyzers.indie_analyzer import rank_products
from analyzers.keyword_candidates import attach_keyword_candidates, build_semrush_checklist
from analyzers.seo_score import attach_seo
from config import timeutil
from storage import enrichment_store


SAMPLE = {
    "product_hunt": [
        {"name": "Joy for Gmail", "tagline": "A clearer inbox", "link": "https://ph/joy"},
    ],
    "toolify": {
        "new": [
            {"name": "Invoice Generator", "description": "Free invoice generator, no login.",
             "category": "Just launched", "link": "https://toolify/invoice"},
        ],
        "trending": [
            {"name": "Code Arena", "description": "Compare AI coding models.",
             "monthly_visit": "31.8M", "growth_rate": "1054%", "link": "https://toolify/code-arena"},
        ],
    },
    "ai_tools": [
        {"name": "ImageGen AI", "description": "Create images from text prompts.",
         "category": "Images", "link": "https://taaft/imagegen"},
    ],
    "chrome_extensions": [
        {"name": "Compose AI", "description": "Accelerate your writing.",
         "users": "300,000 users", "rating": "4.8/5.0", "link": "https://cws/compose"},
    ],
    "github": [
        {"name": "someone/csv-studio", "description": "Self-hosted spreadsheet to chart app.",
         "today_stars": "120 stars today"},
    ],
    "hackernews": [
        {"title": "Grieving the Loss of Details", "author": "a", "score": 10,
         "comments": 2, "url": "https://news.ycombinator.com/item?id=1"},
        {"title": "Show HN: I built a tiny JSON formatter", "author": "b", "score": 40,
         "comments": 5, "url": "https://news.ycombinator.com/item?id=2"},
    ],
}


def test_markdown_report_contains_the_new_scoring_output():
    report = generate_indie_report(
        SAMPLE["product_hunt"], SAMPLE["toolify"], SAMPLE["ai_tools"],
        SAMPLE["chrome_extensions"], SAMPLE["github"], SAMPLE["hackernews"],
    )

    assert f"Indie Hacker Opportunity Report - {timeutil.today_str()}" in report
    assert "Solo Builder Score" in report
    assert "Build Ease" in report and "Tool-Orchard" in report
    assert "Hacker News article/news item" in report
    assert "Top 5 Deep Dive" in report
    # Phase 4 adds the verdict layer on top of the same report
    assert "## Top Opportunities Today" in report
    assert "**Verdict:**" in report
    assert "Opportunity Score" in report


def test_html_report_is_generated_from_the_same_pipeline():
    markdown = generate_indie_report(
        SAMPLE["product_hunt"], SAMPLE["toolify"], SAMPLE["ai_tools"],
        SAMPLE["chrome_extensions"], SAMPLE["github"], SAMPLE["hackernews"],
    )
    html = generate_indie_html(markdown, SAMPLE)

    assert html.startswith("<!DOCTYPE html>")
    assert "Score /100" in html
    assert "Why this score" in html
    assert "tech_difficulty" not in html
    assert "indie_friendly" not in html


def _report():
    return generate_indie_report(
        SAMPLE["product_hunt"], SAMPLE["toolify"], SAMPLE["ai_tools"],
        SAMPLE["chrome_extensions"], SAMPLE["github"], SAMPLE["hackernews"],
    )


def test_markdown_report_contains_cluster_and_checklist_sections():
    report = _report()

    assert "## Top Opportunity Clusters" in report
    assert "## Semrush Check List" in report
    assert "## Individual Product Evidence" in report
    assert "Cluster id:" in report
    assert "US Volume" in report and "KD" in report
    # product-level evidence is preserved, not replaced
    assert "## Solo Builder Score - All Suitable Products" in report
    assert "### Why these scores" in report
    assert "## Top 5 Deep Dive" in report


def test_html_report_contains_cluster_and_checklist_sections():
    html = generate_indie_html(_report(), SAMPLE)

    assert "Top Opportunity Clusters" in html
    assert "Semrush Check List" in html
    assert "Individual Product Evidence" in html
    assert "cluster-card" in html
    assert "kw-list" in html
    # individual product evidence remains reachable
    assert "Solo Builder Score — All Suitable Products" in html
    assert "Top 5 Deep Dive" in html


def test_no_llm_or_paid_api_integration_was_introduced():
    root = Path(__file__).resolve().parents[1]
    new_modules = [
        "analyzers/clustering.py",
        "analyzers/keyword_candidates.py",
        "analyzers/keyword_quality.py",
        "analyzers/seo_score.py",
        "analyzers/brand_filter.py",
        "analyzers/source_quality.py",
        "collectors/__init__.py",
        "analyzers/text_utils.py",
        "config/cluster_weights.py",
        "config/seo_weights.py",
        "config/verdict_weights.py",
        "storage/enrichment_store.py",
        "storage/validation_store.py",
        "scripts/enrich.py",
        "scripts/validate.py",
        "analyzers/verdict.py",
        "analyzers/deep_research.py",
        "analyzers/indie_html_generator.py",
    ]
    banned_imports = [
        "import openai", "from openai", "import anthropic", "from anthropic",
        "import numpy", "import sklearn", "import faiss", "sentence_transformers",
        "import sqlalchemy", "import psycopg", "import requests",
    ]
    for rel in new_modules:
        source = (root / rel).read_text(encoding="utf-8")
        for banned in banned_imports:
            assert banned not in source, f"{rel} must not contain {banned!r}"

    requirements = (root / "requirements.txt").read_text(encoding="utf-8").lower()
    for banned in ["openai", "anthropic", "semrush", "ahrefs", "numpy",
                   "scikit", "faiss", "sentence-transformers", "sqlalchemy"]:
        assert banned not in requirements


# ---------------------------------------------------------------------------
# Phase 3: manual enrichment joins the report and the checklist
# ---------------------------------------------------------------------------

def _sample_clusters(store_path, data_dir):
    groups = {
        "product_hunt": SAMPLE["product_hunt"],
        "toolify": SAMPLE["toolify"]["new"] + SAMPLE["toolify"]["trending"],
        "ai_tools": SAMPLE["ai_tools"],
        "chrome_extensions": SAMPLE["chrome_extensions"],
        "github": SAMPLE["github"],
        "hackernews": SAMPLE["hackernews"],
    }
    suitable, _ = rank_products(groups)
    store = enrichment_store.load_store(store_path)
    clusters = attach_keyword_candidates(analyze_clusters(suitable, data_dir=data_dir))
    attach_seo(clusters, store)
    return clusters, store


def test_report_includes_the_three_separate_scores(tmp_path):
    store_path = tmp_path / "keywords.json"
    report = generate_indie_report(
        SAMPLE["product_hunt"], SAMPLE["toolify"], SAMPLE["ai_tools"],
        SAMPLE["chrome_extensions"], SAMPLE["github"], SAMPLE["hackernews"],
        enrichment_path=store_path,
    )

    assert "Solo Builder Score" in report
    assert "Cluster Evidence Score" in report
    assert "SEO Opportunity Score" in report
    assert "Market Demand Gate" in report
    assert "NOT_CHECKED" in report
    assert "scripts/enrich.py" in report
    # nothing enriched yet, so no checked-keyword table may be invented
    assert "| Checked keyword | US volume |" not in report


def test_html_report_includes_seo_columns(tmp_path):
    store_path = tmp_path / "keywords.json"
    markdown = generate_indie_report(
        SAMPLE["product_hunt"], SAMPLE["toolify"], SAMPLE["ai_tools"],
        SAMPLE["chrome_extensions"], SAMPLE["github"], SAMPLE["hackernews"],
        enrichment_path=store_path,
    )
    html = generate_indie_html(markdown, SAMPLE, enrichment_path=store_path)

    assert "SEO Opportunity Score" in html
    assert "Market Demand Gate" in html
    # the SEO status itself is rendered in the cluster cards
    assert "NOT_CHECKED" in html


def test_rejected_keyword_disappears_from_the_default_checklist(tmp_path):
    store_path = tmp_path / "keywords.json"
    data_dir = tmp_path / "no_history"

    clusters, store = _sample_clusters(store_path, data_dir)
    checklist = build_semrush_checklist(clusters, enrichment=store)
    assert checklist, "the sample day should produce candidates"
    target = checklist[0]

    enrichment_store.reject_keyword(
        store, target["cluster_id"], target["keyword"], reason="too broad", path=store_path
    )

    store_after = enrichment_store.load_store(store_path)
    clusters_after, _ = _sample_clusters(store_path, data_dir)
    checklist_after = build_semrush_checklist(clusters_after, enrichment=store_after)

    assert target["keyword"] not in {entry["keyword"] for entry in checklist_after}
    record = enrichment_store.get_record(store_after, target["cluster_id"], target["keyword"])
    assert record["status"] == enrichment_store.STATUS_REJECTED
    assert record["rejection_reason"] == "too broad"


def test_checked_keyword_disappears_unless_explicitly_requested(tmp_path):
    store_path = tmp_path / "keywords.json"
    data_dir = tmp_path / "no_history"

    clusters, store = _sample_clusters(store_path, data_dir)
    checklist = build_semrush_checklist(clusters, enrichment=store)
    assert checklist
    target = checklist[0]

    enrichment_store.upsert_metrics(
        store, target["cluster_id"], target["keyword"],
        {"us_volume": 1200, "global_volume": 3000, "kd": 20, "weak_serp": "yes"},
        path=store_path,
    )

    store_after = enrichment_store.load_store(store_path)
    clusters_after, _ = _sample_clusters(store_path, data_dir)

    default_list = build_semrush_checklist(clusters_after, enrichment=store_after)
    assert target["keyword"] not in {entry["keyword"] for entry in default_list}

    explicit = build_semrush_checklist(
        clusters_after, enrichment=store_after, include_checked=True
    )
    assert target["keyword"] in {entry["keyword"] for entry in explicit}


def test_enrichment_moves_a_cluster_from_not_checked_to_validated(tmp_path):
    store_path = tmp_path / "keywords.json"
    data_dir = tmp_path / "no_history"

    clusters, _ = _sample_clusters(store_path, data_dir)
    assert all(c["seo_score_status"] == "NOT_CHECKED" for c in clusters)
    assert all(c["market_demand_gate"] == "UNKNOWN" for c in clusters)

    store = enrichment_store.load_store(store_path)
    cluster_id = clusters[0]["cluster_id"]
    for index, (keyword, us, kd) in enumerate([
        ("tattoo generator", 1200, 20),
        ("tattoo stencil generator", 500, 15),
        ("tattoo idea generator", 300, 30),
    ]):
        enrichment_store.upsert_metrics(
            store, cluster_id, keyword,
            {"us_volume": us, "global_volume": us * 2, "kd": kd, "weak_serp": True},
            path=store_path,
        )

    clusters_after, _ = _sample_clusters(store_path, data_dir)
    enriched = [c for c in clusters_after if c["cluster_id"] == cluster_id][0]

    assert enriched["seo_score_status"] == "VALIDATED"
    assert enriched["market_demand_gate"] == "PASS"
    assert enriched["seo_score"] > 0
    assert len(enriched["checked_keywords"]) == 3


def test_demo_semrush_values_never_reach_production_output(tmp_path):
    store_path = tmp_path / "keywords.json"       # empty store, like production
    report = generate_indie_report(
        SAMPLE["product_hunt"], SAMPLE["toolify"], SAMPLE["ai_tools"],
        SAMPLE["chrome_extensions"], SAMPLE["github"], SAMPLE["hackernews"],
        enrichment_path=store_path,
    )

    for demo_value in ["18100", "28900", "1300", "880"]:
        assert demo_value not in report
    assert "random art prompt generator" not in report
    assert "excel consistency checker" not in report


# ---------------------------------------------------------------------------
# Phase 4: verdict layer in the report
# ---------------------------------------------------------------------------

def _report_with_stores(tmp_path, record_verdicts=False):
    keyword_path = tmp_path / "keywords.json"
    validation_path = tmp_path / "evidence.json"
    report = generate_indie_report(
        SAMPLE["product_hunt"], SAMPLE["toolify"], SAMPLE["ai_tools"],
        SAMPLE["chrome_extensions"], SAMPLE["github"], SAMPLE["hackernews"],
        enrichment_path=keyword_path, validation_path=validation_path,
        record_verdicts=record_verdicts,
    )
    return report, validation_path


def test_report_includes_top_opportunities_and_verdicts(tmp_path):
    report, _ = _report_with_stores(tmp_path)

    assert "## Top Opportunities Today" in report
    assert "**Verdict:**" in report
    assert "Opportunity Score" in report
    assert "Substitution risk" in report
    assert "Primary acquisition" in report
    assert "Monetization" in report
    assert "Not BUILD because" in report
    assert "Next actions" in report


def test_no_build_is_shown_as_expected_default(tmp_path):
    report, _ = _report_with_stores(tmp_path)
    assert "No opportunity met the BUILD bar today" in report


def test_html_report_includes_verdict_content(tmp_path):
    report, validation_path = _report_with_stores(tmp_path)
    html = generate_indie_html(
        report, SAMPLE,
        enrichment_path=tmp_path / "keywords.json",
        validation_path=validation_path,
    )

    assert "Top Opportunities Today" in html
    assert "Verdict" in html
    assert "Opportunity" in html
    assert "Next actions" in html


def test_report_generation_does_not_write_verdicts_by_default(tmp_path):
    _, validation_path = _report_with_stores(tmp_path, record_verdicts=False)
    assert not validation_path.exists()


def _verdict_history(validation_path):
    from storage import validation_store

    return validation_store.load_store(validation_path)["verdict_history"]


def test_verdict_history_is_recorded_only_when_enabled(tmp_path):
    _, validation_path = _report_with_stores(tmp_path, record_verdicts=True)
    history = _verdict_history(validation_path)
    assert history, "the first run should record at least one verdict"

    _report_with_stores(tmp_path, record_verdicts=True)
    assert len(_verdict_history(validation_path)) == len(history), \
        "unchanged verdicts must not append history"
