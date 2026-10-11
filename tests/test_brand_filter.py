"""Brand filtering + keyword maturity tests (Phase 5, Steps 1-3)."""

from analyzers.brand_filter import brand_tokens
from analyzers.keyword_candidates import build_semrush_checklist
from analyzers.keyword_quality import (
    MATURITY_AWKWARD,
    MATURITY_BRAND,
    MATURITY_BROAD,
    MATURITY_NICHE,
    is_awkward_phrase,
    keyword_maturity,
)


def _product(name, description="", source="product_hunt", index=0):
    return {
        "name": name,
        "description": description,
        "_source": source,
        "link": f"https://example.com/{source}-{index}",
    }


def _keywords(cluster):
    return [c["keyword"] for c in cluster.get("keyword_candidates", [])]


# --- structural brand detection -------------------------------------------

def test_monica_is_recognised_as_a_brand_token():
    assert "monica" in brand_tokens("Monica: All-In-One AI Assist & Smartest  AI Agent")


def test_gptzero_is_recognised_as_a_brand_token():
    assert "gptzero" in brand_tokens("GPTZero: AI Detection & Writing Replay")


def test_camel_case_product_name_is_a_brand_token():
    assert "tattoogenie" in brand_tokens("TattooGenie AI Tattoo Generator")
    assert "harpa" in brand_tokens("HARPA AI: Web Automation with ChatGPT, Claude, Gemini, Grok")


def test_category_words_are_never_brand_tokens():
    for name in ["Video Summarizer", "Tattoo Generator", "Prompt Generator",
                 "Photo Location Finder", "BPM Finder"]:
        assert brand_tokens(name) == [], name


# --- keywords: brand names must not leak ----------------------------------

def test_monica_video_summarizer_keeps_only_the_category_keyword(cluster_builder):
    clusters = cluster_builder([
        _product("Monica Video Summarizer", "Summarize any video with AI.", index=1),
    ])
    keywords = [k for c in clusters for k in _keywords(c)]

    assert "video summarizer" in keywords
    assert not any("monica" in keyword for keyword in keywords)


def test_gptzero_ai_detector_keyword_has_no_brand(cluster_builder):
    clusters = cluster_builder([
        _product("GPTZero AI Detector", "Detect AI written text.", index=2),
    ])
    keywords = [k for c in clusters for k in _keywords(c)]

    assert "ai detector" in keywords
    assert not any("gptzero" in keyword for keyword in keywords)


def test_tattoogenie_brand_is_stripped_but_tattoo_generator_remains(cluster_builder):
    clusters = cluster_builder([
        _product("TattooGenie AI Tattoo Generator", "Generate tattoo designs with AI.", index=3),
    ])
    keywords = [k for c in clusters for k in _keywords(c)]

    assert "tattoo generator" in keywords
    assert "ai tattoo generator" in keywords
    assert not any("tattoogenie" in keyword for keyword in keywords)


def test_prompt_generator_remains_valid(cluster_builder):
    clusters = cluster_builder([
        _product("Prompt Generator", "Generate writing prompts for stories.", index=4),
    ])
    keywords = [k for c in clusters for k in _keywords(c)]

    assert "prompt generator" in keywords
    assert keyword_maturity("prompt generator") == MATURITY_NICHE


# --- awkward phrase detection ---------------------------------------------

def test_awkward_phrases_are_rejected():
    for phrase in ["monica all one summarizer", "shippedit me analyzer",
                   "ai ai video generator", "free online free checker",
                   "checker tool", "free checker"]:
        assert is_awkward_phrase(phrase) or keyword_maturity(phrase) != MATURITY_NICHE, phrase
        assert keyword_maturity(phrase) in (MATURITY_AWKWARD, MATURITY_BRAND), phrase


def test_awkward_phrase_reasons_are_deterministic():
    assert is_awkward_phrase("ai ai video generator")          # repeated token
    assert is_awkward_phrase("free online free checker")       # stacked modifiers
    assert is_awkward_phrase("monica all one summarizer")      # artifact bigram
    assert is_awkward_phrase("shippedit me analyzer")          # dangling "me"
    assert not is_awkward_phrase("video summarizer")
    assert not is_awkward_phrase("tattoo stencil generator")


# --- maturity classification ----------------------------------------------

def test_niche_and_broad_maturity_labels():
    assert keyword_maturity("tattoo generator") == MATURITY_NICHE
    assert keyword_maturity("excel formula checker") == MATURITY_NICHE
    assert keyword_maturity("bpm finder") == MATURITY_NICHE
    assert keyword_maturity("video summarizer") == MATURITY_BROAD
    assert keyword_maturity("ai detector") == MATURITY_BROAD
    assert keyword_maturity("seo analyzer") == MATURITY_BROAD
    assert keyword_maturity("harpa ai summarizer", None, ["harpa"]) == MATURITY_BRAND


def test_brand_and_awkward_never_reach_the_checklist(cluster_builder):
    clusters = cluster_builder([
        _product("Monica: All-In-One AI Assist & Smartest  AI Agent",
                 "One stop AI Assistant: Chat, Write, Translate, Summarize.", index=5),
        _product("HARPA AI: Web Automation with ChatGPT, Claude",
                 "Free AI sidebar to automate, monitor prices, summarize & write.", index=6),
    ])
    checklist = build_semrush_checklist(clusters)

    for entry in checklist:
        assert entry["maturity"] in ("NICHE", "BROAD")
        assert not any(token in entry["keyword"]
                       for token in ("monica", "harpa", "chatgpt", "claude"))


def test_cluster_exposes_brand_tokens(cluster_builder):
    clusters = cluster_builder([
        _product("Monica: All-In-One AI Assist", "Chat and summarize anything.", index=7),
    ])
    assert clusters[0]["brand_tokens"] == ["monica"]
