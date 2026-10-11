"""Solo Builder Score tests: weights, polarity, ranges and source confidence."""

import pytest

from analyzers import indie_analyzer as ia
from config import scoring_weights as SW

UTILITY = (
    "JSON to CSV Converter",
    "Free online JSON to CSV converter. No signup, works in your browser.",
)


def test_weights_sum_to_one_hundred():
    assert SW.TOTAL_MAX == 100
    assert sum(SW.WEIGHTS.values()) == 100


def test_easy_utility_outranks_difficult_infrastructure(product_factory):
    utility = product_factory(*UTILITY, source="toolify", link="https://a")
    infrastructure = product_factory(
        "Distributed Render Kernel",
        "A real-time distributed rendering engine with kernel-level scheduling "
        "for large studios.",
        source="toolify",
        link="https://b",
    )

    ranked, _ = ia.rank_products({"toolify": [infrastructure, utility]})
    names = [p["name"] for p in ranked]

    assert utility["name"] in names and infrastructure["name"] in names
    assert ranked[0]["name"] == utility["name"]
    assert ranked[0]["_scores"]["ranking_score"] > ranked[-1]["_scores"]["ranking_score"]


def test_build_ease_polarity_cannot_regress(product_factory):
    """A harder product must never earn more build-ease points or a higher total."""
    easy = product_factory("Markdown Converter", "Free online tool to convert markdown.")
    hard = product_factory(
        "Markdown Converter",
        "Free online tool to convert markdown, built as a distributed real-time "
        "compiler with kernel-level scheduling.",
    )

    easy_score = ia.score_product(easy)
    hard_score = ia.score_product(hard)

    assert easy_score["build_ease"] > hard_score["build_ease"]
    assert (easy_score["dimensions"]["build_ease"]["points"]
            > hard_score["dimensions"]["build_ease"]["points"])
    # The old bug summed "tech_difficulty" (higher = harder) into the total.
    assert "tech_difficulty" not in easy_score
    assert "tech_difficulty" not in easy_score["dimensions"]
    assert hard_score["total_score"] <= easy_score["total_score"]


@pytest.mark.parametrize(
    "source",
    ["toolify", "product_hunt", "ai_tools", "chrome_extensions",
     "github", "hackernews", "unknown_source"],
)
def test_total_score_stays_in_range(product_factory, source):
    product = product_factory("Everything App", "An app that does everything for teams.", source=source)
    score = ia.score_product(product)

    assert 0 <= score["total_score"] <= 100
    assert 0 <= score["ranking_score"] <= 100
    assert score["total_score"] == sum(d["points"] for d in score["dimensions"].values())
    assert all(0 <= d["points"] <= d["max"] for d in score["dimensions"].values())


def test_source_confidence_adjustment_is_capped(product_factory):
    for source in SW.SOURCE_CONFIDENCE:
        score = ia.score_product(product_factory("Some Tool", "A small utility.", source=source))
        assert abs(score["source_adjustment"]) <= SW.MAX_SOURCE_ADJUSTMENT
        assert abs(score["ranking_score"] - score["total_score"]) <= SW.MAX_SOURCE_ADJUSTMENT


def test_source_confidence_cannot_rescue_a_weak_product(product_factory):
    weak = product_factory(
        "Deal Desk Platform",
        "An ecosystem suite for team collaboration. Contact sales for pricing. Book a demo.",
        source="toolify",
        link="https://weak",
    )
    strong = product_factory(*UTILITY, source="hackernews", link="https://strong")

    weak_score = ia.score_product(weak)
    strong_score = ia.score_product(strong)

    assert strong_score["total_score"] - weak_score["total_score"] > 2 * SW.MAX_SOURCE_ADJUSTMENT
    assert strong_score["ranking_score"] > weak_score["ranking_score"]


def test_source_confidence_ordering_matches_product_focus():
    assert ia.source_confidence("toolify")[1] > ia.source_confidence("product_hunt")[1]
    assert ia.source_confidence("product_hunt")[1] > ia.source_confidence("chrome_extensions")[1]
    assert ia.source_confidence("chrome_extensions")[1] > ia.source_confidence("github")[1]
    assert ia.source_confidence("github")[1] > ia.source_confidence("hackernews")[1]
    assert ia.source_confidence("hackernews")[0] == "Low"


def test_high_inference_cost_receives_operating_cost_penalty(product_factory):
    heavy = product_factory(
        "AI Video Studio",
        "Continuous video generation with a render pipeline for creators.",
    )
    light = product_factory(
        "Local JSON Formatter",
        "Runs in your browser, no upload required.",
    )

    heavy_score = ia.score_product(heavy)
    light_score = ia.score_product(light)

    assert heavy_score["operating_cost_level"] == "HIGH"
    assert heavy_score["dimensions"]["operating_cost"]["points"] < SW.WEIGHTS["operating_cost"]
    assert light_score["operating_cost_level"] == "LOW"


def test_proprietary_dataset_is_penalized_on_operating_cost(product_factory):
    product = product_factory(
        "Market Data Terminal",
        "Uses a proprietary dataset licensed from exchanges.",
    )
    assert ia.score_operating_cost(product)[0] == 1


def test_self_service_tool_beats_consulting_on_communication(product_factory):
    self_service = product_factory(
        "Free Online Unit Converter",
        "Self-service tool, no signup, instant results.",
    )
    consulting = product_factory(
        "Bespoke Data Consulting",
        "A done-for-you consulting engagement with custom development.",
    )

    assert (ia.score_low_communication(self_service)[0]
            > ia.score_low_communication(consulting)[0])
    assert ia.score_product(self_service)["communication_burden"] == "LOW"
    assert ia.score_product(consulting)["communication_burden"] == "HIGH"


def test_lightweight_generator_receives_positive_signals(product_factory):
    product = product_factory(
        "Invoice Generator",
        "Free invoice generator for freelancers. No login required.",
    )
    score = ia.score_product(product)

    assert score["build_ease"] >= 4
    assert score["tool_orchard"] >= 4
    assert score["operating_cost_level"] in ("LOW", "MEDIUM")
    assert SW.MIN_REASONS <= len(score["reasons"]) <= SW.MAX_REASONS


def test_tool_orchard_families_score_higher_than_novelty(product_factory):
    converter = product_factory("Unit Converter", "Convert units of measure.")
    novelty = product_factory("A One-Off Novelty Toy Project", "Just for fun.")

    assert ia.score_tool_orchard(converter)[0] > ia.score_tool_orchard(novelty)[0]
