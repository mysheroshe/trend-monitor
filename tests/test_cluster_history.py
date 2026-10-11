"""Cluster history / repeat-signal tests (Phase 2, Step 9)."""

import json

from analyzers.clustering import analyze_clusters, load_history_clusters


def _day(tattoo=True):
    if tattoo:
        products = [{"name": "AI Tattoo Generator", "tagline": "Generate tattoo designs",
                     "link": "https://example.com/h1"}]
    else:
        products = [{"name": "Unrelated Newsletter", "tagline": "Weekly links",
                     "link": "https://example.com/h2"}]
    return {"date": "2026-10-09", "product_hunt": products}


def _current():
    return [{"name": "AI Tattoo Generator", "description": "Generate tattoo designs.",
             "_source": "toolify", "link": "https://example.com/t1"}]


def test_history_increments_days_seen(tmp_path, rank_suitable):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-10-09.json").write_text(json.dumps(_day()), encoding="utf-8")
    (history_dir / "2026-10-10.json").write_text(json.dumps(_day()), encoding="utf-8")

    clusters = analyze_clusters(
        rank_suitable(_current()), data_dir=history_dir, today="2026-10-11"
    )
    tattoo = [c for c in clusters if c["cluster_id"] == "tattoo-generation"][0]

    assert tattoo["days_seen"] == 3
    assert tattoo["repeat_appearances"] == 2
    assert tattoo["first_seen"] == "2026-10-09"
    assert tattoo["latest_seen"] == "2026-10-11"
    assert tattoo["seen_dates"] == ["2026-10-09", "2026-10-10", "2026-10-11"]


def test_missing_history_is_reported_not_fabricated(tmp_path, rank_suitable):
    clusters = analyze_clusters(
        rank_suitable(_current()), data_dir=tmp_path / "does-not-exist", today="2026-10-11"
    )
    cluster = clusters[0]

    assert cluster["days_seen"] == 1
    assert cluster["repeat_appearances"] == 0
    assert cluster["first_seen"] == "2026-10-11"
    assert cluster["history_note"]


def test_current_day_is_not_counted_twice(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-10-11.json").write_text(json.dumps(_day()), encoding="utf-8")
    (history_dir / "2026-10-10.json").write_text(json.dumps(_day()), encoding="utf-8")

    history = load_history_clusters(data_dir=history_dir, today="2026-10-11")

    assert set(history) == {"tattoo-generation"}
    assert history["tattoo-generation"]["dates"] == {"2026-10-10"}


def test_history_does_not_change_cluster_ids(tmp_path):
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "2026-10-10.json").write_text(json.dumps(_day()), encoding="utf-8")

    history = load_history_clusters(data_dir=history_dir, today="2026-10-11")
    assert list(history) == ["tattoo-generation"]
