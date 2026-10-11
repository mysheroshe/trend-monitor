"""Hard-filter and data-quality tests (Step 3 and Step 6)."""

from analyzers import indie_analyzer as ia


def test_enterprise_crm_is_filtered(product_factory):
    crm = product_factory(
        "Pipeline CRM",
        "CRM for sales teams to manage the sales pipeline and reduce churn.",
        source="product_hunt",
        link="https://crm",
    )
    suitable, filtered = ia.filter_unsuitable_products({"product_hunt": [crm]})

    assert suitable == []
    assert filtered and "CRM" in filtered[0]["filter_reason"]


def test_two_sided_marketplace_is_penalized_or_filtered(product_factory):
    market = product_factory(
        "FreelanceHub",
        "A two-sided marketplace connecting freelancers with clients.",
        source="toolify",
        link="https://marketplace",
    )
    suitable, filtered = ia.filter_unsuitable_products({"toolify": [market]})

    if suitable:
        assert ia.score_product(suitable[0])["total_score"] < 60
    else:
        assert "marketplace" in filtered[0]["filter_reason"].lower()


def test_generic_words_alone_are_not_filtered(product_factory):
    """'analytics', 'platform' and 'AI' must not over-filter ordinary products."""
    candidates = [
        product_factory("Personal Analytics Dashboard", "A personal analytics dashboard for your own habits."),
        product_factory("AI Photo Enhancer", "An AI photo enhancer for phone photos."),
        product_factory("Solo Creator Platform", "A lightweight platform for solo creators to share their work."),
    ]
    suitable, filtered = ia.filter_unsuitable_products({"toolify": candidates})

    assert len(suitable) == 3
    assert filtered == []


def test_hackernews_articles_are_excluded_from_ranking():
    article = {"title": "Grieving the Loss of Details", "url": "https://news.ycombinator.com/item?id=1"}
    show = {"title": "Show HN: I built a JSON formatter", "url": "https://news.ycombinator.com/item?id=2"}

    suitable, filtered = ia.filter_unsuitable_products({"hackernews": [article, show]})

    kept = [p.get("name") for p in suitable]
    assert any("JSON formatter" in (name or "") for name in kept)
    assert all("Grieving" not in (name or "") for name in kept)
    assert any("article/news" in f["filter_reason"] for f in filtered)


def test_hackernews_product_item_is_kept():
    show = {"title": "Show HN: Tiny self-hosted dashboard tool", "url": "https://news.ycombinator.com/item?id=3"}
    suitable, _ = ia.filter_unsuitable_products({"hackernews": [show]})
    assert len(suitable) == 1


def test_hackernews_launch_hn_is_treated_as_a_product():
    """'Launch HN:' posts are product launches, not news articles."""
    launch = {
        "title": "Launch HN: Sitefire (YC W26) - Automating account research",
        "url": "https://news.ycombinator.com/item?id=4",
    }
    suitable, filtered = ia.filter_unsuitable_products({"hackernews": [launch]})
    assert len(suitable) == 1
    assert filtered == []


def test_github_library_is_filtered():
    library = {
        "name": "someone/cool-lib",
        "description": "A fast library for parsing YAML. npm install cool-lib",
    }
    suitable, filtered = ia.filter_unsuitable_products({"github": [library]})

    assert suitable == []
    assert "library" in filtered[0]["filter_reason"].lower()


def test_github_product_still_passes():
    product = {
        "name": "someone/csv-studio",
        "description": "A self-hosted web app that turns spreadsheets into charts.",
    }
    suitable, _ = ia.filter_unsuitable_products({"github": [product]})
    assert len(suitable) == 1
