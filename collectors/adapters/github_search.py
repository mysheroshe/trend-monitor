"""GitHub topic/search discovery adapter (Phase 6, Step 10).

Uses the public GitHub search API (no token required, verify: api.github.com
answered HTTP 200 from this environment). Repositories are mapped through the
existing ``github_product_likeness`` gate so developer libraries stay out.
"""

from analyzers import signals as S
from analyzers.source_quality import GH_LOW, github_product_likeness

from . import _http

SOURCE = "github_search"
TIER = 1
SIGNAL_TYPES = (S.PRODUCT_SIGNAL, S.TREND_SIGNAL)

TOPICS = ["micro-saas", "indie-hackers", "browser-extension", "chrome-extension",
          "productivity", "creator-tools", "automation", "data-tool"]

LAST_ERROR = ""


def fetch(limit=15, timeout=None):
    """Return product/trend signals from GitHub topic search."""
    global LAST_ERROR
    LAST_ERROR = ""
    collected = []
    errors = []
    per_topic = max(2, limit // max(len(TOPICS), 1) + 1)

    for topic in TOPICS:
        if len(collected) >= limit:
            break
        url = (f"https://api.github.com/search/repositories?q=topic:{topic}"
               f"&sort=updated&order=desc&per_page={per_topic}")
        data, error = _http.get_json(url, timeout=timeout or _http.DEFAULT_TIMEOUT,
                                     retries=1,
                                     headers={"Accept": "application/vnd.github+json"})
        if error:
            errors.append(f"{topic}: {error}")
            continue
        for item in (data or {}).get("items", []):
            if len(collected) >= limit:
                break
            product = {"name": item.get("full_name", ""),
                       "description": item.get("description") or "",
                       "_source": "github"}
            likeness, why = github_product_likeness(product)
            if likeness == GH_LOW:
                continue
            collected.append(S.make_signal(
                SOURCE, S.PRODUCT_SIGNAL,
                title=item.get("full_name", ""),
                description=item.get("description") or "",
                source_url=item.get("html_url") or "",
                product_name=item.get("name", ""),
                category="github",
                evidence_strength="MEDIUM" if likeness == "MEDIUM" else "HIGH",
                engagement_metric=item.get("stargazers_count"),
                growth_metric=item.get("pushed_at"),
                raw_metadata={"topic": topic, "likeness": likeness, "likeness_reason": why,
                              "stars": item.get("stargazers_count"),
                              "forks": item.get("forks_count")},
            ))
    if errors:
        LAST_ERROR = "; ".join(errors[:3])
    return collected
