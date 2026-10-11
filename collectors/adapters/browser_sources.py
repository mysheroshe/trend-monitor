"""Client-rendered source adapters (Phase 6.1, Steps 5-12).

Each entry in ``SOURCES`` declares a source's canonical URL, the stable href
pattern of its listing items, the signal type it contributes and its render
mode. Adapters share one browser session and honour a per-source limit.

Extraction order (Step 14): embedded structured state -> JSON-LD listing
entities -> stable href-pattern anchors. Site chrome/navigation is never
treated as a listing.
"""

import time

from analyzers import signals as S
from analyzers.source_quality import GH_LOW, github_product_likeness

from . import _http, browser_base

SOURCES = {
    "trustmrr": {
        "url": "https://trustmrr.com/",
        "pattern": r"^/startup/",
        "signal_type": S.REVENUE_SIGNAL,
        "tier": 1,
        "limit": 15,
        "kind": "revenue",
    },
    "devhunt": {
        "url": "https://devhunt.org/",
        "pattern": r"^/tool/",
        "signal_type": S.PRODUCT_SIGNAL,
        "tier": 1,
        "limit": 15,
        "kind": "product",
    },
    "betalist": {
        "url": "https://betalist.com/",
        "pattern": r"^/startups/",
        "signal_type": S.PRODUCT_SIGNAL,
        "tier": 2,
        "limit": 15,
        "kind": "product",
    },
    "build_or_skip": {
        "url": "https://buildorskip.com/",
        "pattern": r"^/launch/",
        "signal_type": S.CORROBORATION_SIGNAL,
        "tier": 1,
        "limit": 15,
        "kind": "corroboration",
        # Phase 6.2: 13s budget - it produced no reliable items at 51s
        "timeout_seconds": 13,
    },
}

LAST_ERROR = ""
RENDER_MODE = "PLAYWRIGHT"


_CHROME_MARKERS = ("for sale", "revenue", "view all", "recently listed", "mrr",
                   "sign in", "sign up", "browse", "submit")


def _slug_name(href):
    slug = (href or "").rstrip("/").split("/")[-1].split("?")[0]
    return slug.replace("-", " ").replace("_", " ").strip()


def _clean_name(text, block, href):
    """Prefer a real product name; fall back to the URL slug (never card chrome)."""
    import re as _re

    candidate = _re.sub(r"^\s*\d+\s+", "", (text or "").strip())   # drop vote counts
    lowered = candidate.lower()
    looks_like_chrome = (
        len(candidate) > 60
        or any(marker in lowered for marker in _CHROME_MARKERS)
        or lowered in ("view", "more", "read more", "open", "")
    )
    if not looks_like_chrome and len(candidate) >= 2:
        return candidate
    return _slug_name(href)


def _clean_description(name, block):
    """Trim the card text down to a description without the surrounding chrome."""
    text = (block or "").strip()
    if name and name.lower() in text.lower():
        index = text.lower().index(name.lower())
        text = text[index + len(name):]
    for marker in _CHROME_MARKERS:
        lowered = text.lower()
        if marker in lowered:
            text = text[:lowered.index(marker)]
    text = text.strip(" -–|·,")
    if len(text) < 8:
        return ""
    return text[:240]


