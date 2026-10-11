"""Regression test built from the first real production run (2026-10-11)."""

import json
from pathlib import Path

from analyzers.clustering import analyze_clusters
from analyzers.indie_analyzer import rank_products
from analyzers.keyword_candidates import attach_keyword_candidates, build_semrush_checklist
from analyzers.keyword_quality import MATURITY_BROAD, keyword_maturity
from analyzers.source_quality import HN_PRODUCT, classify_hn_item

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "first_run_2026-10-11.json"

BRAND_TOKENS = {"monica", "harpa", "gptzero", "sider", "chatgpt", "claude",
                "gemini", "grok", "deepseek"}


def _groups():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {
        "product_hunt": data["product_hunt"],
        "toolify": data["toolify"],
        "ai_tools": data["ai_tools"],
        "chrome_extensions": data["chrome_extensions"],
        "github": data["github_trending"],
        "hackernews": data["hacker_news"],
    }


def _pipeline(tmp_path):
    groups = _groups()
    suitable, filtered = rank_products({k: list(v) for k, v in groups.items()})
    clusters = attach_keyword_candidates(analyze_clusters(suitable, data_dir=tmp_path))
    return suitable, filtered, clusters, groups


def test_first_run_mature_brands_remain_as_market_evidence(tmp_path):
    suitable, _, _, _ = _pipeline(tmp_path)
    names = " | ".join(product.get("name", "") for product in suitable)

    assert "HARPA" in names
    assert "Monica" in names
    assert "GPTZero" in names
    assert "Sider" in names


def test_first_run_brand_names_never_become_keyword_candidates(tmp_path):
    _, _, clusters, _ = _pipeline(tmp_path)

    for cluster in clusters:
        for candidate in cluster.get("keyword_candidates", []):
            for token in BRAND_TOKENS:
                assert token not in candidate["keyword"], candidate["keyword"]


def test_first_run_hn_discussion_does_not_enter_the_ranking(tmp_path):
    suitable, filtered, _, groups = _pipeline(tmp_path)

    hn_kept = [p for p in suitable if p.get("_source") == "hackernews"]
    hn_types = {classify_hn_item(item)[0] for item in groups["hackernews"]}

    assert all(classify_hn_item(item)[0] == HN_PRODUCT for item in hn_kept)
    assert "NEWS_DISCUSSION" in hn_types
    traffic = [p for p in filtered if "Cloudflare" in (p.get("name") or "")]
    assert traffic and "article/news" in traffic[0]["filter_reason"]


def test_first_run_generic_mature_phrases_are_broad(tmp_path):
    assert keyword_maturity("video summarizer") == MATURITY_BROAD
    assert keyword_maturity("seo analyzer") == MATURITY_BROAD


def test_first_run_checklist_only_contains_clean_tool_intent(tmp_path):
    _, _, clusters, _ = _pipeline(tmp_path)
    checklist = build_semrush_checklist(clusters)

    assert checklist, "the first run should still yield a few usable keywords"
    for entry in checklist:
        assert entry["maturity"] in ("NICHE", "BROAD")
        assert "monica" not in entry["keyword"]
        assert "shippedit" not in entry["keyword"]
        assert entry["keyword"].strip() == entry["keyword"]


def test_first_run_news_and_library_items_are_filtered(tmp_path):
    _, filtered, _, _ = _pipeline(tmp_path)
    reasons = {p.get("name"): p["filter_reason"] for p in filtered}

    assert any("Cloudflare" in (name or "") for name in reasons)
    assert any("morluto/rea" == name for name in reasons)
    assert any("low" in reason.lower() or "likeness" in reason.lower()
               for reason in reasons.values())
