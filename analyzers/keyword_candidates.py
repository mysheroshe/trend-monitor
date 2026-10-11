"""Deterministic SEO keyword candidate generation (Phase 2, tightened in 3 & 5).

Phase 5 changes:
  * product/brand names are stripped before a subject becomes a candidate
    ("monica all one summarizer" is no longer generated);
  * every candidate must carry a **category anchor** *and* a **functional
    anchor**;
  * candidates carry a maturity label (NICHE / BROAD / BRAND / AWKWARD) and
    BRAND/AWKWARD phrases are never produced;
  * the checklist prefers niche, non-brand, tool-intent phrases and never pads
    the list with weak variations.
"""

from analyzers.brand_filter import cluster_brand_tokens, strip_brand_tokens
from analyzers.clustering import DOMAIN_AUDIENCES, DOMAIN_FAMILIES, FUNCTION_FAMILIES
from analyzers.keyword_quality import (
    GENERIC_DOMAINS,
    MATURITY_AWKWARD,
    MATURITY_BRAND,
    MATURITY_BROAD,
    MATURITY_NICHE,
    has_category_anchor,
    has_function_anchor,
    inferred_categories,
    member_derived_allowed,
    passes_quality,
    keyword_maturity,
)
from analyzers.text_utils import has_phrase, product_text, tokenize
from config import cluster_weights as CW

_PRIORITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
_TYPE_RANK = {
    "CORE_TOOL": 0,
    "LONG_TAIL_TOOL": 1,
    "PROBLEM_QUERY": 2,
    "AUDIENCE_SPECIFIC": 3,
    "COMPARISON": 4,
}
_MATURITY_RANK = {MATURITY_NICHE: 0, MATURITY_BROAD: 1}
_DISCOVERY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
_TIER_RANK = {"A": 0, "B": 1, "C": 2}

# Candidate origins (Phase 6, Step 22) and priority tiers (Step 21).
ORIGIN_CORE = "CORE"
ORIGIN_USE_CASE = "USE_CASE"
ORIGIN_USER_TYPE = "USER_TYPE"
ORIGIN_INPUT_TYPE = "INPUT_TYPE"
ORIGIN_JOB_TO_BE_DONE = "JOB_TO_BE_DONE"
ORIGIN_PROBLEM_PHRASE = "PROBLEM_PHRASE"
ORIGIN_ADJACENT_TOOL = "ADJACENT_TOOL"
ORIGIN_BROAD_BENCHMARK = "BROAD_BENCHMARK"

TIER_A = "A"
TIER_B = "B"
TIER_C = "C"

# Which origin/tier a generated angle belongs to.
_TIER_BY_ORIGIN = {
    ORIGIN_CORE: TIER_A,
    ORIGIN_USE_CASE: TIER_A,
    ORIGIN_INPUT_TYPE: TIER_A,
    ORIGIN_USER_TYPE: TIER_B,
    ORIGIN_JOB_TO_BE_DONE: TIER_B,
    ORIGIN_PROBLEM_PHRASE: TIER_B,
    ORIGIN_BROAD_BENCHMARK: TIER_B,
    ORIGIN_ADJACENT_TOOL: TIER_C,
}


def candidate_tier(maturity, origin):
    """A = strongest manual Semrush candidate, B = useful secondary, C = exploratory."""
    base = _TIER_BY_ORIGIN.get(origin, TIER_C)
    if maturity == MATURITY_BROAD and base == TIER_A:
        return TIER_B
    return base

_AI_TERMS = ["ai", "gpt", "llm", "openai", "claude", "anthropic", "gemini", "machine learning"]

_SUBJECT_STOPWORDS = {
    "ai", "a", "an", "the", "free", "online", "best", "top", "tool", "tools",
    "app", "apps", "web", "site", "website", "platform", "for", "and", "or",
    "with", "your", "my", "new", "pro", "plus", "easy", "simple", "fast",
    "quick", "instant", "smart", "auto", "automatic", "studio", "hq", "io",
    "dev", "labs", "lab", "beta", "get", "now", "make", "made", "use", "using",
    "it", "is", "of", "to", "in", "on", "that", "this",
    # launch prefixes and filler that never belong in a search term
    "launch", "hn", "show", "ask", "tell", "demo", "intro", "introducing",
    "all", "one", "stop", "smartest", "me", "personal", "your",
}


def _families_by_key():
    return {family["key"]: family for family in FUNCTION_FAMILIES}


def _domains_by_key():
    return {domain["key"]: domain for domain in DOMAIN_FAMILIES}


def _domain_phrase(cluster):
    domain = _domains_by_key().get(cluster.get("domain"))
    return domain["label"].lower() if domain else ""


