"""Example cases A-E from the Phase 4 brief (Step 15), end to end."""

from analyzers.clustering import analyze_clusters
from analyzers.indie_analyzer import rank_products
from analyzers.keyword_candidates import attach_keyword_candidates
from analyzers.seo_score import attach_seo
from analyzers.verdict import attach_verdict, decide
from storage import enrichment_store as es
from storage import validation_store as vs


def _product(name, description, source, index):
    return {
        "name": name,
        "description": description,
        "_source": source,
        "link": f"https://example.com/{source}-{index}",
    }


def _build(products, enrichment_rows=(), evidence=(), tmp_path=None, label="run"):
    work = tmp_path / label
    work.mkdir(parents=True, exist_ok=True)
    keyword_path = work / "keywords.json"
    validation_path = work / "evidence.json"

    groups = {}
    for product in products:
        groups.setdefault(product["_source"], []).append(product)
    suitable, _ = rank_products(groups)

    store = es.load_store(keyword_path)
    for cluster_id, keyword, us, global_volume, kd, weak, count in enrichment_rows:
        es.upsert_metrics(
            store, cluster_id, keyword,
            {"us_volume": us, "global_volume": global_volume, "kd": kd,
             "weak_serp": weak, "weak_serp_count": count},
            path=keyword_path,
        )
    store = es.load_store(keyword_path)

    validation = vs.load_store(validation_path)
    for cluster_id, evidence_type, sentiment, summary in evidence:
        vs.add_evidence(validation, cluster_id, evidence_type, sentiment, summary,
                        path=validation_path)
    validation = vs.load_store(validation_path)

    clusters = attach_keyword_candidates(analyze_clusters(suitable, data_dir=work))
    attach_seo(clusters, store)
    attach_verdict(clusters, validation, path=validation_path,
                   record_history=True, today="2026-10-11")
    return clusters


def _only(clusters, cluster_id):
    return [c for c in clusters if c["cluster_id"] == cluster_id][0]


TATTOO = [
    _product("AI Tattoo Generator", "Generate tattoo designs from a text prompt.", "toolify", 1),
    _product("Tattoo Stencil Generator", "Create tattoo stencils.", "product_hunt", 2),
    _product("Random Tattoo Idea Generator", "Random tattoo ideas.", "product_hunt", 3),
]
TATTOO_KEYWORDS = [
    ("tattoo-generation", "ai tattoo generator", 18100, 28900, 51, True, None),
    ("tattoo-generation", "tattoo stencil generator", 1300, 3000, 22, True, None),
    ("tattoo-generation", "random tattoo idea generator", 480, 800, 14, True, None),
]


def test_case_a_tattoo_is_test_until_monetization_is_proven(tmp_path):
    clusters = _build(TATTOO, TATTOO_KEYWORDS, tmp_path=tmp_path, label="a")
    cluster = _only(clusters, "tattoo-generation")

    assert cluster["market_demand_gate"] == "PASS"
    assert cluster["seo_score_status"] == "VALIDATED"
    assert cluster["substitution_risk"] == "MEDIUM"
    assert cluster["verdict"] == "TEST"
    assert cluster["validation_gaps"]


def test_case_a_becomes_build_once_monetization_is_evidenced(tmp_path):
    clusters = _build(
        TATTOO, TATTOO_KEYWORDS,
        evidence=[("tattoo-generation", "PAYMENT_SIGNAL", "positive",
                   "Competitors sell credit packs for tattoo generations")],
        tmp_path=tmp_path, label="a2",
    )
    cluster = _only(clusters, "tattoo-generation")

    assert cluster["monetization_confidence"] in ("MEDIUM", "HIGH")
    assert cluster["verdict"] == "BUILD"


def test_case_b_excel_checker_is_skip(tmp_path):
    products = [_product("Excel Consistency Checker",
                         "Check spreadsheet formulas for consistency.", "product_hunt", 1)]
    clusters = _build(
        products,
        [("spreadsheet-checking", "excel consistency checker", 20, 80, 12, True, None)],
        tmp_path=tmp_path, label="b",
    )
    cluster = _only(clusters, "spreadsheet-checking")

    assert cluster["seo_score_status"] == "PARTIAL"
    assert cluster["market_demand_gate"] == "FAIL"
    assert cluster["verdict"] == "SKIP"
    assert cluster["verdict"] != "BUILD"


def test_case_b_can_only_become_watch_with_strong_non_seo_evidence(tmp_path):
    products = [_product("Excel Consistency Checker",
                         "Check spreadsheet formulas for consistency.", "product_hunt", 1)]
    clusters = _build(
        products,
        [("spreadsheet-checking", "excel consistency checker", 20, 80, 12, True, None)],
        evidence=[
            ("spreadsheet-checking", "COMMUNITY_PAIN", "positive",
             "Accountants repeatedly ask for formula consistency checks"),
            ("spreadsheet-checking", "PAYMENT_SIGNAL", "positive",
             "Comparable spreadsheet add-ins are paid"),
        ],
        tmp_path=tmp_path, label="b2",
    )
    cluster = _only(clusters, "spreadsheet-checking")

    assert cluster["verdict"] == "WATCH"
    assert cluster["verdict"] != "BUILD"


