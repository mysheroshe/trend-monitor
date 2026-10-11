"""Final decision layer: BUILD / TEST / WATCH / SKIP (Phase 4).

Combines the three existing scores (Solo Builder, Cluster Evidence, SEO
Opportunity) with explicitly derived dimensions:

    substitution risk, acquisition channel/fit, monetization model/confidence,
    operating-cost risk, and manual validation evidence.

The three scores are NOT averaged. Several inputs act as gates or penalties,
and BUILD is deliberately hard to reach: the default for
attractive-but-incomplete opportunities is TEST.

Deterministic, offline, no LLM, no paid API, no database.
"""

from analyzers.text_utils import has_phrase, product_text
from config import verdict_weights as VW
from storage import validation_store


# ---------------------------------------------------------------------------
# Local vocabularies (kept here so this module stays independent of the
# Phase 1 filter module and cannot create an import cycle)
# ---------------------------------------------------------------------------

_AI_TERMS = ["ai", "gpt", "llm", "openai", "claude", "anthropic", "gemini",
             "machine learning"]

_SALES_TERMS = [
    "contact sales", "book a demo", "request a demo", "schedule a demo",
    "talk to sales", "enterprise pricing", "custom pricing", "book a call",
    "implementation services", "onboarding services", "dedicated manager",
    "account manager", "professional services", "consulting", "agency",
    "done-for-you", "multi-person team", "team of engineers",
]

_REGULATED_TERMS = [
    "hipaa", "pci dss", "sox compliance", "gdpr compliance", "bank-grade",
    "regulated industry", "clinical trial", "medical device",
]

_PROPRIETARY_DATA_TERMS = [
    "proprietary dataset", "licensed data", "exclusive dataset",
    "proprietary database", "paid data feed", "bloomberg",
]

_HEAVY_INFERENCE_TERMS = [
    "video generation", "continuous inference", "fine-tune", "fine tuning",
    "voice cloning", "gpu cluster", "render farm",
]

_LOCAL_TERMS = [
    "browser-only", "runs in your browser", "client-side", "client side",
    "local processing", "offline", "on-device", "without uploading",
    "in-browser",
]

_EXTENSION_TERMS = ["chrome extension", "browser extension", "extension",
                    "addon", "add-on", "plugin"]

_SUBSCRIPTION_TERMS = ["subscription", "monthly", "annual", "/mo", "per month", "/month"]
_FREEMIUM_TERMS = ["freemium", "free plan", "free tier", "upgrade", "premium"]
_ONE_TIME_TERMS = ["one-time", "one time payment", "lifetime", "pay once"]
_CREDIT_TERMS = ["credits", "credit-based", "microtransaction", "pay per use"]
_ADS_TERMS = ["ad-supported", "advert", "ads", "sponsored"]
_AFFILIATE_TERMS = ["affiliate", "referral commission"]
_LEADGEN_TERMS = ["lead generation", "get leads", "quote request"]
_MARKETPLACE_TERMS = ["marketplace", "buyers and sellers", "vendors"]

