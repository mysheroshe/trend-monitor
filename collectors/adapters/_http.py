"""Shared HTTP helpers for source adapters (Phase 6, Steps 25-26).

Timeout, capped retries, a polite user-agent, and small per-source budgets.
No login walls, CAPTCHAs, paywalls or private APIs are ever touched.
"""

import json
import time

import requests

DEFAULT_UA = ("trend-monitor/1.1 (personal opportunity research; "
              "single daily request per source)")
DEFAULT_TIMEOUT = 12
RETRY_CAP = 2
POLITE_DELAY_SECONDS = 0.5


def get_text(url, timeout=DEFAULT_TIMEOUT, retries=RETRY_CAP, headers=None):
    """GET a public page with capped retries. Returns (text, error)."""
    request_headers = {"User-Agent": DEFAULT_UA, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"}
    if headers:
        request_headers.update(headers)
    last_error = ""
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, headers=request_headers, timeout=timeout)
            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}"
            else:
                return response.text, ""
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        if attempt < retries:
            time.sleep(POLITE_DELAY_SECONDS)
    return "", last_error


def get_json(url, timeout=DEFAULT_TIMEOUT, retries=RETRY_CAP, headers=None):
    """GET a public JSON endpoint. Returns (data, error)."""
    text, error = get_text(url, timeout=timeout, retries=retries, headers=headers)
    if error:
        return None, error
    try:
        return json.loads(text), ""
    except ValueError as exc:
        return None, f"invalid JSON: {exc}"


def extract_json_ld(html):
    """Collect ``application/ld+json`` payloads embedded in a page."""
    import re

    payloads = []
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html or "", re.DOTALL | re.IGNORECASE,
    ):
        try:
            payloads.append(json.loads(match.group(1).strip()))
        except ValueError:
            continue
    return payloads


def extract_next_data(html):
    """Return the ``__NEXT_DATA__`` payload of a Next.js page, or None."""
    import re

    match = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html or "", re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except ValueError:
        return None


_SITE_METADATA_TYPES = {
    "Organization", "Person", "WebSite", "WebPage", "BreadcrumbList",
    "Brand", "ImageObject", "LocalBusiness", "SearchAction", "SiteNavigation",
}


def find_named_objects(node, min_name=3, max_items=40, same_site_host="", _depth=0):
    """Walk embedded JSON and collect dicts that look like listable products.

    A product-looking object has a ``name``/``title`` plus at least one of
    ``description``/``tagline``/``url``/``website``. Site-level metadata
    (Organization/Person/WebSite/...) is skipped so a page's own JSON-LD cannot
    masquerade as a launch item, and links back to the same host (the site's own
    navigation pages) are ignored too.
    """
    found = []
    if _depth > 8 or len(found) >= max_items:
        return found
    if isinstance(node, dict):
        obj_type = node.get("@type")
        if isinstance(obj_type, list):
            obj_type = obj_type[0] if obj_type else None
        if obj_type in _SITE_METADATA_TYPES:
            return found
        name = node.get("name") or node.get("title")
        detail = (node.get("description") or node.get("tagline")
                  or node.get("url") or node.get("website") or node.get("link"))
        url = node.get("url") or node.get("website") or node.get("link") or ""
        same_host = bool(same_site_host) and same_site_host in str(url)
        if isinstance(name, str) and len(name.strip()) >= min_name and detail and not same_host:
            found.append(node)
        for value in node.values():
            found.extend(find_named_objects(value, min_name, max_items - len(found),
                                            same_site_host, _depth + 1))
    elif isinstance(node, list):
        for value in node:
            found.extend(find_named_objects(value, min_name, max_items - len(found),
                                            same_site_host, _depth + 1))
    return found[:max_items]
