"""Final decision layer tests (Phase 4, Steps 2-7, 10-11, 16)."""

from analyzers import verdict as v
from config import verdict_weights as VW
from storage import validation_store as vs


def _member(name, description="", source="toolify"):
    return {"name": name, "description": description, "_source": source}


def _strong_cluster(cluster_factory, **overrides):
    """A cluster that satisfies everything except the monetization evidence."""
    kwargs = dict(
        cluster_id="pdf-conversion", label="PDF Converter Tools",
        domain="pdf", function="conversion",
        solo=85, cluster_score=90, seo_score=75, seo_status="VALIDATED", gate="PASS",
        keywords=[("pdf converter", 2000, 18, True, 3)],
        members=[_member("PDF Converter", "Convert PDF files. Runs in your browser.")],
        orchard=8, days_seen=5, sources=("toolify", "product_hunt"),
    )
    kwargs.update(overrides)
    return cluster_factory(**kwargs)


# ---------------------------------------------------------------------------
# Substitution risk (Step 5)
# ---------------------------------------------------------------------------

def test_substitution_risk_levels(cluster_factory):
    wrapper = cluster_factory(domain=None, function="summarization",
                              members=[_member("Summarizer", "An AI summarizer wrapper.")])
    assert v.substitution_risk(wrapper)[0] == VW.SUBSTITUTION_SEVERE

    generic_writer = cluster_factory(domain=None, function="writing",
                                     members=[_member("AI Writer", "An AI writing assistant.")])
    assert v.substitution_risk(generic_writer)[0] == VW.SUBSTITUTION_SEVERE

    prompts = cluster_factory(domain="prompt", function="generation",
                              members=[_member("Prompt Generator", "Generate prompts.")])
    assert v.substitution_risk(prompts)[0] == VW.SUBSTITUTION_HIGH

    media = cluster_factory(domain="image", function="generation",
                            members=[_member("Image Generator", "Generate images.")])
    assert v.substitution_risk(media)[0] == VW.SUBSTITUTION_HIGH

    tattoo = cluster_factory(domain="tattoo", function="generation",
                             members=[_member("Tattoo Generator", "AI tattoo designs.")])
    assert v.substitution_risk(tattoo)[0] == VW.SUBSTITUTION_MEDIUM

    excel = cluster_factory(domain="spreadsheet", function="checking",
                            members=[_member("Excel Checker", "Check formulas.")])
    assert v.substitution_risk(excel)[0] == VW.SUBSTITUTION_LOW

    pdf = cluster_factory(domain="pdf", function="conversion",
                          members=[_member("PDF Converter", "Convert files in your browser.")])
    assert v.substitution_risk(pdf)[0] == VW.SUBSTITUTION_LOW

    assert v.substitution_risk(tattoo)[1]          # reasons are always provided


# ---------------------------------------------------------------------------
# Acquisition (Step 6)
# ---------------------------------------------------------------------------

def test_acquisition_channel_classification(cluster_factory):
    extension = cluster_factory(
        domain="productivity", function="tracking", sources=("chrome_extensions",),
        members=[_member("Focus Timer", "A chrome extension timer.", "chrome_extensions")])
    assert v.acquisition(extension)[0] == VW.CHANNEL_PLATFORM
    assert v.acquisition(extension)[1] == VW.ACQUISITION_FIT_STRONG

    social = cluster_factory(domain="meme", function="generation",
                             members=[_member("Meme Maker")])
    assert v.acquisition(social)[0] == VW.CHANNEL_SOCIAL

    developer = cluster_factory(domain="code", function="formatting", sources=("github",),
                                members=[_member("Formatter", "Developer tool.", "github")])
    assert v.acquisition(developer)[0] == VW.CHANNEL_COMMUNITY

    enterprise = cluster_factory(
        domain="spreadsheet", function="tracking",
        members=[_member("Ops Suite",
                         "Contact sales for pricing and dedicated implementation services.")])
    assert v.acquisition(enterprise)[0] == VW.CHANNEL_DIRECT_SALES
    assert v.acquisition(enterprise)[1] == VW.ACQUISITION_FIT_WEAK

    search_led = cluster_factory(domain="pdf", function="conversion",
                                 seo_status="VALIDATED", gate="PASS",
                                 members=[_member("PDF Converter")])
    assert v.acquisition(search_led)[0] == VW.CHANNEL_SEO
    assert v.acquisition(search_led)[1] == VW.ACQUISITION_FIT_STRONG

    bare = cluster_factory(domain=None, function=None)
    assert v.acquisition(bare)[0] == VW.CHANNEL_UNKNOWN
    assert v.acquisition(bare)[1] == VW.ACQUISITION_FIT_WEAK


