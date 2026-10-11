"""Deterministic SEO keyword candidate generation (Phase 2/3).

Goal: produce a short, sensible list of search terms worth checking manually
in Semrush. This module does not predict search volume or difficulty, does not
call any external service, and filters out generic/brand-like phrases that
cannot reveal a genuine product opportunity (Phase 3, Step 3).
"""

from analyzers.clustering import DOMAIN_AUDIENCES, DOMAIN_FAMILIES, FUNCTION_FAMILIES
from analyzers.keyword_quality import (
    GENERIC_DOMAINS,
    GENERIC_TOKENS,
    member_derived_allowed,
    passes_quality,
)
from analyzers.text_utils import has_phrase, product_text, tokenize
from config import cluster_weights as CW

# Priority + type ordering used for sorting the shortlist.
_PRIORITY_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
_TYPE_RANK = {
    "CORE_TOOL": 0,
    "LONG_TAIL_TOOL": 1,
    "PROBLEM_QUERY": 2,
    "AUDIENCE_SPECIFIC": 3,
    "COMPARISON": 4,
}

_AI_TERMS = ["ai", "gpt", "llm", "openai", "claude", "anthropic", "gemini", "machine learning"]

# Tokens dropped when deriving a keyword subject from a product name.
_SUBJECT_STOPWORDS = {
    "ai", "a", "an", "the", "free", "online", "best", "top", "tool", "tools",
    "app", "apps", "web", "site", "website", "platform", "for", "and", "or",
    "with", "your", "my", "new", "pro", "plus", "easy", "simple", "fast",
    "quick", "instant", "smart", "auto", "automatic", "studio", "hq", "io",
    "dev", "labs", "lab", "beta", "get", "now", "make", "made", "use", "using",
    "it", "is", "of", "to", "in", "on", "that", "this",
    # Hacker News / launch prefixes that never belong in a search term
    "launch", "hn", "show", "ask", "tell", "demo", "intro", "introducing",
}


def _families_by_key():
    return {family["key"]: family for family in FUNCTION_FAMILIES}


def _domains_by_key():
    return {domain["key"]: domain for domain in DOMAIN_FAMILIES}


def _domain_phrase(cluster):
    """Lowercase human phrase for the cluster's domain, e.g. 'qr code'."""
    domain = _domains_by_key().get(cluster.get("domain"))
    return domain["label"].lower() if domain else ""


def _family(cluster):
    return _families_by_key().get(cluster.get("function"))


def cluster_has_ai(cluster):
    for member in cluster.get("members", []):
        if has_phrase(product_text(member), _AI_TERMS):
            return True
    return False


def extract_subject(name, function_keywords):
    """Keep the meaningful nouns of a product name (drop function/boilerplate)."""
    dropped = set(function_keywords) | _SUBJECT_STOPWORDS
    kept = []
    for token in tokenize(name):
        if token == "by":
            break                        # "Composer 2 by Cursor" -> "composer 2"
        if token in dropped or len(token) < 2 or token.isdigit():
            continue
        kept.append(token)
    return " ".join(kept[:3])


def _member_head_word(member, family):
    """The head word a member actually uses, or the family's primary head word."""
    name = (member.get("name") or member.get("title") or "").lower()
    for head in family["head_words"]:
        if head in tokenize(name):
            return head
    return family["head_words"][0]


def intent_signature(keyword):
    """Identity of a keyword's search intent (used to avoid duplicate variants)."""
    tokens = set(tokenize(keyword)) - GENERIC_TOKENS
    return " ".join(sorted(tokens))


