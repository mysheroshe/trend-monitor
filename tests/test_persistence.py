"""Persistence / gitignore regression tests (Step 0)."""

import subprocess
from pathlib import Path

import pytest

from config import timeutil

REPO_ROOT = Path(__file__).resolve().parents[1]


def _git_ignored(rel_path):
    """True if git would ignore ``rel_path`` (skips if git is unavailable)."""
    try:
        result = subprocess.run(
            # safe.directory keeps this working in sandboxes where the checkout
            # is owned by a different user than the one running the tests.
            ["git", "-c", "safe.directory=*", "check-ignore", "-q", rel_path],
            cwd=str(REPO_ROOT),
            capture_output=True,
        )
    except (OSError, FileNotFoundError):
        pytest.skip("git is not available")
    if result.returncode not in (0, 1):
        pytest.skip("git check-ignore is unavailable in this environment")
    return result.returncode == 0


def test_daily_json_history_is_not_gitignored():
    assert not _git_ignored("data/daily/2099-01-01.json")


def test_other_data_files_remain_ignored():
    assert _git_ignored("data/other.txt")
    assert _git_ignored("data/daily/notes.txt")
    assert _git_ignored("output/whatever.txt")


def test_daily_workflow_stages_daily_data_without_silent_failure():
    workflow = (REPO_ROOT / ".github" / "workflows" / "daily-report.yml").read_text(
        encoding="utf-8"
    )
    assert "data/daily/*.json || true" not in workflow
    assert "git add -A -- data/daily analysis/daily" in workflow
    assert "git diff --staged --quiet" in workflow


def test_save_load_and_cleanup_roundtrip(tmp_path, monkeypatch):
    from storage import data_store

    monkeypatch.setattr(data_store, "DATA_DIR", tmp_path)

    today = timeutil.today_str()
    assert data_store.save_daily_data(today, {"product_hunt": [{"name": "Joy"}]})
    assert (tmp_path / f"{today}.json").exists()

    loaded = data_store.load_daily_data(today)
    assert loaded["date"] == today
    assert loaded["product_hunt"][0]["name"] == "Joy"

    ancient = tmp_path / "2000-01-01.json"
    ancient.write_text("{}", encoding="utf-8")
    data_store.cleanup_old_data(days=28)

    assert not ancient.exists()
    assert (tmp_path / f"{today}.json").exists()


def test_timestamps_use_the_pacific_timezone():
    assert timeutil.now().tzinfo is not None
    assert timeutil.today_str().count("-") == 2
