"""Manual enrichment storage tests (Phase 3, Steps 1, 4, 10)."""

from storage import enrichment_store as es


def test_upsert_and_load_by_stable_cluster_keyword(tmp_path):
    path = tmp_path / "keywords.json"
    store = es.load_store(path)

    es.upsert_metrics(
        store, "tattoo-generation", "Tattoo   Generator",
        {"us_volume": "18,100", "global_volume": 28900, "kd": 51, "weak_serp": "yes"},
        path=path,
    )

    reloaded = es.load_store(path)
    record = es.get_record(reloaded, "tattoo-generation", "tattoo generator")

    assert record is not None
    assert record["keyword"] == "tattoo generator"      # normalized
    assert record["us_volume"] == 18100                 # "18,100" coerced
    assert record["global_volume"] == 28900
    assert record["kd"] == 51
    assert record["weak_serp"] is True
    assert record["status"] == "CHECKED"
    assert es.is_checked(record)


def test_optional_fields_never_block_scoring(tmp_path):
    store = es.load_store(None)
    record = es.upsert_metrics(
        store, "pdf-conversion", "pdf converter",
        {"us_volume": 1200, "global_volume": 3000, "kd": 20, "weak_serp": "no"},
    )

    assert record["cpc"] is None
    assert record["intent"] is None
    assert record["notes"] is None
    assert record["weak_serp_count"] is None
    assert es.is_checked(record)


def test_partial_update_keeps_other_fields(tmp_path):
    path = tmp_path / "keywords.json"
    store = es.load_store(path)
    es.upsert_metrics(store, "pdf-conversion", "pdf converter",
                      {"us_volume": 1200, "global_volume": 3000, "kd": 20, "weak_serp": True},
                      path=path)

    store = es.load_store(path)
    es.upsert_metrics(store, "pdf-conversion", "pdf converter", {"kd": 27}, path=path)
    record = es.get_record(es.load_store(path), "pdf-conversion", "pdf converter")

    assert record["kd"] == 27
    assert record["us_volume"] == 1200
    assert record["weak_serp"] is True


def test_recheck_preserves_previous_metrics_and_checked_at(tmp_path):
    path = tmp_path / "keywords.json"
    store = es.load_store(path)
    keyword = "tattoo generator"

    es.upsert_metrics(store, "tattoo-generation", keyword,
                      {"us_volume": 320, "global_volume": 900, "kd": 12, "weak_serp": True},
                      checked_at="2026-09-01T10:00:00-07:00", path=path)
    store = es.load_store(path)
    es.upsert_metrics(store, "tattoo-generation", keyword, {"kd": 24},
                      checked_at="2026-10-01T10:00:00-07:00", path=path)
    store = es.load_store(path)
    es.upsert_metrics(store, "tattoo-generation", keyword, {"kd": 41},
                      checked_at="2026-10-11T10:00:00-07:00", path=path)

    record = es.get_record(es.load_store(path), "tattoo-generation", keyword)

    assert record["kd"] == 41
    assert record["checked_at"] == "2026-10-11T10:00:00-07:00"
    assert [snapshot["kd"] for snapshot in record["history"]] == [12, 24]
    assert record["history"][0]["checked_at"] == "2026-09-01T10:00:00-07:00"
    assert record["history"][0]["us_volume"] == 320


def test_resaving_identical_values_does_not_duplicate_history(tmp_path):
    path = tmp_path / "keywords.json"
    store = es.load_store(path)
    metrics = {"us_volume": 500, "global_volume": 900, "kd": 20, "weak_serp": True}

    es.upsert_metrics(store, "pdf-conversion", "pdf converter", metrics, path=path)
    store = es.load_store(path)
    es.upsert_metrics(store, "pdf-conversion", "pdf converter", metrics, path=path)

    record = es.get_record(es.load_store(path), "pdf-conversion", "pdf converter")
    assert record["history"] == []


def test_status_transitions_and_rejection_reason(tmp_path):
    path = tmp_path / "keywords.json"
    store = es.load_store(path)

    assert es.status_for(store, "tattoo-generation", "tattoo generator") == es.STATUS_UNCHECKED

    es.reject_keyword(store, "tattoo-generation", "tattoo generator",
                      reason="too broad", path=path)
    store = es.load_store(path)
    record = es.get_record(store, "tattoo-generation", "tattoo generator")
    assert record["status"] == es.STATUS_REJECTED
    assert record["rejection_reason"] == "too broad"
    assert es.status_for(store, "tattoo-generation", "tattoo generator") == es.STATUS_REJECTED

    es.set_status(store, "tattoo-generation", "tattoo generator", es.STATUS_UNCHECKED, path=path)
    store = es.load_store(path)
    assert es.status_for(store, "tattoo-generation", "tattoo generator") == es.STATUS_UNCHECKED

    es.reject_keyword(store, "tattoo-generation", "tattoo generator", reason="brand-only", path=path)
    store = es.load_store(path)
    es.upsert_metrics(store, "tattoo-generation", "tattoo generator",
                      {"us_volume": 900, "global_volume": 1200, "kd": 25, "weak_serp": False},
                      path=path)
    record = es.get_record(es.load_store(path), "tattoo-generation", "tattoo generator")
    assert record["status"] == es.STATUS_CHECKED
    assert record["rejection_reason"] == ""


def test_records_for_filters_by_cluster_and_status(tmp_path):
    store = es.load_store(None)
    es.upsert_metrics(store, "a:one", "kw one",
                      {"us_volume": 100, "global_volume": 200, "kd": 10, "weak_serp": True})
    es.reject_keyword(store, "b:two", "kw two", reason="duplicate intent")

    assert len(es.records_for(store)) == 2
    assert [r["keyword"] for r in es.records_for(store, cluster_id="a:one")] == ["kw one"]
    assert [r["keyword"] for r in es.records_for(store, status="REJECTED")] == ["kw two"]