def _family(cluster):
    return _families_by_key().get(cluster.get("function"))


def cluster_has_ai(cluster):
    for member in cluster.get("members", []):
        if has_phrase(product_text(member), _AI_TERMS):
            return True
    return False


def infer_broad_category(cluster):
    """Infer a broad but legitimate category (ai/video/pdf/...) from member text."""
    text = " ".join(product_text(member) for member in (cluster.get("members") or []))
    if not text:
        return ""
    for category, keywords in inferred_categories().items():
        if has_phrase(text, keywords):
            return category
    return ""


def extract_subject(name, function_keywords, brands=()):
    """Keep the meaningful nouns of a product name (drop function/brand/filler)."""
    dropped = set(function_keywords) | _SUBJECT_STOPWORDS
    kept = []
    for token in tokenize(name):
        if token == "by":
            break
        if token in dropped or len(token) < 2 or token.isdigit():
            continue
        kept.append(token)
    subject = " ".join(kept[:3])
    return strip_brand_tokens(subject, brands)


def _member_head_word(member, family):
    name = (member.get("name") or member.get("title") or "").lower()
    for head in family["head_words"]:
        if head in tokenize(name):
            return head
    return family["head_words"][0]


def intent_signature(keyword):
    """Identity of a keyword's search intent (used to avoid duplicate variants)."""
    from analyzers.keyword_quality import GENERIC_TOKENS

    tokens = set(tokenize(keyword)) - GENERIC_TOKENS
    return " ".join(sorted(tokens))