_REPEAT_USE_FUNCTIONS = {"tracking", "planning", "analysis", "checking", "monitoring"}
_DETERMINISTIC_FUNCTIONS = {
    "calculation", "checking", "conversion", "formatting", "comparison",
    "directory", "extraction", "finding", "tracking",
}
_GENERIC_AI_FUNCTIONS = {"writing", "summarization", "translation"}
_MEDIA_DOMAINS = {"image", "video", "audio"}
_BROAD_DOMAINS = {"text", "code", "data", "website", "image", "video", "audio", "social"}
_SOCIAL_DOMAINS = {
    "fortune_telling", "entertainment", "meme", "avatar", "wallpaper",
    "gif", "sticker", "thumbnail",
}
_UTILITY_DOMAINS = {
    "pdf", "spreadsheet", "unit", "color", "font", "qr", "barcode", "password",
    "currency", "time", "calendar", "data",
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _cluster_text(cluster):
    parts = [product_text(member) for member in (cluster.get("members") or [])]
    if not parts:
        parts.append(str(cluster.get("cluster_label") or "").lower())
        parts.extend(str(name).lower() for name in (cluster.get("member_names") or []))
    return " ".join(parts)


def _solo_score(cluster):
    return int(cluster.get("max_solo_builder_score") or 0)


def _viable_keywords(cluster):
    return [k for k in (cluster.get("checked_keywords") or []) if k.get("is_viable")]


def _empty_evidence_summary():
    return {
        "total": 0, "positive": 0, "neutral": 0, "negative": 0,
        "types": {}, "positive_types": [], "negative_types": [], "has_url": False,
    }


def _evidence_for(cluster, store):
    if not store:
        return _empty_evidence_summary()
    return validation_store.evidence_summary(store, cluster.get("cluster_id"))


# ---------------------------------------------------------------------------
# Step 5 - substitution risk
# ---------------------------------------------------------------------------

def substitution_risk(cluster):
    """How likely is a major platform to absorb this functionality?"""
    function = cluster.get("function")
    domain = cluster.get("domain")
    text = _cluster_text(cluster)
    reasons = []

    if has_phrase(text, ["wrapper", "chatgpt wrapper", "gpt wrapper"]):
        return VW.SUBSTITUTION_SEVERE, ["thin wrapper around a general model API"]
    if function in _GENERIC_AI_FUNCTIONS and not domain:
        reasons.append(f"generic AI {function} with no domain anchor")
        return VW.SUBSTITUTION_SEVERE, reasons
    if domain == "prompt" and function == "generation":
        reasons.append("prompt generation is native to major models and IDEs")
        return VW.SUBSTITUTION_HIGH, reasons
    if function == "generation" and domain in _MEDIA_DOMAINS:
        reasons.append(f"{domain} generation is a native feature of Canva/Adobe/OpenAI")
        return VW.SUBSTITUTION_HIGH, reasons
    if function in _GENERIC_AI_FUNCTIONS and domain in _BROAD_DOMAINS:
        reasons.append(f"AI {function} for a broad domain")
        return VW.SUBSTITUTION_HIGH, reasons
    if function == "generation" and not domain:
        reasons.append("generic AI generator with no domain anchor")
        return VW.SUBSTITUTION_HIGH, reasons

    if function in _DETERMINISTIC_FUNCTIONS and domain and domain not in _BROAD_DOMAINS:
        reasons.append("deterministic processing over a specific domain - hard to absorb")
        return VW.SUBSTITUTION_LOW, reasons
    if has_phrase(text, _LOCAL_TERMS) or has_phrase(text, _EXTENSION_TERMS):
        reasons.append("browser/local tool rather than a model capability")
        return VW.SUBSTITUTION_LOW, reasons
    if has_phrase(text, _AI_TERMS):
        reasons.append("AI-adjacent but tied to a specific domain and workflow")
        return VW.SUBSTITUTION_MEDIUM, reasons
    if function in _DETERMINISTIC_FUNCTIONS:
        reasons.append("deterministic utility")
        return VW.SUBSTITUTION_LOW, reasons

    reasons.append("no strong substitution signal either way (heuristic, not certainty)")
    return VW.SUBSTITUTION_MEDIUM, reasons


# ---------------------------------------------------------------------------
# Step 6 - acquisition
# ---------------------------------------------------------------------------

def acquisition(cluster):
    """Return (primary_acquisition_channel, acquisition_fit, reasons)."""
    text = _cluster_text(cluster)
    domain = cluster.get("domain")
    sources = set(cluster.get("member_sources") or [])
    seo_status = cluster.get("seo_score_status", "NOT_CHECKED")
    gate = cluster.get("market_demand_gate", "UNKNOWN")

    if has_phrase(text, _SALES_TERMS):
        return VW.CHANNEL_DIRECT_SALES, VW.ACQUISITION_FIT_WEAK, [
            "sales/demo or service-delivery signals require direct outreach"
        ]
    if "chrome_extensions" in sources or has_phrase(text, _EXTENSION_TERMS):
        return VW.CHANNEL_PLATFORM, VW.ACQUISITION_FIT_STRONG, [
            "extension store listing provides self-service distribution"
        ]
    if domain in _SOCIAL_DOMAINS:
        return VW.CHANNEL_SOCIAL, VW.ACQUISITION_FIT_STRONG, [
            "shareable output drives viral/social distribution"
        ]
    if "github" in sources or domain == "code":
        return VW.CHANNEL_COMMUNITY, VW.ACQUISITION_FIT_MEDIUM, [
            "developer communities (GitHub/HN/Reddit) are the natural channel"
        ]
    if cluster.get("keyword_candidates") or (domain and cluster.get("function")):
        if seo_status == "VALIDATED" and gate == "PASS":
            fit, why = VW.ACQUISITION_FIT_STRONG, "validated search demand with accessible keywords"
        else:
            fit, why = VW.ACQUISITION_FIT_MEDIUM, "search-led, but demand is not validated yet"
        return VW.CHANNEL_SEO, fit, [why]
    return VW.CHANNEL_UNKNOWN, VW.ACQUISITION_FIT_WEAK, [
        "no clear self-service acquisition channel identified"
    ]


# ---------------------------------------------------------------------------
# Step 7 - monetization
# ---------------------------------------------------------------------------

def monetization(cluster, evidence=None):
    """Return (model, confidence, reasons)."""
    text = _cluster_text(cluster)
    domain = cluster.get("domain")
    function = cluster.get("function")
    evidence = evidence or _empty_evidence_summary()
    payment_signal = "PAYMENT_SIGNAL" in evidence.get("positive_types", [])

    if has_phrase(text, _SALES_TERMS + _MARKETPLACE_TERMS):
        return "enterprise sales", "LOW", [
            "sales-led or marketplace economics are hard solo"
        ]
    if has_phrase(text, _SUBSCRIPTION_TERMS):
        model, base = "subscription", "MEDIUM"
    elif has_phrase(text, _CREDIT_TERMS) or domain in ("fortune_telling", "entertainment"):
        model, base = "credits", "MEDIUM"
    elif has_phrase(text, _ONE_TIME_TERMS):
        model, base = "one-time payment", "MEDIUM"
    elif has_phrase(text, _ADS_TERMS):
        model, base = "ads", "LOW"
    elif has_phrase(text, _AFFILIATE_TERMS):
        model, base = "affiliate", "LOW"
    elif has_phrase(text, _LEADGEN_TERMS):
        model, base = "lead generation", "LOW"
    elif has_phrase(text, _FREEMIUM_TERMS):
        model, base = "freemium", "MEDIUM"
    elif (function in _DETERMINISTIC_FUNCTIONS and domain) or domain in _UTILITY_DOMAINS:
        model, base = "one-time payment", "MEDIUM"
    elif has_phrase(text, _EXTENSION_TERMS):
        model, base = "freemium", "MEDIUM"
    else:
        model, base = "freemium", "LOW"

    reasons = [f"inferred '{model}' model from product positioning"]

    confidence = base
    if base == "MEDIUM" and function in _REPEAT_USE_FUNCTIONS:
        confidence = "HIGH"
        reasons.append("recurring-use workflow supports paid conversion")
    if payment_signal:
        if confidence == "LOW":
            confidence = "MEDIUM"
        elif confidence == "MEDIUM":
            confidence = "HIGH"
        reasons.append("positive PAYMENT_SIGNAL evidence recorded")
    substitution, _ = substitution_risk(cluster)
    if substitution in (VW.SUBSTITUTION_HIGH, VW.SUBSTITUTION_SEVERE) and confidence == "HIGH":
        confidence = "MEDIUM"
        reasons.append("substitution risk caps confidence")

    return model, confidence, reasons


# ---------------------------------------------------------------------------
# Operating cost risk
# ---------------------------------------------------------------------------

def operating_cost_risk(cluster):
    """Return (level, reasons) from member cost levels plus text heuristics."""
    text = _cluster_text(cluster)
    proprietary = has_phrase(text, _PROPRIETARY_DATA_TERMS)
    heavy = has_phrase(text, _HEAVY_INFERENCE_TERMS)
    if proprietary and heavy:
        return VW.COST_RISK_SEVERE, [
            "combines a paid/proprietary dataset with heavy inference"
        ]

    levels = []
    for member in cluster.get("members") or []:
        level = ((member.get("_scores") or {}).get("operating_cost_level"))
        if level:
            levels.append(level)

    if levels:
        if "HIGH" in levels and proprietary:
            return VW.COST_RISK_HIGH, ["high ongoing cost plus paid-data dependency"]
        if "HIGH" in levels:
            return VW.COST_RISK_HIGH, ["at least one member has a high ongoing cost profile"]
        if "MEDIUM" in levels:
            return VW.COST_RISK_MEDIUM, ["moderate recurring serving cost"]
        return VW.COST_RISK_LOW, ["low marginal cost per use"]

    if proprietary:
        return VW.COST_RISK_HIGH, ["paid/proprietary data dependency"]
    if heavy:
        return VW.COST_RISK_HIGH, ["inference-heavy workload"]
    if has_phrase(text, _LOCAL_TERMS) or has_phrase(text, _EXTENSION_TERMS):
        return VW.COST_RISK_LOW, ["browser/local processing"]
    if has_phrase(text, _AI_TERMS):
        return VW.COST_RISK_MEDIUM, ["occasional model calls"]
    return VW.COST_RISK_MEDIUM, ["no member cost data; assuming moderate cost"]


# ---------------------------------------------------------------------------
# Opportunity Score components
# ---------------------------------------------------------------------------

def competition_accessibility(cluster):
    """Points from the accessibility of the best viable keyword."""
    viable = _viable_keywords(cluster)
    if not viable:
        return 0, ["no checked keyword clears the viability bar"]
    best = min(viable, key=lambda k: k.get("kd", 999))
    kd = int(best.get("kd") or 0)
    points = VW.COMPETITION_KD_FALLBACK
    for threshold, value in VW.COMPETITION_KD_POINTS:
        if kd <= threshold:
            points = value
            break
    bonus = 0
    count = best.get("weak_serp_count")
    if count is not None and count >= 2:
        bonus = VW.COMPETITION_MULTI_WEAK_BONUS
    elif best.get("weak_serp"):
        bonus = VW.COMPETITION_WEAK_SERP_BONUS
    points = min(VW.WEIGHTS["competition_accessibility"], points + bonus)
    return points, [
        f"best viable keyword '{best.get('keyword')}' has KD {kd}"
        + (" with multiple low-authority results" if bonus == 2
           else " with a weak SERP result" if bonus == 1 else "")
    ]


def market_demand_points(cluster, evidence):
    """Points from validated SEO demand (or a little credit for non-SEO demand)."""
    status = cluster.get("seo_score_status", "NOT_CHECKED")
    gate = cluster.get("market_demand_gate", "UNKNOWN")
    seo_score = int(cluster.get("seo_score") or 0)
    strong_types = [t for t in evidence.get("positive_types", [])
                    if t in VW.STRONG_NON_SEO_EVIDENCE_TYPES]

    if status != "NOT_CHECKED":
        if gate == "FAIL":
            return 0, ["market demand gate FAIL"]
        return round(seo_score / 100 * VW.WEIGHTS["market_demand"]), [
            f"SEO demand validated (score {seo_score}/100)"
        ]
    if strong_types:
        points = min(10, 5 * len(strong_types))
        return points, [
            "no Semrush data yet; partial credit for "
            + ", ".join(sorted(strong_types)) + " evidence"
        ]
    return 0, ["demand not measured yet (no Semrush data, no demand evidence)"]


def opportunity_evidence_points(evidence):
    positive_types = evidence.get("positive_types", [])[:VW.EVIDENCE_MAX_POSITIVE_TYPES]
    points = (VW.EVIDENCE_POINTS_PER_POSITIVE_TYPE * len(positive_types)
              - VW.EVIDENCE_NEGATIVE_PENALTY * evidence.get("negative", 0))
    points = max(0, min(VW.WEIGHTS["opportunity_evidence"], points))
    reasons = []
    if positive_types:
        reasons.append("positive evidence: " + ", ".join(positive_types))
    else:
        reasons.append("no manual validation evidence recorded yet")
    if evidence.get("negative"):
        reasons.append(f"{evidence['negative']} negative evidence record(s)")
    return points, reasons


def opportunity_score(cluster, evidence=None):
    """Opportunity Score /100 (supporting metric only; gates are separate)."""
    evidence = evidence or _empty_evidence_summary()
    substitution, _ = substitution_risk(cluster)
    _, fit, _ = acquisition(cluster)
    _, confidence, _ = monetization(cluster, evidence)
    cost_risk, _ = operating_cost_risk(cluster)
    competition_points, _ = competition_accessibility(cluster)
    demand_points, _ = market_demand_points(cluster, evidence)
    evidence_points, _ = opportunity_evidence_points(evidence)

    solo = _solo_score(cluster)
    orchard = int(cluster.get("tool_orchard_potential") or 0)

    parts = {
        "solo_builder_fit": round(solo / 100 * VW.WEIGHTS["solo_builder_fit"]),
        "market_demand": demand_points,
        "opportunity_evidence": evidence_points,
        "competition_accessibility": competition_points,
        "monetization_confidence": VW.MONETIZATION_POINTS.get(confidence, 0),
        "acquisition_fit": VW.ACQUISITION_POINTS.get(fit, 0),
        "operating_cost": VW.COST_POINTS.get(cost_risk, 0),
        "tool_orchard": round(orchard / 10 * VW.WEIGHTS["tool_orchard"]),
        "substitution_risk": VW.SUBSTITUTION_POINTS.get(substitution, 0),
    }
    total = max(0, min(VW.OPPORTUNITY_MAX, sum(parts.values())))
    return total, parts


# ---------------------------------------------------------------------------
# Steps 2-4, 10-11 - verdict, gates, reasons and gaps
# ---------------------------------------------------------------------------

def _build_requirements(cluster, evidence, context):
    solo = context["solo"]
    requirements = [
        ("solo", solo >= VW.BUILD_MIN_SOLO_BUILDER,
         f"Solo Builder Score >= {VW.BUILD_MIN_SOLO_BUILDER} (currently {solo})"),
        ("demand", context["gate"] == "PASS" or context["strong_non_seo"],
         "Market Demand Gate = PASS or strong non-SEO demand evidence"),
        ("seo_validated",
         context["channel"] != VW.CHANNEL_SEO or context["seo_status"] == "VALIDATED",
         "SEO keyword validation (SEO is the main acquisition channel)"),
        ("substitution", context["substitution"] in VW.BUILD_REQUIRED_SUBSTITUTION,
         f"substitution risk in {VW.BUILD_REQUIRED_SUBSTITUTION} "
         f"(currently {context['substitution']})"),
        ("acquisition", context["fit"] in VW.BUILD_REQUIRED_ACQUISITION_FIT,
         f"acquisition fit in {VW.BUILD_REQUIRED_ACQUISITION_FIT} (currently {context['fit']})"),
        ("monetization", context["confidence"] in VW.BUILD_REQUIRED_MONETIZATION,
         f"monetization confidence in {VW.BUILD_REQUIRED_MONETIZATION} "
         f"(currently {context['confidence']})"),
        ("cost", context["cost_risk"] in VW.BUILD_REQUIRED_COST_RISK,
         f"operating-cost risk in {VW.BUILD_REQUIRED_COST_RISK} "
         f"(currently {context['cost_risk']})"),
        ("monetization_evidence",
         context["confidence"] == "HIGH"
         or any(t in VW.BUILD_TRUSTED_EVIDENCE_TYPES for t in evidence["positive_types"]),
         "monetization evidence: a positive COMPETITOR or PAYMENT_SIGNAL note, "
         "or HIGH monetization confidence"),
        ("support", context["diversity"] >= 2
         or context["strongest_confidence"] in ("High", "Medium–High"),
         "corroboration from 2+ sources or a high-confidence source"),
        ("persistence", context["days_seen"] >= VW.WATCH_MIN_DAYS_SEEN
         or evidence["positive"] > 0,
         "persistence (seen on 2+ days) or positive validation evidence"),
    ]
    return [{"key": key, "ok": ok, "reason": reason} for key, ok, reason in requirements]


def _validation_gaps(cluster, evidence, context):
    """Concrete next actions for TEST / WATCH opportunities."""
    gaps = []
    status = context["seo_status"]
    checked = len(cluster.get("checked_keywords") or [])
    viable = len(_viable_keywords(cluster))

    if status == "NOT_CHECKED":
        gaps.append("Run 3-5 Semrush lookups for this cluster "
                    "(US volume, KD, weak-SERP yes/no)")
    elif checked < 3 or viable < 2:
        gaps.append(f"Verify {max(3 - checked, 1)} more Semrush keywords "
                    "(aim for 2+ viable terms)")
    if status != "NOT_CHECKED" and viable:
        gaps.append("Inspect the top 10 SERP results for the best viable keyword "
                    "and note incumbent authority")
    if "COMPETITOR" not in evidence["positive_types"]:
        gaps.append("Check 3 competitor pricing pages to confirm people pay")
    if "PAYMENT_SIGNAL" not in evidence["positive_types"]:
        gaps.append("Look for payment signals (pricing pages, credits, reviews "
                    "mentioning purchase)")
    if "COMMUNITY_PAIN" not in evidence["positive_types"]:
        gaps.append("Search Reddit/communities for repeated pain around this problem")
    if context["confidence"] in ("LOW", "UNKNOWN"):
        gaps.append("Validate willingness to pay and repeat usage before building")
    if context["cost_risk"] in ("HIGH", "SEVERE"):
        gaps.append("Estimate API/inference cost per use and per paying user")
    if context["substitution"] in ("HIGH", "SEVERE"):
        gaps.append("Check whether ChatGPT/Claude/Gemini already handles this task "
                    "well enough for free")
    if context["days_seen"] < VW.WATCH_MIN_DAYS_SEEN:
        gaps.append("Keep monitoring for 2+ days of repeat appearances")
    if context["gate"] == "FAIL":
        gaps.append("Re-check demand in Semrush; if it stays negligible, drop this idea")
    return gaps


def _verdict_reasons(context, evidence):
    reasons = []
    if context["gate"] == "PASS":
        reasons.append("meaningful search demand (market gate PASS)")
    if _viable_keywords({"checked_keywords": context["checked_keywords"]}):
        reasons.append(f"{len(_viable_keywords({'checked_keywords': context['checked_keywords']}))} "
                       "accessible long-tail keyword(s)")
    if context["solo"] >= VW.BUILD_MIN_SOLO_BUILDER:
        reasons.append(f"strong solo-builder fit ({context['solo']}/100)")
    if context["fit"] in ("STRONG", "MEDIUM"):
        reasons.append(f"{context['channel']} acquisition fits this user ({context['fit']})")
    if context["cost_risk"] == "LOW":
        reasons.append("low operating cost")
    if evidence["positive"]:
        reasons.append(f"{evidence['positive']} positive validation evidence record(s)")
    return reasons


def decide(cluster, store=None, today=None):
    """Compute substitution/acquisition/monetization, verdict, score and gaps."""
    cluster_id = cluster.get("cluster_id", "")
    evidence = _evidence_for(cluster, store)

    substitution, substitution_reasons = substitution_risk(cluster)
    channel, fit, acquisition_reasons = acquisition(cluster)
    model, confidence, monetization_reasons = monetization(cluster, evidence)
    cost_risk, cost_reasons = operating_cost_risk(cluster)
    competition_points, competition_reasons = competition_accessibility(cluster)
    demand_points, demand_reasons = market_demand_points(cluster, evidence)
    evidence_points, evidence_reasons = opportunity_evidence_points(evidence)
    total, parts = opportunity_score(cluster, evidence)

    solo = _solo_score(cluster)
    gate = cluster.get("market_demand_gate", "UNKNOWN")
    seo_status = cluster.get("seo_score_status", "NOT_CHECKED")
    days_seen = int(cluster.get("days_seen") or 1)
    diversity = int(cluster.get("source_diversity") or 0)
    strongest_confidence = cluster.get("strongest_source_confidence", "Unknown")
    text = _cluster_text(cluster)

    strong_types = [t for t in evidence["positive_types"]
                    if t in VW.STRONG_NON_SEO_EVIDENCE_TYPES]
    strong_non_seo = len(strong_types) >= VW.STRONG_NON_SEO_MIN_EVIDENCE
    negative_dominant = (evidence["negative"] >= 2
                         and evidence["negative"] > evidence["positive"])

    context = {
        "solo": solo, "gate": gate, "seo_status": seo_status,
        "substitution": substitution, "channel": channel, "fit": fit,
        "confidence": confidence, "cost_risk": cost_risk,
        "diversity": diversity, "strongest_confidence": strongest_confidence,
        "days_seen": days_seen, "strong_non_seo": strong_non_seo,
        "checked_keywords": cluster.get("checked_keywords") or [],
    }

    blocking = []
    verdict = None

    # ---- hard SKIP conditions
    if has_phrase(text, _SALES_TERMS):
        blocking.append("enterprise/direct-sales or service-delivery dependency")
        verdict = VW.VERDICT_SKIP
    elif has_phrase(text, _REGULATED_TERMS):
        blocking.append("high regulatory burden")
        verdict = VW.VERDICT_SKIP
    elif cost_risk == VW.COST_RISK_SEVERE:
        blocking.append("severe operating-cost risk")
        verdict = VW.VERDICT_SKIP
    elif solo < VW.SKIP_BELOW_SOLO_BUILDER:
        blocking.append(f"Solo Builder Score {solo}/100 is below the "
                        f"{VW.SKIP_BELOW_SOLO_BUILDER} bar")
        verdict = VW.VERDICT_SKIP
    elif substitution == VW.SUBSTITUTION_SEVERE:
        blocking.append("functionality is a commodity capability of major platforms")
        verdict = VW.VERDICT_SKIP
    elif gate == "FAIL" and not strong_non_seo:
        blocking.append("market demand gate FAIL with no non-SEO demand evidence")
        verdict = VW.VERDICT_SKIP
    elif negative_dominant:
        blocking.append("validation evidence is predominantly negative")
        verdict = VW.VERDICT_SKIP

    reasons = _verdict_reasons(context, evidence)
    gaps = []

    if verdict is None:
        requirements = _build_requirements(cluster, evidence, context)
        unmet = [r for r in requirements if not r["ok"]]
        if not unmet:
            verdict = VW.VERDICT_BUILD
            reasons.insert(0, "every BUILD requirement is met with evidence")
        else:
            blocking.extend(f"BUILD requires: {r['reason']}" for r in unmet)
            if gate == "UNKNOWN" and seo_status == "NOT_CHECKED" and not strong_non_seo:
                if context["channel"] in (VW.CHANNEL_SEO, VW.CHANNEL_UNKNOWN):
                    verdict = VW.VERDICT_WATCH
                    reasons.append("no demand proof yet for a search-led or unclear channel")
                else:
                    # a viable non-SEO channel exists, but demand is unproven
                    verdict = VW.VERDICT_TEST
                    reasons.append(f"{context['channel']} channel is viable; demand still unproven")
            elif substitution == VW.SUBSTITUTION_HIGH and confidence in ("LOW", "UNKNOWN"):
                verdict = VW.VERDICT_WATCH
                reasons.append("commodity-prone capability with weak monetization")
            elif gate == "FAIL":
                verdict = VW.VERDICT_WATCH
                reasons.append("search demand too thin for SEO-led; watching for non-SEO demand")
            elif days_seen < VW.WATCH_MIN_DAYS_SEEN and gate in ("UNKNOWN", "WEAK"):
                verdict = VW.VERDICT_WATCH
                reasons.append("too early: no persistence and unproven demand")
            elif solo < VW.WATCH_BELOW_SOLO_BUILDER:
                verdict = VW.VERDICT_WATCH
                reasons.append(f"weak solo-builder fit ({solo}/100)")
            else:
                verdict = VW.VERDICT_TEST

    if verdict in (VW.VERDICT_TEST, VW.VERDICT_WATCH):
        gaps = _validation_gaps(cluster, evidence, context)

    return {
        "verdict": verdict,
        "verdict_reasons": reasons,
        "blocking_reasons": blocking,
        "validation_gaps": gaps,
        "opportunity_score": total,
        "opportunity_score_parts": parts,
        "substitution_risk": substitution,
        "substitution_reasons": substitution_reasons,
        "primary_acquisition_channel": channel,
        "acquisition_fit": fit,
        "acquisition_reasons": acquisition_reasons,
        "monetization_model": model,
        "monetization_confidence": confidence,
        "monetization_reasons": monetization_reasons,
        "operating_cost_risk": cost_risk,
        "operating_cost_reasons": cost_reasons,
        "competition_reasons": competition_reasons,
        "demand_reasons": demand_reasons,
        "evidence_reasons": evidence_reasons,
        "evidence_summary": evidence,
        "build_requirements": _build_requirements(cluster, evidence, context),
    }


def attach_verdict(clusters, store=None, path=None, record_history=True, today=None):
    """Attach verdict fields to each cluster and record verdict changes."""
    for cluster in clusters:
        cluster.update(decide(cluster, store, today=today))

    if store is not None and record_history:
        changed = False
        for cluster in clusters:
            reason = "; ".join(cluster["verdict_reasons"][:2])
            result = validation_store.record_verdict(
                store, cluster["cluster_id"], cluster["verdict"],
                reason=reason, date=today,
            )
            changed = changed or result["changed"]
        if changed and path is not None:
            validation_store.save_store(store, path)

    if store is not None:
        for cluster in clusters:
            cluster["verdict_history"] = validation_store.verdict_history_for(
                store, cluster["cluster_id"]
            )
    return clusters
