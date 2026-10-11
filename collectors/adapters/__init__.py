"""Source-adapter registry for the multi-source engine (Phase 6).

Only adapters verified against the live public page/API are registered as
implemented. Every other requested source is *declared* here with the exact
probe result so Source Health reports reality instead of guessing.
"""

from analyzers.signals import (
    COMPETITION_SIGNAL, CORROBORATION_SIGNAL, DEMAND_SIGNAL, EXIT_SIGNAL,
    FEATURE_GAP_SIGNAL, PAIN_SIGNAL, PAYMENT_SIGNAL, PRODUCT_SIGNAL,
    REVENUE_SIGNAL, TREND_SIGNAL,
)

from . import browser_base, browser_sources, devhunt, github_search, hn_demand, peerlist, trustmrr

IMPLEMENTED = {
    "github_search": github_search,
    "hn_demand": hn_demand,
}

# Adapters that were written and probed but could not be shipped: their public
# pages are client-rendered, so the server HTML only contains the site's own
# navigation metadata. They stay in the tree, are excluded from IMPLEMENTED,
# and are declared below with the exact probe result.
PROBED_NOT_SHIPPED = {
    "devhunt": devhunt,
    "trustmrr": trustmrr,
    "peerlist": peerlist,
}

# Everything else the phase asked for, with the result of the live probe
# (2026-10-11, this environment). Status values:
#   unreachable | blocked | rate_limited | flaky | html_only | unknown_domain
DECLARED_SOURCES = [
    {"source": "reddit", "tier": 1, "status": "official_api",
     "detail": "integrated via the official Reddit API (collectors/adapters/reddit_api.py); "
               "HTML scraping is not used. Requires REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET; "
               "reports NOT_CONFIGURED until those exist. The unauthenticated JSON endpoints "
               "remain unreachable from this network (16s timeout)",
     "signal_types": [PAIN_SIGNAL, DEMAND_SIGNAL, FEATURE_GAP_SIGNAL]},
    {"source": "build_or_skip", "tier": 1, "status": "unreachable",
     "detail": "buildorskip.com TLS handshake timed out - confirm the exact URL",
     "signal_types": [CORROBORATION_SIGNAL]},
    {"source": "columbus", "tier": 1, "status": "unknown_domain",
     "detail": "columbus.so did not resolve - confirm the exact URL",
     "signal_types": [PRODUCT_SIGNAL, REVENUE_SIGNAL, TREND_SIGNAL]},
    {"source": "mrrscout", "tier": 1, "status": "html_only",
     "detail": "reachable (HTTP 200) but no embedded structured data; needs brittle HTML parsing",
     "signal_types": [REVENUE_SIGNAL, PAYMENT_SIGNAL]},
    {"source": "sideprojectors", "tier": 1, "status": "flaky",
     "detail": "HTTP 200 once, read timeout on the second probe",
     "signal_types": [EXIT_SIGNAL, REVENUE_SIGNAL, COMPETITION_SIGNAL]},
    {"source": "indiehackers", "tier": 2, "status": "html_only",
     "detail": "reachable but the listings are rendered client-side",
     "signal_types": [REVENUE_SIGNAL, CORROBORATION_SIGNAL]},
    {"source": "open_startups", "tier": 2, "status": "unknown_domain",
     "detail": "no canonical public domain confirmed",
     "signal_types": [REVENUE_SIGNAL]},
    {"source": "indie_hacker_directory", "tier": 2, "status": "unknown_domain",
     "detail": "no canonical public domain confirmed",
     "signal_types": [CORROBORATION_SIGNAL]},
    {"source": "betalist", "tier": 2, "status": "html_only",
     "detail": "reachable but the launch cards are client-rendered",
     "signal_types": [PRODUCT_SIGNAL, TREND_SIGNAL]},
    {"source": "microlaunch", "tier": 2, "status": "html_only",
     "detail": "reachable but no embedded structured data",
     "signal_types": [PRODUCT_SIGNAL, TREND_SIGNAL]},
    {"source": "uneed", "tier": 2, "status": "unreachable",
     "detail": "www.uneed.best TLS handshake timed out",
     "signal_types": [PRODUCT_SIGNAL, TREND_SIGNAL]},
    {"source": "chrome_web_store_reviews", "tier": 2, "status": "html_only",
     "detail": "reviews are client-rendered; only the extension page is scrapeable",
     "signal_types": [FEATURE_GAP_SIGNAL, PAIN_SIGNAL, COMPETITION_SIGNAL]},
    {"source": "app_store_reviews", "tier": 2, "status": "blocked",
     "detail": "no public unauthenticated review endpoint",
     "signal_types": [FEATURE_GAP_SIGNAL, PAIN_SIGNAL]},
    {"source": "g2", "tier": 3, "status": "blocked", "detail": "HTTP 403",
     "signal_types": [FEATURE_GAP_SIGNAL, COMPETITION_SIGNAL]},
    {"source": "capterra", "tier": 3, "status": "not_probed",
     "detail": "not probed in this run", "signal_types": [FEATURE_GAP_SIGNAL]},
    {"source": "upwork", "tier": 3, "status": "blocked",
     "detail": "HTTP 403 from this network", "signal_types": [PAYMENT_SIGNAL, DEMAND_SIGNAL]},
    {"source": "acquire", "tier": 3, "status": "html_only",
     "detail": "reachable but listings are client-rendered",
     "signal_types": [EXIT_SIGNAL, REVENUE_SIGNAL]},
    {"source": "x_twitter", "tier": 3, "status": "blocked",
     "detail": "x.com timed out; API requires auth", "signal_types": [PAIN_SIGNAL, TREND_SIGNAL]},
    {"source": "bigideasdb", "tier": 3, "status": "rate_limited",
     "detail": "HTTP 429 on the first request", "signal_types": [CORROBORATION_SIGNAL]},
    {"source": "startupideasdb", "tier": 3, "status": "unreachable",
     "detail": "read timeout", "signal_types": [PAIN_SIGNAL, CORROBORATION_SIGNAL]},
    {"source": "product_hunt_html", "tier": 3, "status": "blocked",
     "detail": "producthunt.com HTML returns 403; the existing RSS feed source is used instead",
     "signal_types": [PRODUCT_SIGNAL]},
    {"source": "devhunt", "tier": 1, "status": "html_only",
     "detail": "adapter implemented (collectors/adapters/devhunt.py) but devhunt.org serves only "
               "site-level JSON-LD - launch cards are client-rendered, so it yields 0 items",
     "signal_types": [PRODUCT_SIGNAL, TREND_SIGNAL]},
    {"source": "trustmrr", "tier": 1, "status": "html_only",
     "detail": "adapter implemented (collectors/adapters/trustmrr.py) but its JSON-LD is its own "
               "navigation pages, not individual MRR listings",
     "signal_types": [REVENUE_SIGNAL, PAYMENT_SIGNAL]},
    {"source": "peerlist", "tier": 2, "status": "html_only",
     "detail": "adapter implemented (collectors/adapters/peerlist.py); __NEXT_DATA__ present but "
               "no product objects in the server payload",
     "signal_types": [PRODUCT_SIGNAL, TREND_SIGNAL]},
]


