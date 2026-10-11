"""Source typing / novelty / discovery quality tests (Phase 5, Steps 4-7, 10)."""

from analyzers.indie_analyzer import rank_products
from analyzers.source_quality import (
    DQ_HIGH,
    DQ_LOW,
    GH_HIGH,
    GH_LOW,
    HN_DEMAND,
    HN_NEWS,
    HN_PRODUCT,
    HN_UNKNOWN,
    NOVELTY_HIGH,
    NOVELTY_LOW,
    classify_hn_item,
    discovery_quality,
    github_product_likeness,
    novelty_signal,
    source_health,
)


def _hn(title, url="https://example.com/x"):
    return {"title": title, "url": url, "_source": "hackernews"}


def _gh(name, description, source="github"):
    return {"name": name, "description": description, "_source": source}


# --- Hacker News typing ----------------------------------------------------

def test_show_hn_product_is_accepted():
    kind, _ = classify_hn_item(_hn("Show HN: I built a tiny offline PDF stamper"))
    assert kind == HN_PRODUCT
    assert discovery_quality(_hn("Show HN: I built a tiny offline PDF stamper"))[0] == DQ_HIGH


def test_launch_hn_product_is_accepted():
    kind, _ = classify_hn_item(_hn("Launch HN: Sitefire (YC W26) - Automating account research"))
    assert kind == HN_PRODUCT


def test_ask_hn_is_demand_evidence_not_a_product():
    kind, why = classify_hn_item(_hn("Ask HN: What do you use for local transcription?"))
    assert kind == HN_DEMAND
    assert "demand" in why
    assert discovery_quality(_hn("Ask HN: What do you use for local transcription?"))[0] == DQ_LOW


def test_news_and_incident_posts_are_excluded():
    traffic = _hn("Sudden drop in Cloudflare bot traffic after strike on Yandex datacenter",
                  "https://radar.cloudflare.com/bots/as13238")
    kind, _ = classify_hn_item(traffic)
    assert kind == HN_NEWS
    assert discovery_quality(traffic)[0] == DQ_LOW

    blog = _hn("I paid people to try and follow my README",
               "https://shkspr.mobi/blog/2026/10/i-paid-people-to-try-and-follow-my-readme/")
    assert classify_hn_item(blog)[0] == HN_NEWS
    assert classify_hn_item(_hn("IRCv3"))[0] == HN_UNKNOWN


def test_only_product_hn_items_enter_the_ranking():
    groups = {"hackernews": [
        _hn("Show HN: I built a CSV diff tool", "https://example.com/1"),
        _hn("Ask HN: how do I find a good podcast editor?", "https://example.com/2"),
        _hn("Sudden drop in Cloudflare bot traffic after strike on Yandex datacenter",
            "https://example.com/3"),
        _hn("LineageOS 24.0", "https://example.com/4"),
    ]}
    suitable, filtered = rank_products(groups)

    assert [p["name"] for p in suitable] == ["Show HN: I built a CSV diff tool"]
    assert len(filtered) == 3
    assert any("demand signal" in p["filter_reason"] for p in filtered)
    assert all("hn_content_type" in p for p in suitable + filtered)


# --- GitHub product likeness ----------------------------------------------

def test_github_library_is_low_product_likeness():
    item = _gh("morluto/rea", "Reverse engineer anything with agents, from app behavior down to native binaries.")
    assert github_product_likeness(item)[0] == GH_LOW
    assert discovery_quality(item)[0] == DQ_LOW

    sdk = _gh("someone/fast-yaml", "A fast library for parsing YAML. pip install fast-yaml")
    assert github_product_likeness(sdk)[0] == GH_LOW


def test_github_end_user_utility_is_high_product_likeness():
    item = _gh("bilawalsidhu/gods-eye-view",
               "A spy satellite simulator in your browser, except the data is real.")
    assert github_product_likeness(item)[0] == GH_HIGH
    assert discovery_quality(item)[0] in (DQ_HIGH, "MEDIUM")

    port = _gh("boykopovar/AnyPS5", "Tool for automatic PS5 executables porting to Linux and Windows")
    assert github_product_likeness(port)[0] == GH_HIGH


def test_github_low_likeness_items_are_filtered_out():
    groups = {"github": [
        _gh("morluto/rea", "Reverse engineer anything with agents, down to native binaries."),
        _gh("boykopovar/AnyPS5", "Tool for automatic PS5 executables porting to Linux and Windows"),
    ]}
    suitable, filtered = rank_products(groups)

    assert [p["name"] for p in suitable] == ["boykopovar/AnyPS5"]
    assert "low" in filtered[0]["filter_reason"].lower()


# --- Novelty ---------------------------------------------------------------

def test_toolify_new_page_gets_high_novelty():
    assert novelty_signal({"name": "X", "category": "Just launched", "_source": "toolify"})[0] == NOVELTY_HIGH
    assert novelty_signal({"name": "Y", "_source": "toolify"})[0] == NOVELTY_HIGH


def test_mature_high_traffic_tool_is_not_high_novelty():
    mature = {"name": "Claude 2", "monthly_visit": "290.3M", "growth_rate": "2%", "_source": "toolify"}
    level, why = novelty_signal(mature)
    assert level == NOVELTY_LOW
    assert "mature" in why

    growing = {"name": "New thing", "monthly_visit": "1.2M", "growth_rate": "1054%", "_source": "toolify"}
    assert novelty_signal(growing)[0] in (NOVELTY_HIGH, "MEDIUM")


def test_chrome_extension_novelty_follows_install_base():
    big = {"name": "Monica", "users": "3,000,000 users", "_source": "chrome_extensions"}
    small = {"name": "Tiny Tool", "users": "900 users", "_source": "chrome_extensions"}
    assert novelty_signal(big)[0] == NOVELTY_LOW
    assert novelty_signal(small)[0] == NOVELTY_HIGH


# --- Source health ---------------------------------------------------------

def test_source_health_counts_fetched_accepted_filtered():
    first_run = __import__("json").loads(
        (__import__("pathlib").Path(__file__).parent
         / "fixtures" / "first_run_2026-10-11.json").read_text(encoding="utf-8")
    )
    groups = {
        "product_hunt": first_run["product_hunt"],
        "toolify": first_run["toolify"],
        "ai_tools": first_run["ai_tools"],
        "chrome_extensions": first_run["chrome_extensions"],
        "github": first_run["github_trending"],
        "hackernews": first_run["hacker_news"],
    }
    suitable, filtered = rank_products({k: list(v) for k, v in groups.items()})
    rows = {row["source"]: row for row in source_health(groups, suitable, filtered,
                                                         errors={"ai_tools": "request failed: 403"})}

    assert rows["product_hunt"]["fetched"] == 5
    assert rows["product_hunt"]["accepted"] == 5
    assert rows["toolify"]["status"] == "empty"
    assert rows["ai_tools"]["status"] == "error"
    assert "403" in rows["ai_tools"]["error"]
    assert rows["hackernews"]["accepted"] == 1      # only the Show HN item
    assert "news discussion" in rows["hackernews"]["note"] or "unknown" in rows["hackernews"]["note"]
    assert rows["github"]["accepted"] == 2
    assert "low" in rows["github"]["note"]
