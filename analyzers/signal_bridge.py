"""Bridge eligible PRODUCT_SIGNALs into the product pipeline (Phase 6.2).

High-quality product signals from the Phase 6/6.1 evidence layer are converted
into ordinary product records so they can flow through the *same*
``rank_products`` -> cluster -> keyword pipeline. Everything else (demand, pain,
revenue-only, payment-only, exit, feature-gap, corroboration opinions) stays
evidence-only.

The bridge never invents fields: missing description/category stay missing.
"""

from analyzers import signals as S
from analyzers.source_quality import (
    DQ_LOW,
    GH_LOW,
    discovery_quality,
    github_product_likeness,
    novelty_signal,
)

# Eligible sources with their discovery-source confidence (0..1, same scale as
# the existing SOURCE_CONFIDENCE; a small +/-5 ranking adjustment, never enough
# to overpower the Solo Builder Score).
BRIDGE_SOURCES = {
    "betalist": 0.8,       # fresh launches, medium-high discovery confidence
    "devhunt": 0.7,        # medium-high for developer-tool opportunities
    "github_search": 0.6,  # medium; must respect github_product_likeness
    "trustmrr": 0.6,       # medium; only when the record has product context
}

ORIGIN_TYPE = "signal_bridge"

# Sources whose only useful payload is revenue/payment evidence: bridging them
# requires enough product context to classify a domain/function.
REVENUE_ONLY_SOURCES = {"trustmrr"}

_CHROME_MARKERS = ("for sale", "view all", "recently listed", "sign in", "browse",
                   "submit", "navigation", "menu")


def bridge_eligible(signal):
    """Return (eligible, reason) for one signal."""
    source = signal.get("source") or ""
    if source not in BRIDGE_SOURCES:
        return False, f"source '{source}' is evidence-only"

    signal_type = signal.get("signal_type")
    if signal_type != S.PRODUCT_SIGNAL:
        if not (source in REVENUE_ONLY_SOURCES and signal_type in (S.REVENUE_SIGNAL,
                                                                  S.PAYMENT_SIGNAL)):
            return False, f"{signal_type} is evidence-only"

    name = (signal.get("product_name") or signal.get("title") or "").strip()
    if len(name) < 2:
        return False, "no product name"
    if any(marker in name.lower() for marker in _CHROME_MARKERS):
        return False, "navigation/chrome text, not a product"

    description = (signal.get("description") or "").strip()
    url = signal.get("source_url") or ""
    if not url and not description:
        return False, "no URL and no description"

    if source in REVENUE_ONLY_SOURCES and len(description) < 20:
        return False, "revenue-only record without product context"

    if source == "github_search":
        likeness, why = github_product_likeness({"name": name, "description": description})
        if likeness == GH_LOW:
            return False, f"github product likeness LOW: {why}"

    product = {"name": name, "description": description, "_source": source}
    quality, why = discovery_quality(product, source)
    if quality == DQ_LOW:
        return False, f"discovery quality LOW: {why}"

    return True, ""


def signal_to_product(signal):
    """Convert an eligible signal into a product record (or ``None``)."""
    eligible, _reason = bridge_eligible(signal)
    if not eligible:
        return None

    source = signal["source"]
    name = (signal.get("product_name") or signal.get("title") or "").strip()
    description = (signal.get("description") or "").strip()
    url = signal.get("source_url") or ""

    product = {
        "name": name,
        "description": description,
        "_source": source,
        "link": url,
        "url": url,
        "source_url": url,
        "origin_type": ORIGIN_TYPE,
        "category": signal.get("category") or "",
        "launch_date": signal.get("detected_at") or "",
        "pricing": signal.get("pricing_or_revenue") or "",
        "engagement": signal.get("engagement") or signal.get("engagement_metric"),
        "underlying_source_id": signal.get("underlying_source_id"),
        "source_list": [source],
        "source_count": 1,
        "raw_metadata": dict(signal.get("raw_metadata") or {}),
    }
    product["novelty_signal"] = novelty_signal(product, source)[0]
    product["discovery_quality"] = discovery_quality(product, source)[0]
    return product


def bridged_products(signal_list):
    """All eligible signals converted to product records (deduped by identity)."""
    products = []
    seen = set()
    for signal in signal_list or []:
        product = signal_to_product(signal)
        if not product:
            continue
        key = (product["_source"], (product.get("name") or "").lower())
        if key in seen:
            continue
        seen.add(key)
        products.append(product)
    return products


def bridge_summary(signal_list):
    """Counts per source: signals seen vs products bridged vs skipped."""
    summary = {}
    for signal in signal_list or []:
        source = signal.get("source") or "?"
        row = summary.setdefault(source, {"signals": 0, "bridged": 0, "skipped": 0})
        row["signals"] += 1
        if signal_to_product(signal):
            row["bridged"] += 1
        else:
            row["skipped"] += 1
    return summary
