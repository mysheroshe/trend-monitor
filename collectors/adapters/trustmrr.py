"""TrustMRR revenue adapter (Phase 6, Steps 4, 7).

trustmrr.com is reachable and embeds ``application/ld+json``. Revenue is
captured as REVENUE/PAYMENT evidence with an explicit confidence label -
self-reported figures are never marked VERIFIED, and revenue never sets a
verdict by itself.
"""

from analyzers import signals as S

from . import _http

SOURCE = "trustmrr"
TIER = 1
SIGNAL_TYPES = (S.REVENUE_SIGNAL, S.PAYMENT_SIGNAL)

URL = "https://trustmrr.com/"

LAST_ERROR = ""


def fetch(limit=15, timeout=None):
    """Return revenue/payment signals from public MRR listings."""
    global LAST_ERROR
    LAST_ERROR = ""
    html, error = _http.get_text(URL, timeout=timeout or _http.DEFAULT_TIMEOUT, retries=1)
    if error:
        LAST_ERROR = error
        return []

    items = []
    for payload in _http.extract_json_ld(html):
        items.extend(_http.find_named_objects(payload, max_items=limit,
                                              same_site_host="trustmrr.com"))
    if not items:
        LAST_ERROR = "no revenue listings found in embedded JSON-LD"
        return []

    collected = []
    for item in items[:limit]:
        name = item.get("name") or item.get("title") or ""
        description = item.get("description") or ""
        money = S.parse_money(f"{description} {name}")
        confidence = S.revenue_confidence(SOURCE, self_reported=True)
        collected.append(S.make_signal(
            SOURCE, S.REVENUE_SIGNAL if money else S.PAYMENT_SIGNAL,
            title=name, description=description,
            source_url=item.get("url") or item.get("website") or "",
            product_name=name, category="mrr-directory",
            pricing_or_revenue=description[:120] if money is None else f"${money:,.0f}/mo",
            evidence_strength="MEDIUM",
            revenue_confidence=confidence,
            raw_metadata={"directory": "trustmrr", "amount": money},
        ))
    return collected