def generate_keyword_candidates(cluster, max_keywords=None):
    """Return deterministic keyword candidates with maturity labels.

    Each candidate: {"keyword", "priority", "type", "maturity", "reason"}.
    BRAND and AWKWARD phrases are never returned.
    """
    limit = max_keywords or CW.MAX_KEYWORDS_PER_CLUSTER
    domain = _domain_phrase(cluster)
    domain_key = cluster.get("domain")
    family = _family(cluster)
    has_ai = cluster_has_ai(cluster)
    is_multi_member = cluster.get("member_count", 0) >= 2
    domain_is_generic = bool(domain_key) and domain_key in GENERIC_DOMAINS
    allow_member_derived = member_derived_allowed(cluster)
    brands = cluster_brand_tokens(cluster)
    brand_filtered = []

    candidates = []
    seen = set()

    def add(keyword, priority, keyword_type, reason, origin=ORIGIN_CORE):
        phrase = " ".join(str(keyword).split()).lower()
        if not phrase or phrase in seen:
            return
        if len(phrase.split()) > CW.MAX_KEYWORD_WORDS:
            return
        maturity = keyword_maturity(phrase, cluster, brands)
        if maturity in (MATURITY_BRAND, MATURITY_AWKWARD):
            if maturity == MATURITY_BRAND:
                brand_filtered.append(phrase)
            return
        if not passes_quality(phrase, cluster):
            return
        if not (has_category_anchor(phrase) and has_function_anchor(phrase)):
            # a candidate must describe a tool search: anchor + function
            return
        seen.add(phrase)
        candidates.append({
            "keyword": phrase,
            "priority": priority,
            "type": keyword_type,
            "maturity": maturity,
            "origin": origin,
            "tier": candidate_tier(maturity, origin),
            "reason": reason,
            "cluster_id": cluster.get("cluster_id"),
            "cluster_label": cluster.get("cluster_label"),
        })

    # ---- no domain and no function: unclustered product name, offer nothing
    if not domain and not family:
        return []

    head_words = list(family["head_words"]) if family else []
    primary_head = head_words[0] if head_words else ""
    used_heads = [primary_head] if primary_head else []
    for head in head_words[1:]:
        if len(used_heads) >= CW.MAX_HEAD_WORD_VARIANTS:
            break
        used_heads.append(head)

    core_priority = "HIGH" if (domain_key and domain_key not in GENERIC_DOMAINS) else "MEDIUM"
    domain_templates_allowed = bool(domain) and not domain_is_generic

    # ---- domain core
    if domain and primary_head and domain_templates_allowed:
        add(f"{domain} {primary_head}", core_priority, "CORE_TOOL",
            f"direct {primary_head} intent for this domain", ORIGIN_CORE)

    # ---- member-derived cores (brand-stripped, anchor-required)
    if family and allow_member_derived:
        for member in cluster.get("members", []):
            raw_name = member.get("name") or member.get("title") or ""
            subject = extract_subject(raw_name, family["keywords"], brands)
            if not subject:
                continue
            if not has_category_anchor(subject):
                # no category anchor -> product-name fragment, not a search intent
                continue
            head = _member_head_word(member, family)
            if head not in used_heads:
                continue
            add(f"{subject} {head}", "HIGH", "CORE_TOOL",
                "matches a product in this cluster; brand-free and niche",
                ORIGIN_USE_CASE)

    # ---- inferred broad category when there is no *specific* domain
    if family and (not domain or domain_is_generic):
        category = infer_broad_category(cluster)
        # use the head word the products themselves use ("detector", not "checker")
        observed_heads = []
        for member in cluster.get("members", []):
            name_tokens = tokenize(member.get("name") or member.get("title") or "")
            for head_word in head_words:
                if head_word in name_tokens:
                    observed_heads.append(head_word)
                    break
        template_head = observed_heads[0] if observed_heads else primary_head
        if category and template_head:
            add(f"{category} {template_head}", "MEDIUM", "CORE_TOOL",
                f"clear {template_head} intent, but {category} is a broad crowded category",
                ORIGIN_BROAD_BENCHMARK)
            add(f"free {category} {template_head}", "LOW", "LONG_TAIL_TOOL",
                "broad category with a free-tier modifier", ORIGIN_BROAD_BENCHMARK)

    head = primary_head

    # ---- modifier variants
    if domain and head and domain_templates_allowed:
        add(f"free {domain} {head}", "HIGH", "LONG_TAIL_TOOL", "free-tier tool intent")
        add(f"online {domain} {head}", "MEDIUM", "LONG_TAIL_TOOL", "browser-based tool intent")
        if has_ai:
            add(f"ai {domain} {head}", "HIGH", "LONG_TAIL_TOOL", "AI-positioned cluster",
                ORIGIN_INPUT_TYPE)
        add(f"{domain} {head} tool", "MEDIUM", "LONG_TAIL_TOOL", "generic tool query",
            ORIGIN_ADJACENT_TOOL)
        # adjacent tool: the same domain with a secondary functional head word
        for extra_head in used_heads[1:]:
            add(f"{domain} {extra_head}", "MEDIUM", "CORE_TOOL",
                f"adjacent {extra_head} angle for the same domain", ORIGIN_ADJACENT_TOOL)

    # ---- problem query
    if family and domain and family.get("problem") and domain_templates_allowed:
        add(family["problem"].format(domain=domain), "MEDIUM", "PROBLEM_QUERY",
            "problem-aware search phrasing", ORIGIN_PROBLEM_PHRASE)

    # ---- audience-specific
    audience = DOMAIN_AUDIENCES.get(cluster.get("domain"))
    if audience and domain and head and domain_templates_allowed:
        add(f"{domain} {head} for {audience}", "MEDIUM", "AUDIENCE_SPECIFIC",
            f"targets {audience}", ORIGIN_USER_TYPE)

    # ---- comparison (at most one, multi-member only)
    if is_multi_member and domain and head and domain_templates_allowed:
        add(f"best {domain} {head}", "LOW", "COMPARISON",
            "comparison intent across the cluster's products", ORIGIN_BROAD_BENCHMARK)

    candidates.sort(key=lambda c: (
        _TIER_RANK.get(c["tier"], 9),
        _MATURITY_RANK.get(c["maturity"], 9),
        _PRIORITY_RANK[c["priority"]],
        _TYPE_RANK[c["type"]],
    ))
    cluster["brand_tokens"] = brands
    cluster["brand_filtered_keywords"] = sorted(set(brand_filtered))
    return candidates[:limit]


def _keyword_status(enrichment, cluster_id, keyword):
    """UNCHECKED / CHECKED / REJECTED for one candidate."""
    if not enrichment:
        return "UNCHECKED"
    from storage.enrichment_store import get_record

    record = get_record(enrichment, cluster_id, keyword)
    if not record:
        return "UNCHECKED"
    status = record.get("status") or "UNCHECKED"
    return status if status in ("CHECKED", "REJECTED") else "UNCHECKED"


