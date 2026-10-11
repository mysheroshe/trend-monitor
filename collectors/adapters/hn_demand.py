"""Hacker News demand adapter (Phase 6, Step 9).

Uses the public Algolia HN search API (no key; verified HTTP 200) to find
Ask-HN style demand/pain posts. These never enter the product ranking - they
become PAIN / DEMAND / FEATURE_GAP evidence for opportunities.
"""

from urllib.parse import quote

from analyzers import signals as S

from . import _http

SOURCE = "hn_demand"
TIER = 1
SIGNAL_TYPES = (S.PAIN_SIGNAL, S.DEMAND_SIGNAL, S.FEATURE_GAP_SIGNAL)

QUERIES = ['"looking for a tool"', '"is there a tool"', '"wish there was"',
           '"alternative to"', '"too expensive"']

LAST_ERROR = ""


def fetch(limit=15, timeout=None):
    """Return demand/pain signals from Ask HN discussions."""
    global LAST_ERROR
    LAST_ERROR = ""
    collected = []
    errors = []
    per_query = max(2, limit // max(len(QUERIES), 1) + 1)

    for query in QUERIES:
        if len(collected) >= limit:
            break
        url = ("https://hn.algolia.com/api/v1/search?query="
               + quote(query)
               + f"&tags=ask_hn&hitsPerPage={per_query}")
        data, error = _http.get_json(url, timeout=timeout or _http.DEFAULT_TIMEOUT, retries=1)
        if error:
            errors.append(f"{query}: {error}")
            continue
        for hit in (data or {}).get("hits", []):
            if len(collected) >= limit:
                break
            title = hit.get("title") or ""
            text = (hit.get("story_text") or "")[:400]
            types, matched = S.detect_pain_patterns(f"{title} {text}")
            signal_type = types[0] if types else S.DEMAND_SIGNAL
            collected.append(S.make_signal(
                SOURCE, signal_type,
                title=title,
                description=text,
                source_url=f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                pain_point=text[:200],
                engagement_metric=hit.get("points"),
                evidence_strength="MEDIUM",
                raw_metadata={"matched_phrases": matched, "num_comments": hit.get("num_comments"),
                              "query": query},
                engagement=hit.get("points"),
            ))
    if errors:
        LAST_ERROR = "; ".join(errors[:3])
    return collected