def _signal_for(source, config, item):
    href = item.get("href") or ""
    block = item.get("block") or ""
    name = _clean_name(item.get("text"), block, href)
    if not name:
        return None
    url = href if href.startswith("http") else config["url"].rstrip("/") + href
    description = _clean_description(name, block)

    kind = config.get("kind", "product")
    if kind == "product":
        likeness, why = github_product_likeness({"name": name, "description": description})
        if likeness == GH_LOW:
            return None
        return S.make_signal(
            source, S.PRODUCT_SIGNAL, title=name, description=description,
            source_url=url, product_name=name, category="launch-directory",
            evidence_strength="MEDIUM",
            raw_metadata={"render_mode": RENDER_MODE, "likeness": likeness,
                          "likeness_reason": why, "listing_url": config["url"]},
        )

    if kind == "revenue":
        amount = browser_base.money_from(block)
        verified = "verified" in block.lower()
        confidence = (S.REVENUE_VERIFIED if verified
                      else S.REVENUE_PUBLIC_SELF_REPORTED)
        return S.make_signal(
            source, S.REVENUE_SIGNAL if amount else S.PAYMENT_SIGNAL,
            title=name, description=description, source_url=url, product_name=name,
            category="mrr-directory",
            pricing_or_revenue=f"${amount:,.0f}" if amount else None,
            revenue_confidence=confidence,
            evidence_strength="MEDIUM" if amount else "LOW",
            raw_metadata={"render_mode": RENDER_MODE, "verified_label": verified,
                          "listing_url": config["url"]},
        )

    # corroboration (Build or Skip): their verdict is metadata, never our verdict
    fate = S.EXIT_UNKNOWN
    lowered = block.lower()
    if "acquired" in lowered:
        fate = S.EXIT_HEALTHY
    elif "gone" in lowered or "dead" in lowered:
        fate = S.EXIT_DISTRESSED
    return S.make_signal(
        source, S.CORROBORATION_SIGNAL,
        title=name, description=description, source_url=url, product_name=name,
        category="launch-history",
        evidence_strength="MEDIUM",
        exit_signal_type=fate,
        raw_metadata={"render_mode": RENDER_MODE, "external_opinion": block[:160],
                      "external_source": source, "listing_url": config["url"]},
    )


def fetch(source, session=None, limit=None, timeout=None, use_cache=True):
    """Return signals for one client-rendered source (never raises)."""
    global LAST_ERROR
    LAST_ERROR = ""
    config = SOURCES.get(source)
    if not config:
        LAST_ERROR = f"unknown browser source: {source}"
        return [], "error", {}

    source_limit = min(limit or config["limit"], config["limit"])
    owns_session = session is None
    session = session or browser_base.BrowserSession()
    started = session.available() and (session._browser is not None or session.start()[0])
    runtime = 0.0
    items = []

    if started:
        t0 = time.time()
        timeout_ms = int(config.get("timeout_seconds", 0) * 1000) or None
        page, _html, text, error = session.render(config["url"], timeout_ms=timeout_ms)
        runtime = time.time() - t0
        if error:
            LAST_ERROR = error
        else:
            raw = browser_base.extract_listings(page, config["pattern"])
            seen = set()
            for entry in raw:
                if len(items) >= source_limit:
                    break
                if entry.get("href") in seen:
                    continue
                seen.add(entry.get("href"))
                signal = _signal_for(source, config, entry)
                if signal:
                    items.append(signal)
            if not items:
                # rendered, but nothing that looks like a listing
                LAST_ERROR = ("HTML_RENDERED_BUT_NO_LISTING_DATA: no items matched "
                              f"{config['pattern']}")
        session.close_page(page)
    elif not session.available():
        LAST_ERROR = "playwright not installed"
    else:
        LAST_ERROR = LAST_ERROR or "browser unavailable"

    if owns_session:
        session.stop()

    stale = False
    cached_at = ""
    if not items and use_cache:
        cached, cached_at = browser_base.load_cache(source)
        if cached:
            items, stale = cached, True
            LAST_ERROR = LAST_ERROR or "used cached data"

    status = _status_for(items, error=LAST_ERROR, stale=stale)
    return items, status, {"runtime_seconds": round(runtime, 1), "stale": stale,
                           "cached_at": cached_at, "render_mode": RENDER_MODE,
                           "low_efficiency": bool(
                               config.get("timeout_seconds")
                               and runtime >= config["timeout_seconds"] - 1)}


def _status_for(items, error="", stale=False):
    if stale:
        return "STALE_CACHE"
    if items:
        return "OK"
    if not error:
        return "EMPTY"
    if "BLOCKED" in error:
        return "BLOCKED"
    if "NO_LISTING_DATA" in error:
        return "HTML_RENDERED_BUT_NO_LISTING_DATA"
    if "playwright not installed" in error:
        return "DISABLED"
    if "Timeout" in error or "timed out" in error:
        return "TIMEOUT"
    return "PARSER_DRIFT"
