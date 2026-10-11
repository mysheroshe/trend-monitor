"""Validation evidence + verdict history store (Phase 4).

Lightweight, human-editable JSON in git (``data/validation/evidence.json``).
No database, no API calls.

Two sections live in one file:
  * ``records``          - cluster_id -> [evidence ...]
  * ``verdict_history``  - append-only verdict changes
  * ``current_verdicts`` - cluster_id -> last known verdict (change detection)
"""

import hashlib
import json
import os
import re
from pathlib import Path

from config import timeutil

STORE_VERSION = 1

EVIDENCE_TYPES = (
    "COMMUNITY_PAIN", "COMPETITOR", "PAYMENT_SIGNAL", "SEARCH_SIGNAL",
    "TREND_SIGNAL", "SUBSTITUTION", "ACQUISITION", "OTHER",
)

SENTIMENTS = ("positive", "neutral", "negative")


def default_path():
    return Path(__file__).resolve().parents[1] / "data" / "validation" / "evidence.json"


def empty_store():
    return {
        "version": STORE_VERSION,
        "updated_at": None,
        "records": {},
        "current_verdicts": {},
        "verdict_history": [],
    }


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
    if not isinstance(data.get("current_verdicts"), dict):
        data["current_verdicts"] = {}
    if not isinstance(data.get("verdict_history"), list):
        data["verdict_history"] = []
    return data


def save_store(store, path=None):
    """Atomic write so a crash cannot corrupt manual evidence."""
    store_path = Path(path) if path is not None else default_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store["version"] = STORE_VERSION
    payload = json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp_path = store_path.with_name(store_path.name + ".tmp")
    tmp_path.write_text(payload, encoding="utf-8")
    os.replace(tmp_path, store_path)
    return store_path


def normalize_sentiment(value):
    text = (value or "").strip().lower()
    if text in ("pos", "positive", "+", "yes", "true"):
        return "positive"
    if text in ("neg", "negative", "-", "no", "false"):
        return "negative"
    return "neutral"


def normalize_evidence_type(value):
    text = re.sub(r"[^a-z_]", "", (value or "").strip().lower())
    for evidence_type in EVIDENCE_TYPES:
        if evidence_type.lower() == text:
            return evidence_type
    return "OTHER"


def _evidence_id(cluster_id, evidence_type, summary, checked_at):
    digest = hashlib.sha1(
        f"{cluster_id}|{evidence_type}|{summary}|{checked_at}".encode("utf-8")
    ).hexdigest()[:10]
    return f"ev-{digest}"


def add_evidence(store, cluster_id, evidence_type, sentiment, summary,
                 source="manual", url="", note="", checked_at=None, path=None):
    """Append one evidence record for a cluster."""
    now = checked_at or timeutil.now().isoformat(timespec="seconds")
    evidence_type = normalize_evidence_type(evidence_type)
    sentiment = normalize_sentiment(sentiment)
    record = {
        "evidence_id": _evidence_id(cluster_id, evidence_type, summary or "", now),
        "cluster_id": cluster_id,
        "evidence_type": evidence_type,
        "sentiment": sentiment,
        "source": source or "manual",
        "url": url or "",
        "note": note or "",
        "summary": summary or "",
        "checked_at": now,
    }
    store.setdefault("records", {}).setdefault(cluster_id, []).append(record)
    store["updated_at"] = now
    if path is not None:
        save_store(store, path)
    return record


def evidence_for(store, cluster_id):
    """All evidence records for a cluster, oldest first."""
    records = (store.get("records") or {}).get(cluster_id) or []
    return sorted(records, key=lambda r: r.get("checked_at") or "")


def evidence_summary(store, cluster_id):
    """Counts and types of the evidence recorded for a cluster."""
    records = evidence_for(store, cluster_id)
    summary = {
        "total": len(records),
        "positive": 0,
        "neutral": 0,
        "negative": 0,
        "types": {},
        "positive_types": [],
        "negative_types": [],
        "has_url": False,
    }
    for record in records:
        sentiment = record.get("sentiment") or "neutral"
        if sentiment in summary:
            summary[sentiment] += 1
        evidence_type = record.get("evidence_type") or "OTHER"
        summary["types"][evidence_type] = summary["types"].get(evidence_type, 0) + 1
        if sentiment == "positive" and evidence_type not in summary["positive_types"]:
            summary["positive_types"].append(evidence_type)
        if sentiment == "negative" and evidence_type not in summary["negative_types"]:
            summary["negative_types"].append(evidence_type)
        if record.get("url"):
            summary["has_url"] = True
    return summary


def record_verdict(store, cluster_id, new_verdict, reason="", date=None, path=None):
    """Record a verdict change (no-op when the verdict is unchanged)."""
    day = date or timeutil.today_str()
    current = (store.get("current_verdicts") or {}).get(cluster_id)
    if current == new_verdict:
        return {"changed": False, "previous": current, "new": new_verdict}

    entry = {
        "cluster_id": cluster_id,
        "previous_verdict": current,
        "new_verdict": new_verdict,
        "date": day,
        "reason": reason or "",
    }
    store.setdefault("verdict_history", []).append(entry)
    store.setdefault("current_verdicts", {})[cluster_id] = new_verdict
    store["updated_at"] = timeutil.now().isoformat(timespec="seconds")
    if path is not None:
        save_store(store, path)
    return {"changed": True, "previous": current, "new": new_verdict, "entry": entry}


def verdict_history_for(store, cluster_id):
    return [entry for entry in (store.get("verdict_history") or [])
            if entry.get("cluster_id") == cluster_id]


def current_verdict(store, cluster_id):
    return (store.get("current_verdicts") or {}).get(cluster_id)