def test_seo_is_not_assumed_for_every_tool(cluster_factory):
    """A non-search channel wins when the product is not search-led."""
    social = cluster_factory(domain="wallpaper", function="generation",
                             members=[_member("Wallpaper Maker")])
    assert v.acquisition(social)[0] != VW.CHANNEL_SEO


# ---------------------------------------------------------------------------
# Monetization (Step 7)
# ---------------------------------------------------------------------------

def test_monetization_model_and_confidence(cluster_factory):
    subscription = cluster_factory(
        domain="finance", function="tracking",
        members=[_member("Budget Tracker", "A subscription budgeting app.")])
    model, confidence, _ = v.monetization(subscription, None)
    assert model == "subscription"
    assert confidence == "HIGH"                     # subscription + recurring use

    credits = cluster_factory(domain="fortune_telling", function="generation",
                              members=[_member("Tarot Reader")])
    assert v.monetization(credits, None)[0] == "credits"

    one_time = cluster_factory(domain="pdf", function="conversion",
                               members=[_member("PDF Converter", "One-time purchase.")])
    assert v.monetization(one_time, None)[0] == "one-time payment"

    ads = cluster_factory(domain="education", function="generation",
                          members=[_member("Study Game", "Ad-supported study games.")])
    assert v.monetization(ads, None)[0] == "ads"
    assert v.monetization(ads, None)[1] == "LOW"

    enterprise = cluster_factory(
        domain=None, function="tracking",
        members=[_member("Ops Suite", "Contact sales for enterprise pricing.")])
    assert v.monetization(enterprise, None)[0] == "enterprise sales"
    assert v.monetization(enterprise, None)[1] == "LOW"

    freemium = cluster_factory(domain="tattoo", function="generation",
                               members=[_member("Tattoo Generator", "AI tattoo designs.")])
    assert v.monetization(freemium, None)[0] == "freemium"


def test_payment_signal_raises_monetization_confidence(cluster_factory):
    cluster = cluster_factory(domain="tattoo", function="generation",
                              members=[_member("Tattoo Generator", "AI tattoo designs.")])
    base = v.monetization(cluster, None)[1]
    evidence = {"positive_types": ["PAYMENT_SIGNAL"], "positive": 1, "negative": 0,
                "types": {"PAYMENT_SIGNAL": 1}}
    raised = v.monetization(cluster, evidence)[1]

    assert base == "LOW"
    assert raised == "MEDIUM"


def test_substitution_caps_monetization_confidence(cluster_factory):
    cluster = cluster_factory(
        domain=None, function="summarization",
        members=[_member("Summarizer", "A subscription AI summarizer.")])
    assert v.monetization(cluster, None)[1] != "HIGH"


# ---------------------------------------------------------------------------
# Opportunity Score (Step 10)
# ---------------------------------------------------------------------------

def test_opportunity_score_is_bounded_and_is_the_sum_of_its_parts(cluster_factory):
    cluster = _strong_cluster(cluster_factory, solo=100, seo_score=100,
                              keywords=[("best keyword", 20000, 5, True, 3)])
    evidence = {"positive_types": ["COMPETITOR", "PAYMENT_SIGNAL", "COMMUNITY_PAIN"],
                "positive": 3, "negative": 0, "types": {}}
    total, parts = v.opportunity_score(cluster, evidence)

    assert 0 <= total <= 100
    assert total == sum(parts.values())
    assert set(parts) == set(VW.WEIGHTS)


