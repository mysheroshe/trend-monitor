"""Optional deep-research interface (Phase 4, Step 9). OFF by default.

Design goals:
  * the deterministic pipeline must never depend on this module;
  * no API key is required for normal runs;
  * nothing runs unless it is explicitly enabled AND a provider is registered;
  * every provider result is written to the validation evidence store, so the
    report can cite it instead of inventing claims.

How a future implementation plugs in
------------------------------------
1. Write a provider function ``fn(cluster) -> list[dict]`` where each dict has
   the keys ``summary`` (required), and optional ``evidence_type``,
   ``sentiment``, ``source``, ``url``, ``note``.
2. Register it: ``deep_research.register_provider("web", fn)``.
3. Enable it for a run: ``TREND_MONITOR_DEEP_RESEARCH=1`` (or pass
   ``env={"TREND_MONITOR_DEEP_RESEARCH": "1"}``).

Candidate providers (not implemented here): public web search, Reddit/HN
search, competitor page fetches, product-launch feeds. Any of those needs an
explicit opt-in and must degrade gracefully when unavailable.
"""

import os

from storage import validation_store

ENV_FLAG = "TREND_MONITOR_DEEP_RESEARCH"

_PROVIDERS = {}

DISABLED_REASON = (
    "deep research is off by default; set TREND_MONITOR_DEEP_RESEARCH=1 and "
    "register a provider to enable it"
)


def deep_research_enabled(env=None):
    """True only when the opt-in flag is explicitly set."""
    source = env if env is not None else os.environ
    value = str(source.get(ENV_FLAG, "")).strip().lower()
    return value in ("1", "true", "yes", "on")


def register_provider(name, fn):
    """Register a provider; ``fn(cluster) -> list[dict]``."""
    _PROVIDERS[name] = fn
    return fn


def unregister_provider(name):
    _PROVIDERS.pop(name, None)


def available_providers():
    return sorted(_PROVIDERS)


def _to_evidence(cluster_id, item):
    """Normalize a provider result; drop anything without a summary."""
    if not isinstance(item, dict):
        return None
    summary = str(item.get("summary") or "").strip()
    if not summary:
        return None
    return {
        "cluster_id": cluster_id,
        "evidence_type": validation_store.normalize_evidence_type(item.get("evidence_type")),
        "sentiment": validation_store.normalize_sentiment(item.get("sentiment")),
        "source": str(item.get("source") or "deep_research"),
        "url": str(item.get("url") or ""),
        "note": str(item.get("note") or ""),
        "summary": summary,
    }


def research_top_candidates(clusters, limit=5, provider=None, env=None, store=None, path=None):
    """Collect (and optionally persist) evidence for the top clusters.

    Returns a list of evidence dicts. Returns ``[]`` - without any network
    access - unless deep research is enabled and a provider is registered.
    """
    if not deep_research_enabled(env):
        return []
    name = provider or (available_providers()[0] if available_providers() else None)
    if not name or name not in _PROVIDERS:
        return []

    collected = []
    for cluster in clusters[:limit]:
        try:
            items = _PROVIDERS[name](cluster) or []
        except Exception:  # a provider must never break the pipeline
            continue
        for item in items:
            record = _to_evidence(cluster["cluster_id"], item)
            if not record:
                continue
            collected.append(record)
            if store is not None:
                validation_store.add_evidence(
                    store, record["cluster_id"], record["evidence_type"],
                    record["sentiment"], record["summary"],
                    source=record["source"], url=record["url"], note=record["note"],
                    path=path,
                )
    return collected
