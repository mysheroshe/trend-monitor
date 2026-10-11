"""Shared fixtures for the Phase 1 test suite."""

import json
from pathlib import Path

import pytest


def _make_product(name, description="", source="toolify", **extra):
    """Build a minimal product dict in the shape the collectors produce."""
    product = {"name": name, "description": description, "_source": source}
    product.update(extra)
    return product


@pytest.fixture
def product_factory():
    return _make_product


@pytest.fixture
def rank_suitable():
    """Group products by source and run the Phase 1 pipeline on them."""
    from analyzers.indie_analyzer import rank_products

    def _rank(products):
        groups = {}
        for product in products:
            groups.setdefault(product.get("_source", "toolify"), []).append(product)
        suitable, _ = rank_products(groups)
        return suitable

    return _rank


@pytest.fixture
def cluster_builder(rank_suitable, tmp_path):
    """Build ranked clusters with keyword candidates attached.

    History defaults to an empty directory so unit tests are deterministic.
    """
    from analyzers.clustering import analyze_clusters
    from analyzers.keyword_candidates import attach_keyword_candidates

    empty_history = tmp_path / "no_history"

    def _build(products, data_dir=None, today=None):
        kwargs = {"data_dir": empty_history if data_dir is None else data_dir}
        if today is not None:
            kwargs["today"] = today
        clusters = analyze_clusters(rank_suitable(products), **kwargs)
        return attach_keyword_candidates(clusters)

    return _build


@pytest.fixture
def tattoo_products():
    """The cluster example from the Phase 2 brief."""
    return [
        {"name": "AI Tattoo Generator", "description": "Generate tattoo designs from a text prompt.",
         "_source": "toolify", "link": "https://example.com/tattoo-1"},
        {"name": "Tattoo Generator AI", "description": "AI tattoo creator for artists.",
         "_source": "toolify", "link": "https://example.com/tattoo-2"},
        {"name": "Free Tattoo Maker", "description": "Create custom tattoo art online, free.",
         "_source": "product_hunt", "link": "https://example.com/tattoo-3"},
        {"name": "Sleeve Tattoo AI", "description": "Sleeve tattoo ideas.",
         "_source": "product_hunt", "link": "https://example.com/tattoo-4"},
    ]


@pytest.fixture
def audio_products():
    """The audio example: related but deliberately distinct search intents."""
    return [
        {"name": "BPM Finder", "description": "Find the BPM of any song.",
         "_source": "product_hunt", "link": "https://example.com/audio-1"},
        {"name": "Song Key Finder", "description": "Detect the musical key of a track.",
         "_source": "product_hunt", "link": "https://example.com/audio-2"},
        {"name": "Pitch Changer", "description": "Shift the pitch of audio files.",
         "_source": "ai_tools", "link": "https://example.com/audio-3"},
        {"name": "Vocal Remover", "description": "Remove vocals from a song.",
         "_source": "ai_tools", "link": "https://example.com/audio-4"},
    ]


@pytest.fixture
def demo_products():
    """The three demo clusters used by the Phase 3 offline demonstration."""
    return [
        {"name": "AI Tattoo Generator", "description": "Generate tattoo designs from a text prompt.",
         "_source": "toolify", "link": "https://example.com/demo-tattoo-1"},
        {"name": "Tattoo Stencil Generator", "description": "Create tattoo stencils.",
         "_source": "product_hunt", "link": "https://example.com/demo-tattoo-2"},
        {"name": "Random Tattoo Idea Generator", "description": "Random tattoo ideas.",
         "_source": "product_hunt", "link": "https://example.com/demo-tattoo-3"},
        {"name": "Excel Consistency Checker", "description": "Check spreadsheet formulas for consistency.",
         "_source": "product_hunt", "link": "https://example.com/demo-excel"},
        {"name": "Random Art Prompt Generator", "description": "Generate random art prompts.",
         "_source": "toolify", "link": "https://example.com/demo-prompt"},
    ]


@pytest.fixture
def demo_store_path(tmp_path):
    """A copy of the demo Semrush fixture (tests only - never production data)."""
    source = Path(__file__).resolve().parent / "fixtures" / "semrush_demo_enrichment.json"
    path = tmp_path / "demo_keywords.json"
    path.write_text(json.dumps(json.loads(source.read_text(encoding="utf-8"))), encoding="utf-8")
    return path


@pytest.fixture
def demo_clusters(cluster_builder, demo_products, demo_store_path):
    """The demo clusters with keyword candidates and SEO scores attached."""
    from analyzers.seo_score import attach_seo
    from storage import enrichment_store

    clusters = cluster_builder(demo_products)
    return attach_seo(clusters, enrichment_store.load_store(demo_store_path))


def _keyword(keyword, us=0, kd=0, weak=True, count=None):
    """A checked-keyword row in the shape produced by analyzers/seo_score.py."""
    return {
        "keyword": keyword,
        "us_volume": us,
        "global_volume": us * 2,
        "kd": kd,
        "weak_serp": weak,
        "weak_serp_count": count,
        "keyword_score": 0,
        "is_viable": us >= 100 and kd <= 49,
        "intent": keyword,
        "checked_at": "2026-10-11T00:00:00-07:00",
    }


@pytest.fixture
def keyword_factory():
    return _keyword


@pytest.fixture
def cluster_factory(keyword_factory):
    """Build a Phase 3 shaped cluster dict without running the whole pipeline."""
    def _make(cluster_id="demo-cluster", label="Demo Tools", domain=None, function=None,
              solo=80, cluster_score=80, seo_score=0, seo_status="NOT_CHECKED",
              gate="UNKNOWN", keywords=(), members=(), sources=("toolify",),
              orchard=6, days_seen=1, strongest_confidence="High"):
        member_list = list(members)
        return {
            "cluster_id": cluster_id,
            "cluster_key": cluster_id,
            "cluster_label": label,
            "domain": domain,
            "function": function,
            "member_count": max(len(member_list), 1),
            "source_diversity": len(sources),
            "member_sources": list(sources),
            "max_solo_builder_score": solo,
            "cluster_score": cluster_score,
            "tool_orchard_potential": orchard,
            "seo_score": seo_score,
            "seo_score_status": seo_status,
            "market_demand_gate": gate,
            "checked_keywords": [keyword_factory(*kw) for kw in keywords],
            "keyword_candidates": [{"keyword": kw[0]} for kw in keywords],
            "days_seen": days_seen,
            "strongest_source_confidence": strongest_confidence,
            "member_names": [m.get("name", "") for m in member_list],
            "members": member_list,
        }

    return _make
