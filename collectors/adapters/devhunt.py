"""DevHunt launch adapter (Phase 6, Step 12).

devhunt.org is reachable (HTTP 200) and embeds ``application/ld+json``
structured data, which is what this adapter reads. If the structure ever
changes the adapter reports the failure instead of inventing items.
"""

from analyzers import signals as S
from analyzers.source_quality import GH_LOW, github_product_likeness

from . import _http

SOURCE = "devhunt"
TIER = 1
SIGNAL_TYPES = (S.PRODUCT_SIGNAL, S.TREND_SIGNAL)

URL = "https://devhunt.org/"

LAST_ERROR = ""


def fetch(limit=15, timeout=None):
    """Return product signals from DevHunt's public launch listings."""
    global LAST_ERROR
    LAST_ERROR = ""
    html, error = _http.get_text(URL, timeout=timeout or _http.DEFAULT_TIMEOUT, retries=1)
    if error:
        LAST_ERROR = error
        return []

    payloads = _http.extract_json_ld(html)
    items = []
    for payload in payloads:
        items.extend(_http.find_named_objects(payload, max_items=limit,
                                              same_site_host="devhunt.org"))
    if not items:
        LAST_ERROR = "no product objects found in embedded JSON-LD"
        return []

    collected = []
    for item in items[:limit]:
        name = item.get("name") or item.get("title") or ""
        description = item.get("description") or item.get("tagline") or ""
        url = item.get("url") or item.get("website") or item.get("link") or ""
        likeness, _ = github_product_likeness({"name": name, "description": description})
        if likeness == GH_LOW:
            continue
        collected.append(S.make_signal(
            SOURCE, S.PRODUCT_SIGNAL,
            title=name, description=description, source_url=url,
            product_name=name, category="launch-directory",
            evidence_strength="MEDIUM",
            raw_metadata={"directory": "devhunt", "likeness": likeness},
        ))
    return collected
