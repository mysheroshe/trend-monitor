"""SEO keyword candidate tests (Phase 2, Steps 5-7)."""

from analyzers.keyword_candidates import build_semrush_checklist
from config import cluster_weights as CW

MODIFIERS = {"free", "online", "ai", "best"}
GENERATION_HEADS = {"generator", "maker", "creator"}


def _keywords(cluster):
    return [c["keyword"] for c in cluster["keyword_candidates"]]


def test_tattoo_cluster_produces_sensible_keywords(cluster_builder, tattoo_products):
    clusters = cluster_builder(tattoo_products)
    tattoo = [c for c in clusters if c["cluster_id"] == "tattoo-generation"][0]
    keywords = _keywords(tattoo)

    assert "tattoo generator" in keywords
    assert "free tattoo generator" in keywords
    assert "ai tattoo generator" in keywords
    assert all("tattoo" in keyword for keyword in keywords)
    assert CW.MIN_KEYWORDS_PER_CLUSTER <= len(keywords) <= CW.MAX_KEYWORDS_PER_CLUSTER


def test_audio_utility_clusters_produce_sensible_keywords(cluster_builder, audio_products):
    clusters = cluster_builder(audio_products)
    by_id = {c["cluster_id"]: c for c in clusters}

    assert set(by_id) == {"audio-finding", "audio-changing", "audio-removal"}
    assert "bpm finder" in _keywords(by_id["audio-finding"])
    assert "song key finder" in _keywords(by_id["audio-finding"])
    assert "pitch changer" in _keywords(by_id["audio-changing"])
    assert "vocal remover" in _keywords(by_id["audio-removal"])


def test_audio_subclusters_are_not_merged_into_one_blob(cluster_builder, audio_products):
    clusters = cluster_builder(audio_products)
    assert len(clusters) == 3
    assert all(cluster["member_count"] <= 2 for cluster in clusters)


def test_nonsense_keyword_combinations_are_not_generated(cluster_builder, tattoo_products, audio_products):
    clusters = cluster_builder(list(tattoo_products) + list(audio_products))

    for cluster in clusters:
        for candidate in cluster["keyword_candidates"]:
            keyword = candidate["keyword"]
            tokens = keyword.split()
            assert keyword == keyword.lower()
            assert keyword.strip() == keyword
            assert "  " not in keyword
            assert 1 <= len(tokens) <= CW.MAX_KEYWORD_WORDS
            # never stack two modifiers ("free online x", "ai how to ...")
            assert len(MODIFIERS & set(tokens)) <= 1
            assert not keyword.startswith(("free online", "ai free", "ai online"))


def test_duplicate_intent_keywords_are_deduplicated(cluster_builder, tattoo_products):
    clusters = cluster_builder(tattoo_products)
    keywords = _keywords(clusters[0])

    assert len(keywords) == len(set(keywords))
    heads = {keyword.split()[-1] for keyword in keywords} & GENERATION_HEADS
    assert len(heads) <= CW.MAX_HEAD_WORD_VARIANTS


def test_keyword_count_respects_the_configured_maximum(cluster_builder, tattoo_products, audio_products):
    clusters = cluster_builder(list(tattoo_products) + list(audio_products))
    for cluster in clusters:
        assert len(cluster["keyword_candidates"]) <= CW.MAX_KEYWORDS_PER_CLUSTER


def test_semrush_checklist_only_contains_top_ranked_candidates(
    cluster_builder, tattoo_products, audio_products
):
    clusters = cluster_builder(list(tattoo_products) + list(audio_products))
    checklist = build_semrush_checklist(clusters)

    assert CW.SEMRUSH_MIN_KEYWORDS <= len(checklist) <= CW.SEMRUSH_MAX_KEYWORDS
    assert all(entry["priority"] in ("HIGH", "MEDIUM") for entry in checklist)

    rank_of = {c["cluster_id"]: c["cluster_rank"] for c in clusters}
    ranks = [rank_of[entry["cluster_id"]] for entry in checklist]
    assert ranks == sorted(ranks)
    assert ranks[0] == min(ranks)

    # only clusters with usable candidates contribute, capped at the configured
    # number of clusters, and the best cluster leads
    contributing = []
    for entry in checklist:
        if entry["cluster_id"] not in contributing:
            contributing.append(entry["cluster_id"])
    assert len(contributing) <= CW.SEMRUSH_MAX_CLUSTERS
    assert checklist[0]["cluster_id"] == clusters[0]["cluster_id"]
    assert checklist[0]["priority"] == "HIGH"


def test_checklist_reports_required_fields(cluster_builder, tattoo_products, audio_products):
    clusters = cluster_builder(list(tattoo_products) + list(audio_products))
    checklist = build_semrush_checklist(clusters)
    for entry in checklist:
        for field in ("keyword", "cluster_label", "priority", "type", "why"):
            assert entry[field]