def generate_keyword_candidates(cluster, max_keywords=None):
    """Return up to ``max_keywords`` deterministic keyword candidates.

    Each candidate: {"keyword", "priority", "type", "reason"}.
    """
    limit = max_keywords or CW.MAX_KEYWORDS_PER_CLUSTER
    domain = _domain_phrase(cluster)
    domain_key = cluster.get("domain")
    family = _family(cluster)
    has_ai = cluster_has_ai(cluster)
    is_multi_member = cluster.get("member_count", 0) >= 2
    domain_is_generic = bool(domain_key) and domain_key in GENERIC_DOMAINS
    allow_member_derived = member_derived_allowed(cluster)

    candidates = []
    seen = set()

    def add(keyword, priority, keyword_type, reason):
        phrase = " ".join(str(keyword).split()).lower()
        if not phrase or phrase in seen:
            return
        if len(phrase.split()) > CW.MAX_KEYWORD_WORDS:
            return
        if not passes_quality(phrase, cluster):
            return
        seen.add(phrase)
        candidates.append({
            "keyword": phrase,
            "priority": priority,
            "type": keyword_type,
            "reason": reason,
            "cluster_id": cluster.get("cluster_id"),
            "cluster_label": cluster.get("cluster_label"),
        })

    # ---- no domain and no function: this is an unclustered product, i.e. a
    # product name rather than a search intent. Offer nothing (Phase 3, Step 3
    # excludes obvious brand/product-name queries).
    if not domain and not family:
        return []

    # ---- head words shared by the cluster (capped to avoid permutations)
    head_words = list(family["head_words"]) if family else []
    primary_head = head_words[0] if head_words else ""
    used_heads = [primary_head] if primary_head else []
    for head in head_words[1:]:
        if len(used_heads) >= CW.MAX_HEAD_WORD_VARIANTS:
            break
        used_heads.append(head)

    # Broad domains are only useful with a specific subject attached, so their
    # generic core terms are deprioritised rather than promoted.
    core_priority = "HIGH" if (domain_key and domain_key not in GENERIC_DOMAINS) else "MEDIUM"
    domain_templates_allowed = bool(domain) and not domain_is_generic

    # ---- domain core (CORE_TOOL)
    if domain and primary_head and domain_templates_allowed:
        add(f"{domain} {primary_head}", core_priority, "CORE_TOOL",
            f"direct {primary_head} intent for this domain")

    # ---- member-derived cores (CORE_TOOL) — the most specific candidates
    if family and allow_member_derived:
        for member in cluster.get("members", []):
            subject = extract_subject(
                member.get("name") or member.get("title") or "", family["keywords"]
            )
            if not subject:
                continue
            head = _member_head_word(member, family)
            if head not in used_heads:
                continue
            add(f"{subject} {head}", "HIGH", "CORE_TOOL",
                "matches a product in this cluster")

    head = primary_head

    # ---- modifier variants (LONG_TAIL_TOOL), compatibility-checked
    if domain and head and domain_templates_allowed:
        add(f"free {domain} {head}", "HIGH", "LONG_TAIL_TOOL", "free-tier tool intent")
        add(f"online {domain} {head}", "MEDIUM", "LONG_TAIL_TOOL", "browser-based tool intent")
        if has_ai:
            add(f"ai {domain} {head}", "HIGH", "LONG_TAIL_TOOL", "AI-positioned cluster")
        add(f"{domain} {head} tool", "MEDIUM", "LONG_TAIL_TOOL", "generic tool query")

    # ---- problem query (PROBLEM_QUERY)
    if family and domain and family.get("problem") and domain_templates_allowed:
        add(family["problem"].format(domain=domain), "MEDIUM", "PROBLEM_QUERY",
            "problem-aware search phrasing")

    # ---- audience-specific (AUDIENCE_SPECIFIC) — only when a role is known
    audience = DOMAIN_AUDIENCES.get(cluster.get("domain"))
    if audience and domain and head and domain_templates_allowed:
        add(f"{domain} {head} for {audience}", "MEDIUM", "AUDIENCE_SPECIFIC",
            f"targets {audience}")

    # ---- comparison (COMPARISON) — at most one, only for multi-member clusters
    if is_multi_member and domain and head and domain_templates_allowed:
        add(f"best {domain} {head}", "LOW", "COMPARISON",
            "comparison intent across the cluster's products")

    candidates.sort(key=lambda c: (_PRIORITY_RANK[c["priority"]], _TYPE_RANK[c["type"]]))
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
    """Return the daily Semrush Check List (highest-value candidates only).

    Ordering rules (Phase 3, Step 9): clusters without SEO validation first,
    then UNCHECKED keywords, HIGH priority first, niche/domain-specific terms
    before broad ones, and never several variants of the same search intent.
    """
    minimum = min_keywords or CW.SEMRUSH_MIN_KEYWORDS
    maximum = max_keywords or CW.SEMRUSH_MAX_KEYWORDS
    cluster_limit = max_clusters or CW.SEMRUSH_MAX_CLUSTERS
    cluster_min = per_cluster_min or CW.SEMRUSH_PER_CLUSTER_MIN
    cluster_max = per_cluster_max or CW.SEMRUSH_PER_CLUSTER_MAX

    def _candidates(cluster):
        existing = cluster.get("keyword_candidates")
        if existing is None:
            return generate_keyword_candidates(cluster)
        return existing

    def _eligible(cluster):
        """Candidates worth offering, best first."""
        eligible = []
        for candidate in _candidates(cluster):
            if not passes_quality(candidate["keyword"], cluster):
                continue
            status = _keyword_status(enrichment, cluster["cluster_id"], candidate["keyword"])
            if status != "UNCHECKED" and not include_checked:
                continue
            eligible.append((candidate, status))
        eligible.sort(key=lambda item: (_PRIORITY_RANK[item[0]["priority"]], _TYPE_RANK[item[0]["type"]]))
        return eligible

    # Unvalidated clusters come first, then highest cluster score. Clusters
    # that offer no usable candidate are skipped entirely, so a day whose top
    # clusters are unclustered/too-generic products still produces a checklist
    # from the best clusters that actually have search intent.
    ranked = sorted(
        clusters,
        key=lambda c: (
            c.get("seo_score_status") == "VALIDATED",
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
    order = {cluster["cluster_id"]: index for index, cluster in enumerate(top_clusters)}

    entries = []
    # Intent de-duplication is per cluster: two different clusters are two
    # different opportunities, but within a cluster we never offer the same
    # search intent twice.
    used_intents = {}
    taken = {cluster["cluster_id"]: 0 for cluster in top_clusters}

    def _entry(cluster, candidate, status):
        seo_status = cluster.get("seo_score_status", "NOT_CHECKED")
        return {
            "keyword": candidate["keyword"],
            "cluster_id": cluster["cluster_id"],
            "cluster_label": cluster["cluster_label"],
            "cluster_score": cluster["cluster_score"],
            "priority": candidate["priority"],
            "type": candidate["type"],
            "keyword_status": status,
            "seo_status": seo_status,
            "checked": status != "UNCHECKED",
            "why": (
                f"{candidate['reason']}; cluster '{cluster['cluster_label']}' scores "
                f"{cluster['cluster_score']}/100 from {cluster['member_count']} product(s) "
                f"across {cluster['source_diversity']} source(s); SEO {seo_status}"
            ),
        }

    # Two staged passes guarantee coverage: at least `cluster_min` per cluster
    # before any cluster is allowed to contribute up to `cluster_max`.
    for cap in (cluster_min, cluster_max):
        for cluster in top_clusters:
            if len(entries) >= maximum:
                break
            for candidate, status in pools[cluster["cluster_id"]]:
                if len(entries) >= maximum:
                    break
                if taken[cluster["cluster_id"]] >= cap:
                    break
                if candidate["keyword"] in {e["keyword"] for e in entries}:
                    continue
                signature = intent_signature(candidate["keyword"])
                cluster_intents = used_intents.setdefault(cluster["cluster_id"], set())
                if signature and signature in cluster_intents:
                    continue
                entries.append(_entry(cluster, candidate, status))
                taken[cluster["cluster_id"]] += 1
                if signature:
                    cluster_intents.add(signature)

    entries.sort(
        key=lambda e: (
            order[e["cluster_id"]],
            _PRIORITY_RANK[e["priority"]],
            _TYPE_RANK[e["type"]],
        )
    )
    if len(entries) > maximum:
        entries = entries[:maximum]
    return entries


def attach_keyword_candidates(clusters):
    """Attach (and return) the generated ``keyword_candidates`` per cluster."""
    for cluster in clusters:
        if "keyword_candidates" not in cluster:
            cluster["keyword_candidates"] = generate_keyword_candidates(cluster)
    return clusters