def build_semrush_checklist(
    clusters,
    enrichment=None,
    min_keywords=None,
    max_keywords=None,
    max_clusters=None,
    per_cluster_min=None,
    per_cluster_max=None,
    include_checked=False,
):
    """Return the daily Semrush Check List.

    Priority (Phase 5): NICHE maturity > HIGH discovery-quality clusters >
    emerging products > direct tool intent > new intent coverage. BROAD
    benchmark terms are only used when the list would otherwise be nearly
    empty, and the list is never padded with weak variations.
    """
    maximum = max_keywords or CW.SEMRUSH_MAX_KEYWORDS
    cluster_limit = max_clusters or CW.SEMRUSH_MAX_CLUSTERS
    cluster_min = per_cluster_min or CW.SEMRUSH_PER_CLUSTER_MIN
    cluster_max = per_cluster_max or CW.SEMRUSH_PER_CLUSTER_MAX
    # At most this many BROAD "benchmark" phrases (crowded mature categories),
    # and never from a cluster that has niche terms of its own.
    broad_benchmark_cap = 3

    def _candidates(cluster):
        existing = cluster.get("keyword_candidates")
        return generate_keyword_candidates(cluster) if existing is None else existing

    def _eligible(cluster):
        eligible = []
        for candidate in _candidates(cluster):
            maturity = candidate.get("maturity") or keyword_maturity(candidate["keyword"])
            if maturity not in _MATURITY_RANK:
                continue                      # BRAND / AWKWARD never offered
            if not passes_quality(candidate["keyword"], cluster):
                continue
            status = _keyword_status(enrichment, cluster["cluster_id"], candidate["keyword"])
            if status != "UNCHECKED" and not include_checked:
                continue
            eligible.append((candidate, status, maturity))
        eligible.sort(key=lambda item: (
            _MATURITY_RANK[item[2]],
            _PRIORITY_RANK[item[0]["priority"]],
            _TYPE_RANK[item[0]["type"]],
        ))
        return eligible

    ranked = sorted(
        clusters,
        key=lambda c: (
            c.get("seo_score_status") == "VALIDATED",
            _DISCOVERY_RANK.get(c.get("discovery_quality"), 1),
            -c.get("opportunity_score", 0),
            -c.get("cluster_score", 0),
            c.get("cluster_id", ""),
        ),
    )

    top_clusters = []
    pools = {}
    for cluster in ranked:
        eligible = _eligible(cluster)
        if not eligible:
            continue
        pools[cluster["cluster_id"]] = eligible
        top_clusters.append(cluster)
        if len(top_clusters) >= cluster_limit:
            break

    entries = []
    used_intents = {}
    taken = {cluster["cluster_id"]: 0 for cluster in top_clusters}
    broad_taken = 0

    def _entry(cluster, candidate, status, maturity):
        seo_status = cluster.get("seo_score_status", "NOT_CHECKED")
        benchmark = maturity == MATURITY_BROAD
        why = candidate["reason"]
        why += "; non-brand" if maturity == MATURITY_NICHE else "; broad mature category"
        if benchmark:
            why += " - check only as a benchmark"
        return {
            "keyword": candidate["keyword"],
            "cluster_id": cluster["cluster_id"],
            "cluster_label": cluster["cluster_label"],
            "cluster_score": cluster["cluster_score"],
            "priority": candidate["priority"],
            "type": candidate["type"],
            "maturity": maturity,
            "keyword_status": status,
            "seo_status": seo_status,
            "checked": status != "UNCHECKED",
            "why": why,
        }

    # NICHE candidates first: a cluster with niche terms never falls back to
    # broad benchmark phrases.
    for cap in (cluster_min, cluster_max):
        for cluster in top_clusters:
            if len(entries) >= maximum:
                break
            pool = pools[cluster["cluster_id"]]
            for candidate, status, maturity in pool:
                if len(entries) >= maximum or taken[cluster["cluster_id"]] >= cap:
                    break
                if maturity == MATURITY_BROAD and broad_taken >= broad_benchmark_cap:
                    continue
                if candidate["keyword"] in {entry["keyword"] for entry in entries}:
                    continue
                signature = intent_signature(candidate["keyword"])
                cluster_intents = used_intents.setdefault(cluster["cluster_id"], set())
                if signature and signature in cluster_intents:
                    continue
                entries.append(_entry(cluster, candidate, status, maturity))
                taken[cluster["cluster_id"]] += 1
                if maturity == MATURITY_BROAD:
                    broad_taken += 1
                if signature:
                    cluster_intents.add(signature)

    order = {cluster["cluster_id"]: index for index, cluster in enumerate(top_clusters)}
    niche_first = {"NICHE": 0, "BROAD": 1}
    entries.sort(key=lambda e: (
        order[e["cluster_id"]],
        niche_first.get(e["maturity"], 2),
        _PRIORITY_RANK[e["priority"]],
        _TYPE_RANK[e["type"]],
    ))
    return entries[:maximum]


def attach_keyword_candidates(clusters):
    """Attach (and return) the generated ``keyword_candidates`` per cluster."""
    for cluster in clusters:
        if "keyword_candidates" not in cluster:
            cluster["keyword_candidates"] = generate_keyword_candidates(cluster)
        cluster.setdefault("brand_tokens", [])
        cluster.setdefault("brand_filtered_keywords", [])
    return clusters
