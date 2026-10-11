"""Peerlist Launchpad adapter (Phase 6, Step 12).

peerlist.io/launchpad is reachable and ships a ``__NEXT_DATA__`` payload whose
embedded JSON can be walked for launched products.
"""

from analyzers import signals as S

from . import _http

SOURCE = "peerlist"
TIER = 2
SIGNAL_TYPES = (S.PRODUCT_SIGNAL, S.TREND_SIGNAL)

URL = "https://peerlist.io/launchpad"

LAST_ERROR = ""


def fetch(limit=15, timeout=None):
    """Return product signals from the Peerlist launch feed."""
    global LAST_ERROR
    LAST_ERROR = ""
    html, error = _http.get_text(URL, timeout=timeout or _http.DEFAULT_TIMEOUT, retries=1)
    if error:
        LAST_ERROR = error
        return []

    payload = _http.extract_next_data(html)
    if not payload:
        LAST_ERROR = "no __NEXT_DATA__ payload found"
        return []
    items = _http.find_named_objects(payload, max_items=limit,
                                     same_site_host="peerlist.io")
    if not items:
        LAST_ERROR = "no product objects found in __NEXT_DATA__"
        return []

    collected = []
    for item in items[:limit]:
        name = item.get("name") or item.get("title") or ""
        description = item.get("description") or item.get("tagline") or ""
        collected.append(S.make_signal(
            SOURCE, S.PRODUCT_SIGNAL,
            title=name, description=description,
            source_url=item.get("url") or item.get("website") or item.get("link") or URL,
            product_name=name, category="launch-directory",
            evidence_strength="MEDIUM",
            raw_metadata={"directory": "peerlist"},
        ))
    return collected