def test_low_cost_self_service_scores_better_than_costly_sales_led(cluster_factory):
    self_service = _strong_cluster(
        cluster_factory, cluster_id="self-service",
        members=[_member("PDF Converter", "Convert files in your browser. One-time purchase.")])
    sales_led = cluster_factory(
        cluster_id="sales-led", domain="video", function="generation", solo=85,
        seo_score=75, seo_status="VALIDATED", gate="PASS",
        keywords=[("video generator", 2000, 18, True, 3)],
        members=[_member("Video Suite",
                         "Contact sales. Dedicated implementation services. "
                         "Continuous inference with a proprietary dataset.")],
        days_seen=5, sources=("toolify", "product_hunt"))

    assert v.opportunity_score(self_service)[0] > v.opportunity_score(sales_led)[0]


# ---------------------------------------------------------------------------
# Verdict rules and hard gates (Steps 2-4, 11)
# ---------------------------------------------------------------------------

def test_fail_market_gate_blocks_build(cluster_factory):
    cluster = _strong_cluster(cluster_factory, gate="FAIL",
                              keywords=[("tiny keyword", 20, 5, True, None)])
    result = v.decide(cluster, None)

    assert result["verdict"] == VW.VERDICT_SKIP
    assert any("FAIL" in reason for reason in result["blocking_reasons"])


def test_severe_substitution_blocks_build(cluster_factory):
    cluster = _strong_cluster(
        cluster_factory, domain=None, function="summarization",
        members=[_member("AI Summarizer", "An AI summarizer wrapper.")])
    result = v.decide(cluster, None)

    assert result["verdict"] == VW.VERDICT_SKIP
    assert any("commodity" in reason for reason in result["blocking_reasons"])


def test_high_score_cannot_override_a_hard_blocker(cluster_factory):
    cluster = _strong_cluster(cluster_factory, solo=100, cluster_score=100,
                              seo_score=100, gate="FAIL", orchard=10,
                              keywords=[("tiny keyword", 20, 5, True, None)])
    result = v.decide(cluster, None)

    assert result["opportunity_score"] > 0        # a score exists ...
    assert result["verdict"] == VW.VERDICT_SKIP    # ... but the gate still wins


def test_enterprise_sales_heavy_opportunity_becomes_skip(cluster_factory):
    cluster = cluster_factory(
        domain=None, function="tracking", solo=90, cluster_score=90,
        seo_score=80, seo_status="VALIDATED", gate="PASS",
        keywords=[("crm software", 9000, 40, False, None)],
        members=[_member("Ops Suite",
                         "Contact sales for enterprise pricing. "
                         "Dedicated implementation services.")])
    result = v.decide(cluster, None)

    assert result["verdict"] == VW.VERDICT_SKIP
    assert any("sales" in reason or "service" in reason for reason in result["blocking_reasons"])


def test_negligible_demand_becomes_skip(cluster_factory):
    cluster = _strong_cluster(cluster_factory, seo_status="PARTIAL", gate="FAIL",
                              keywords=[("excel consistency checker", 20, 5, True, None)])
    assert v.decide(cluster, None)["verdict"] == VW.VERDICT_SKIP


def test_weak_early_trend_becomes_watch(cluster_factory):
    cluster = cluster_factory(solo=80, cluster_score=70, gate="UNKNOWN",
                              seo_status="NOT_CHECKED", days_seen=1)
    result = v.decide(cluster, None)

    assert result["verdict"] == VW.VERDICT_WATCH
    assert result["validation_gaps"]


def test_incomplete_evidence_defaults_to_test_not_build(cluster_factory):
    result = v.decide(_strong_cluster(cluster_factory), None)

    assert result["verdict"] == VW.VERDICT_TEST
    assert any("monetization evidence" in reason for reason in result["blocking_reasons"])
    assert result["validation_gaps"]


