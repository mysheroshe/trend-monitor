"""Validation evidence + verdict history tests (Phase 4, Steps 8 and 14)."""

from storage import validation_store as vs


def test_evidence_round_trip(tmp_path):
    path = tmp_path / "evidence.json"
    store = vs.load_store(path)

    vs.add_evidence(
        store, "tattoo-generation", "COMPETITOR", "positive",
        "Multiple standalone tattoo AI tools monetise via credits",
        source="manual", note="checked 3 pricing pages",
        path=path,
    )

    reloaded = vs.load_store(path)
    records = vs.evidence_for(reloaded, "tattoo-generation")

    assert len(records) == 1
    record = records[0]
    assert record["cluster_id"] == "tattoo-generation"
    assert record["evidence_type"] == "COMPETITOR"
    assert record["sentiment"] == "positive"
    assert record["source"] == "manual"
    assert record["note"] == "checked 3 pricing pages"
    assert record["checked_at"]
    assert record["evidence_id"].startswith("ev-")


def test_evidence_normalizes_type_and_sentiment(tmp_path):
    store = vs.load_store(None)
    record = vs.add_evidence(store, "c1", "community_pain", "POS", "people complain about X")
    assert record["evidence_type"] == "COMMUNITY_PAIN"
    assert record["sentiment"] == "positive"

    record = vs.add_evidence(store, "c1", "not-a-type", "maybe", "unclear")
    assert record["evidence_type"] == "OTHER"
    assert record["sentiment"] == "neutral"


def test_evidence_does_not_require_a_url(tmp_path):
    path = tmp_path / "evidence.json"
    store = vs.load_store(path)
    vs.add_evidence(store, "c1", "TREND_SIGNAL", "positive", "noticed a trend", path=path)
    record = vs.evidence_for(vs.load_store(path), "c1")[0]
    assert record["url"] == ""


def test_evidence_summary_counts_types_and_sentiment():
    store = vs.load_store(None)
    vs.add_evidence(store, "c1", "COMPETITOR", "positive", "a")
    vs.add_evidence(store, "c1", "COMPETITOR", "positive", "b")
    vs.add_evidence(store, "c1", "PAYMENT_SIGNAL", "positive", "c")
    vs.add_evidence(store, "c1", "SUBSTITUTION", "negative", "d")
    vs.add_evidence(store, "c1", "OTHER", "neutral", "e")

    summary = vs.evidence_summary(store, "c1")

    assert summary["total"] == 5
    assert summary["positive"] == 3
    assert summary["neutral"] == 1
    assert summary["negative"] == 1
    assert summary["types"]["COMPETITOR"] == 2
    assert set(summary["positive_types"]) == {"COMPETITOR", "PAYMENT_SIGNAL"}
    assert summary["negative_types"] == ["SUBSTITUTION"]


def test_verdict_history_records_changes_only(tmp_path):
    path = tmp_path / "evidence.json"
    store = vs.load_store(path)

    first = vs.record_verdict(store, "tattoo-generation", "WATCH", reason="too early",
                              date="2026-10-09", path=path)
    assert first["changed"] is True
    assert first["previous"] is None

    again = vs.record_verdict(store, "tattoo-generation", "WATCH", date="2026-10-10", path=path)
    assert again["changed"] is False

    promoted = vs.record_verdict(store, "tattoo-generation", "TEST",
                                 reason="keyword demand found", date="2026-10-11", path=path)
    assert promoted["changed"] is True
    assert promoted["previous"] == "WATCH"

    reloaded = vs.load_store(path)
    history = vs.verdict_history_for(reloaded, "tattoo-generation")

    assert len(history) == 2
    assert history[0]["previous_verdict"] is None
    assert history[0]["new_verdict"] == "WATCH"
    assert history[1]["previous_verdict"] == "WATCH"
    assert history[1]["new_verdict"] == "TEST"
    assert history[1]["date"] == "2026-10-11"
    assert history[1]["reason"] == "keyword demand found"
    assert vs.current_verdict(reloaded, "tattoo-generation") == "TEST"


def test_verdict_history_is_isolated_per_cluster(tmp_path):
    store = vs.load_store(tmp_path / "evidence.json")
    vs.record_verdict(store, "a", "TEST", date="2026-10-11")
    vs.record_verdict(store, "b", "SKIP", date="2026-10-11")

    assert len(vs.verdict_history_for(store, "a")) == 1
    assert len(vs.verdict_history_for(store, "b")) == 1
    assert vs.verdict_history_for(store, "c") == []