def test_case_c_prompt_generator_never_becomes_build(tmp_path):
    products = [_product("Random Art Prompt Generator", "Generate random art prompts.", "toolify", 1)]
    clusters = _build(
        products,
        [("prompt-generation", "random art prompt generator", 880, 1500, 2, True, None)],
        tmp_path=tmp_path, label="c",
    )
    cluster = _only(clusters, "prompt-generation")

    assert cluster["substitution_risk"] == "HIGH"
    assert cluster["monetization_confidence"] == "LOW"
    assert cluster["verdict"] in ("TEST", "WATCH")
    assert cluster["verdict"] != "BUILD"


def test_case_d_enterprise_crm_is_skip(tmp_path):
    products = [_product("Enterprise CRM Suite",
                         "Contact sales for enterprise pricing. Dedicated implementation services.",
                         "product_hunt", 1)]
    suitable, filtered = rank_products({"product_hunt": products})

    # filtered before ranking ...
    assert suitable == []
    assert "enterprise" in filtered[0]["filter_reason"].lower()

    # ... and the verdict layer still skips it if it ever reaches it
    manual = {
        "cluster_id": "manual-enterprise", "cluster_label": "Enterprise CRM (manual)",
        "domain": None, "function": "tracking",
        "max_solo_builder_score": 80, "cluster_score": 80, "tool_orchard_potential": 6,
        "seo_score": 60, "seo_score_status": "VALIDATED", "market_demand_gate": "PASS",
        "checked_keywords": [{"keyword": "crm software", "us_volume": 9000, "kd": 40,
                              "weak_serp": False, "is_viable": True}],
        "member_count": 1, "source_diversity": 1, "member_sources": ["product_hunt"],
        "days_seen": 1, "strongest_source_confidence": "Medium",
        "members": [{"name": "Enterprise CRM Suite", "_source": "product_hunt",
                     "description": "Contact sales for enterprise pricing. "
                                    "Dedicated implementation services."}],
    }
    assert decide(manual, None)["verdict"] == "SKIP"


BROWSER_UTILITY = [
    _product("PDF Converter", "Convert PDF files. Runs in your browser. "
                              "One-time purchase.", "toolify", 1),
    _product("Image to PDF Converter", "Convert images to PDF. Free online tool.",
             "product_hunt", 2),
]
BROWSER_UTILITY_KEYWORDS = [
    ("pdf-conversion", "pdf converter", 2000, 4000, 18, True, 3),
    ("pdf-conversion", "image to pdf converter", 900, 1500, 22, True, None),
    ("pdf-conversion", "free pdf converter", 1200, 2000, 25, True, None),
]


def test_case_e_browser_utility_is_test_without_evidence(tmp_path):
    clusters = _build(BROWSER_UTILITY, BROWSER_UTILITY_KEYWORDS, tmp_path=tmp_path, label="e1")
    cluster = _only(clusters, "pdf-conversion")

    assert cluster["substitution_risk"] == "LOW"
    assert cluster["operating_cost_risk"] == "LOW"
    assert cluster["market_demand_gate"] == "PASS"
    assert cluster["verdict"] == "TEST"


def test_case_e_browser_utility_reaches_build_with_evidence(tmp_path):
    clusters = _build(
        BROWSER_UTILITY, BROWSER_UTILITY_KEYWORDS,
        evidence=[("pdf-conversion", "COMPETITOR", "positive",
                   "Competing converters charge one-time fees and rank with weak domains")],
        tmp_path=tmp_path, label="e2",
    )
    cluster = _only(clusters, "pdf-conversion")

    assert cluster["verdict"] == "BUILD"
    assert cluster["opportunity_score"] > 70
    assert cluster["validation_gaps"] == []


def test_case_e_verdict_history_is_recorded(tmp_path):
    work = tmp_path / "history"
    work.mkdir()
    validation_path = work / "evidence.json"
    store = vs.load_store(validation_path)

    vs.record_verdict(store, "pdf-conversion", "WATCH", reason="first seen",
                      date="2026-10-09", path=validation_path)
    store = vs.load_store(validation_path)
    vs.record_verdict(store, "pdf-conversion", "TEST", reason="search demand validated",
                      date="2026-10-10", path=validation_path)

    history = vs.verdict_history_for(vs.load_store(validation_path), "pdf-conversion")
    assert [entry["new_verdict"] for entry in history] == ["WATCH", "TEST"]
    assert history[1]["previous_verdict"] == "WATCH"