def test_build_requires_validation_evidence(cluster_factory):
    cluster = _strong_cluster(cluster_factory)
    store = vs.load_store(None)
    vs.add_evidence(store, cluster["cluster_id"], "COMPETITOR", "positive",
                    "Competing converters charge one-time fees and rank with weak domains")

    result = v.decide(cluster, store)

    assert result["verdict"] == VW.VERDICT_BUILD
    assert result["blocking_reasons"] == []


def test_no_forced_build_category(cluster_factory):
    weak_clusters = [
        cluster_factory(cluster_id="c1", solo=55, gate="UNKNOWN", seo_status="NOT_CHECKED"),
        cluster_factory(cluster_id="c2", solo=60, gate="FAIL", seo_status="PARTIAL",
                        keywords=[("kw", 10, 5, True, None)]),
        cluster_factory(cluster_id="c3", solo=65, domain="prompt", function="generation",
                        gate="PASS", seo_status="PARTIAL",
                        keywords=[("prompt generator", 880, 2, True, None)],
                        members=[_member("Prompt Generator", "Generate prompts.")]),
    ]
    verdicts = {v.decide(cluster, None)["verdict"] for cluster in weak_clusters}
    assert VW.VERDICT_BUILD not in verdicts


def test_validation_gaps_only_for_test_and_watch(cluster_factory):
    build_cluster = _strong_cluster(cluster_factory)
    store = vs.load_store(None)
    vs.add_evidence(store, build_cluster["cluster_id"], "COMPETITOR", "positive", "competitors charge")
    assert v.decide(build_cluster, store)["validation_gaps"] == []

    skip_cluster = _strong_cluster(cluster_factory, gate="FAIL",
                                   keywords=[("tiny", 10, 5, True, None)])
    assert v.decide(skip_cluster, None)["validation_gaps"] == []

    assert v.decide(_strong_cluster(cluster_factory), None)["validation_gaps"]
    assert v.decide(cluster_factory(gate="UNKNOWN"), None)["validation_gaps"]


def test_gaps_mention_concrete_next_actions(cluster_factory):
    gaps = v.decide(_strong_cluster(cluster_factory), None)["validation_gaps"]
    text = " ".join(gaps).lower()

    assert "competitor pricing" in text
    assert "payment signals" in text
    assert "reddit" in text
    assert "serp" in text


def test_negative_evidence_can_force_skip(cluster_factory):
    cluster = _strong_cluster(cluster_factory)
    store = vs.load_store(None)
    vs.add_evidence(store, cluster["cluster_id"], "SUBSTITUTION", "negative",
                    "ChatGPT already does this for free")
    vs.add_evidence(store, cluster["cluster_id"], "SUBSTITUTION", "negative",
                    "Free alternatives dominate the SERP")

    assert v.decide(cluster, store)["verdict"] == VW.VERDICT_SKIP


def test_deep_research_is_off_by_default():
    from analyzers import deep_research

    assert not deep_research.deep_research_enabled(env={})
    assert deep_research.deep_research_enabled(env={deep_research.ENV_FLAG: "1"})
    assert deep_research.available_providers() == []
    assert deep_research.research_top_candidates([{"cluster_id": "c"}], env={}) == []


def test_deep_research_results_become_evidence_when_a_provider_is_registered(tmp_path):
    from analyzers import deep_research

    def provider(cluster):
        return [{
            "evidence_type": "COMPETITOR",
            "sentiment": "positive",
            "summary": f"{cluster['cluster_id']} has paying competitors",
            "note": "provider stub",
        }]

    store = vs.load_store(tmp_path / "evidence.json")
    deep_research.register_provider("test-stub", provider)
    try:
        results = deep_research.research_top_candidates(
            [{"cluster_id": "demo-cluster"}], provider="test-stub",
            env={deep_research.ENV_FLAG: "1"}, store=store,
            path=tmp_path / "evidence.json",
        )
    finally:
        deep_research.unregister_provider("test-stub")

    assert len(results) == 1
    records = vs.evidence_for(vs.load_store(tmp_path / "evidence.json"), "demo-cluster")
    assert records[0]["evidence_type"] == "COMPETITOR"
    assert "paying competitors" in records[0]["summary"]