def declared_status(source):
    for entry in DECLARED_SOURCES:
        if entry["source"] == source:
            return entry
    return None


def fetch_all(limit_per_source=15, enabled=None, timeout=None):
    """Run every implemented adapter. Returns (signals, health_rows).

    A failing or blocked adapter can never break the pipeline.
    """
    signals, rows = [], []
    for name, module in IMPLEMENTED.items():
        if enabled is not None and name not in enabled:
            continue
        try:
            items = module.fetch(limit=limit_per_source, timeout=timeout) or []
            error = getattr(module, "LAST_ERROR", "") or ""
        except Exception as exc:                     # noqa: BLE001 - never fail the pipeline
            items, error = [], f"adapter crashed: {type(exc).__name__}: {exc}"
        signals.extend(items)
        rows.append({
            "source": name,
            "tier": getattr(module, "TIER", 9),
            "status": "error" if error else ("empty" if not items else "ok"),
            "items_fetched": len(items),
            "items_accepted": len(items),
            "items_filtered": 0,
            "last_error": error,
            "signal_types": list(getattr(module, "SIGNAL_TYPES", ())),
            "notes": "",
        })
    return signals, rows


def fetch_browser_all(limit_per_source=10, sources=None, use_cache=True):
    """Run the client-rendered adapters on ONE shared browser session.

    A source that is blocked, times out or drifts is reported in its health row
    and never fails the run. Per-source runtime is included for cost control.
    """
    signals, rows = [], []
    session = browser_base.BrowserSession()
    started, start_error = (session.start() if session.available()
                            else (False, "playwright not installed"))
    names = sources if sources is not None else list(browser_sources.SOURCES)
    for name in names:
        if name not in browser_sources.SOURCES:
            continue
        config = browser_sources.SOURCES[name]
        if not started:
            rows.append({
                "source": name, "tier": config["tier"], "status": "DISABLED",
                "items_fetched": 0, "items_accepted": 0, "items_filtered": 0,
                "last_error": start_error, "signal_types": [config["signal_type"]],
                "runtime_seconds": 0.0, "render_mode": browser_sources.RENDER_MODE,
                "stale_cache_used": False, "notes": "",
            })
            continue
        try:
            items, status, meta = browser_sources.fetch(
                name, session=session, limit=limit_per_source, use_cache=use_cache)
        except Exception as exc:                 # noqa: BLE001 - never fail the run
            items, status, meta = [], "PARSER_DRIFT", {"runtime_seconds": 0.0}
            browser_sources.LAST_ERROR = f"adapter crashed: {type(exc).__name__}: {exc}"
        signals.extend(items)
        rows.append({
            "source": name, "tier": config["tier"], "status": status,
            "items_fetched": len(items), "items_accepted": len(items), "items_filtered": 0,
            "last_error": browser_sources.LAST_ERROR,
            "signal_types": [config["signal_type"]],
            "runtime_seconds": meta.get("runtime_seconds", 0.0),
            "render_mode": meta.get("render_mode", browser_sources.RENDER_MODE),
            "stale_cache_used": bool(meta.get("stale")),
            "cached_at": meta.get("cached_at", ""),
            "notes": "",
        })
    session.stop()
    return signals, rows
