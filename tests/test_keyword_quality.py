"""Keyword quality tightening tests (Phase 3, Step 3)."""

from analyzers.keyword_candidates import generate_keyword_candidates
from analyzers.keyword_quality import (
    is_generic_phrase,
    member_derived_allowed,
    passes_quality,
)

GENERIC_PHRASES = [
    "checker tool",
    "free checker",
    "code editor",
    "free code editor",
    "online code editor",
    "ai tool",
    "productivity tool",
    "business tool",
]

USEFUL_PHRASES = [
    "tattoo generator",
    "prompt generator",
    "bpm finder",
    "tattoo stencil generator",
    "song key finder",
    "excel consistency checker",
    "photo location finder",
]


def test_generic_low_value_phrases_are_deprioritised():
    for phrase in GENERIC_PHRASES:
        assert is_generic_phrase(phrase), phrase
        assert not passes_quality(phrase, {}), phrase


def test_useful_head_terms_are_kept():
    for phrase in USEFUL_PHRASES:
        assert not is_generic_phrase(phrase), phrase
        assert passes_quality(phrase, {}), phrase


def test_member_derived_keywords_require_a_domain_anchor():
    assert not member_derived_allowed({"member_count": 1, "domain": None})
    assert not member_derived_allowed({"member_count": 1, "domain": "code"})
    assert member_derived_allowed({"member_count": 1, "domain": "audio"})
    assert member_derived_allowed({"member_count": 2, "domain": None})


def test_unclustered_product_offers_no_keywords():
    cluster = {
        "cluster_id": "single-general-general-abc",
        "cluster_label": "KiloClaw (unclustered)",
        "cluster_key": "single:general:general:abc",
        "domain": None,
        "function": None,
        "member_count": 1,
        "member_names": ["KiloClaw"],
        "members": [{"name": "KiloClaw", "_source": "toolify"}],
        "source_diversity": 1,
        "cluster_score": 70,
    }
    assert generate_keyword_candidates(cluster) == []


def test_function_only_singleton_does_not_emit_product_name_keywords(cluster_builder):
    """The Phase 2 sample produced 'wa workflow enhancer' - that must not return."""
    clusters = cluster_builder([
        {"name": "WA WorkFlow", "description": "Boost workflow efficiency for teams.",
         "_source": "chrome_extensions", "link": "https://example.com/wa"},
    ])
    keywords = [k["keyword"] for c in clusters for k in c["keyword_candidates"]]

    assert "wa workflow enhancer" not in keywords
    assert not any("wa" == token for keyword in keywords for token in keyword.split())


def test_generic_domain_templates_are_not_generated(cluster_builder):
    clusters = cluster_builder([
        {"name": "Code Editor Pro", "description": "Edit code in the browser.",
         "_source": "toolify", "link": "https://example.com/code-editor"},
    ])
    keywords = [k["keyword"] for c in clusters for k in c["keyword_candidates"]]

    assert "code editor" not in keywords
    assert "free code editor" not in keywords


def test_niche_cluster_keeps_specific_keywords(cluster_builder, tattoo_products):
    clusters = cluster_builder(tattoo_products)
    keywords = [k["keyword"] for c in clusters for k in c["keyword_candidates"]]

    assert "tattoo generator" in keywords
    assert "tattoo stencil generator" not in keywords      # not a product in this fixture
    assert all("tattoo" in keyword for keyword in keywords)
