"""Normalization and de-duplication tests (Step 6)."""

from analyzers import indie_analyzer as ia


def test_toolify_new_trending_duplicate_is_deduplicated():
    all_products = {
        "toolify": [
            {
                "name": "Claude 2",
                "description": "An AI assistant from Anthropic.",
                "category": "Just launched",
                "link": "https://www.toolify.ai/tool/claude-2",
            },
            {
                "name": "Claude 2",
                "description": "An AI assistant from Anthropic.",
                "monthly_visit": "290.3M",
                "growth_rate": "43.07%",
                "link": "https://www.toolify.ai/tool/claude-2",
            },
        ]
    }
    normalized = ia.normalize_products(all_products)

    assert len(normalized) == 1
    # the richer (trending) record contributes its extra fields
    assert normalized[0]["monthly_visit"] == "290.3M"
    assert normalized[0]["growth_rate"] == "43.07%"


def test_duplicate_urls_are_dropped():
    all_products = {
        "toolify": [
            {"name": "Alpha", "link": "https://example.com/x/y/"},
            {"name": "Beta", "link": "https://example.com/x/y"},
        ]
    }
    assert len(ia.normalize_products(all_products)) == 1


def test_names_are_normalized_for_dedup():
    all_products = {
        "toolify": [
            {"name": "Claude 2!", "link": "https://a"},
            {"name": "  claude   2 ", "link": "https://b"},
        ]
    }
    assert len(ia.normalize_products(all_products)) == 1


def test_normalize_name_strips_punctuation_and_case():
    assert ia.normalize_name("Gmail: Joy (Beta)!") == "gmail joy beta"
    assert ia.normalize_name("") == ""


def test_normalize_url_ignores_scheme_and_fragment():
    assert ia.normalize_url("HTTPS://Example.com/a/#frag") == "example.com/a"
    assert ia.normalize_url("") == ""
