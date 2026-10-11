"""Manual Semrush enrichment store (Phase 3).

Human-editable, deterministic, versionable JSON committed to git. The stable
join key is ``cluster_id + normalized keyword`` so Phase 4/5 work and future
dashboards can join on it without a database.

Required fields for scoring: us_volume, global_volume, kd, weak_serp.
Optional fields (weak_serp_count, cpc, intent, notes) never block scoring.

No API calls, no database, no LLM.
"""

import json
import os
import re
from pathlib import Path

from config import timeutil

STORE_VERSION = 1

REQUIRED_FIELDS = ("us_volume", "global_volume", "kd", "weak_serp")
OPTIONAL_FIELDS = ("weak_serp_count", "cpc", "intent", "notes")
METRIC_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

STATUS_UNCHECKED = "UNCHECKED"
STATUS_CHECKED = "CHECKED"
STATUS_REJECTED = "REJECTED"
STATUSES = (STATUS_UNCHECKED, STATUS_CHECKED, STATUS_REJECTED)


def default_path():
    return Path(__file__).resolve().parents[1] / "data" / "enrichment" / "keywords.json"


def normalize_keyword(keyword):
    """Lowercase and collapse whitespace so lookups are stable and mergeable."""
    text = (keyword or "").strip().lower()
    return re.sub(r"\s+", " ", text)


def record_key(cluster_id, keyword):
    """Stable join key: cluster_id + normalized keyword."""
    return f"{cluster_id}|{normalize_keyword(keyword)}"


def empty_store():
    return {"version": STORE_VERSION, "updated_at": None, "records": {}}


def load_store(path=None):
    """Load the store; a missing or unreadable file yields an empty store."""
    store_path = Path(path) if path is not None else default_path()
    if not store_path.exists():
        return empty_store()
    try:
        data = json.loads(store_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_store()
    if not isinstance(data, dict):
        return empty_store()
    data.setdefault("version", STORE_VERSION)
    data.setdefault("updated_at", None)
    if not isinstance(data.get("records"), dict):
        data["records"] = {}
    return data


def save_store(store, path=None):
    """Write the store atomically so a crash cannot corrupt manual data."""
    store_path = Path(path) if path is not None else default_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store["version"] = STORE_VERSION
    payload = json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp_path = store_path.with_name(store_path.name + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, store_path)
    return store_path


def get_record(store, cluster_id, keyword):
    if not store:
        return None
    return (store.get("records") or {}).get(record_key(cluster_id, keyword))


def _snapshot(record):
    snapshot = {"checked_at": record.get("checked_at")}
    for field in METRIC_FIELDS:
        snapshot[field] = record.get(field)
    return snapshot


def _coerce(field, value):
    if value is None or value == "":
        return None
    if field in ("us_volume", "global_volume", "kd", "weak_serp_count"):
        try:
            return int(str(value).replace(",", "").strip())
        except (TypeError, ValueError):
            return None
    if field == "weak_serp":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("y", "yes", "true", "1"):
            return True
        if text in ("n", "no", "false", "0"):
            return False
        return None
    if field == "cpc":
        try:
            return float(str(value).replace("$", "").replace(",", "").strip())
        except (TypeError, ValueError):
            return None
    return str(value).strip()


def is_checked(record):
    """True when every required scoring field is present."""
    if not record or record.get("status") != STATUS_CHECKED:
        return False
    return all(record.get(field) is not None for field in REQUIRED_FIELDS)


def upsert_metrics(store, cluster_id, keyword, metrics, checked_at=None, path=None):
    """Insert or update one keyword's metrics, preserving prior observations.

    Only the supplied (non-empty) fields are changed, so a single field can be
    edited later. When any metric actually changes, the previous observation is
    appended to ``history`` before the record is updated.
    """
    now = checked_at or timeutil.now().isoformat(timespec="seconds")
    normalized = normalize_keyword(keyword)
    records = store.setdefault("records", {})
    key = record_key(cluster_id, normalized)
    record = records.get(key)

    if record is None:
        record = {
            "cluster_id": cluster_id,
            "keyword": normalized,
            "status": STATUS_CHECKED,
            "rejection_reason": "",
            "history": [],
        }
        for field in METRIC_FIELDS:
            record[field] = None
        record["checked_at"] = None
        records[key] = record

    # Capture the previous observation BEFORE mutating, so history keeps the
    # old metrics (KD 12 -> 24 -> 41 stays recoverable).
    previous = _snapshot(record) if record.get("checked_at") else None

    changed = False
    for field in METRIC_FIELDS:
        raw = metrics.get(field) if isinstance(metrics, dict) else None
        if raw is None or raw == "":
            continue
        value = _coerce(field, raw)
        if value is None:
            continue
        if record.get(field) != value:
            changed = True
            record[field] = value

    if changed and previous is not None:
        record.setdefault("history", []).append(previous)

    record["checked_at"] = now
    record["status"] = STATUS_CHECKED
    record["rejection_reason"] = ""
    store["updated_at"] = now

    if path is not None:
        save_store(store, path)
    return record


def set_status(store, cluster_id, keyword, status, reason="", path=None):
    """Set UNCHECKED / CHECKED / REJECTED (plus an optional rejection reason)."""
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    normalized = normalize_keyword(keyword)
    records = store.setdefault("records", {})
    key = record_key(cluster_id, normalized)
    record = records.get(key)
    if record is None:
        record = {
            "cluster_id": cluster_id,
            "keyword": normalized,
            "checked_at": None,
            "history": [],
        }
        for field in METRIC_FIELDS:
            record[field] = None
        records[key] = record
    record["status"] = status
    record["rejection_reason"] = reason if status == STATUS_REJECTED else ""
    store["updated_at"] = timeutil.now().isoformat(timespec="seconds")
    if path is not None:
        save_store(store, path)
    return record


def reject_keyword(store, cluster_id, keyword, reason="", path=None):
    return set_status(store, cluster_id, keyword, STATUS_REJECTED, reason, path)


def records_for(store, cluster_id=None, status=None):
    """List records, optionally filtered by cluster and/or status."""
    result = []
    for record in (store.get("records") or {}).values():
        if cluster_id is not None and record.get("cluster_id") != cluster_id:
            continue
        if status is not None and record.get("status") != status:
            continue
        result.append(record)
    return sorted(result, key=lambda r: (r.get("cluster_id", ""), r.get("keyword", "")))


def status_for(store, cluster_id, keyword):
    record = get_record(store, cluster_id, keyword)
    if not record:
        return STATUS_UNCHECKED
    status = record.get("status")
    return status if status in STATUSES else STATUS_UNCHECKED
