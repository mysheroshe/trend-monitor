"""Headless-browser adapter tests (Phase 6.1, Steps 4-22)."""

import json

import pytest

from analyzers import signals as S
from collectors.adapters import browser_base, browser_sources


class _FakePage:
    def __init__(self, listings):
        self._listings = listings
        self.closed = False

    def evaluate(self, script, arg=None):
        return self._listings

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, listings=None, error="", available=True):
        self._browser = object() if available else None
        self._listings = listings or []
        self._error = error
        self.closed_pages = []
        self.stopped = False

    def available(self):
        return self._browser is not None

    def start(self):
        return True, ""

    def render(self, url, wait_ms=0, wait_selector=None, retries=0, timeout_ms=None):
        if self._error:
            return None, "", "", self._error
        return _FakePage(self._listings), "<html></html>", "body text", ""

    def close_page(self, page):
        self.closed_pages.append(page)
        if page is not None:
            page.close()

    def stop(self):
        self.stopped = True


def _listing(href, text, block):
    return {"href": href, "text": text, "block": block}


# --- browser base ----------------------------------------------------------

def test_browser_session_is_safe_when_playwright_is_missing(monkeypatch):
    monkeypatch.setattr(browser_base, "PLAYWRIGHT_AVAILABLE", False)
    session = browser_base.BrowserSession()

    assert session.available() is False
    ok, error = session.start()
    assert ok is False
    assert "playwright not installed" in error
    session.stop()                       # must not raise


def test_render_without_a_browser_returns_an_error_not_a_crash():
    session = browser_base.BrowserSession()
    page, html, text, error = session.render("https://example.com/")
    assert page is None and error == "browser not started"


def test_page_is_closed_even_on_error():
    session = _FakeSession(error="TimeoutError: Page.goto")
    page, html, text, error = session.render("https://example.com/")
    assert error
    session.close_page(page)             # None-safe


def test_extract_listings_handles_a_broken_page():
    class _Boom:
        def evaluate(self, *args, **kwargs):
            raise RuntimeError("detached frame")

    assert browser_base.extract_listings(_Boom(), r"^/x/") == []


# --- cache / staleness -----------------------------------------------------

def test_cache_round_trip_and_staleness(tmp_path):
    path = tmp_path / "trustmrr.json"
    browser_base.save_cache("trustmrr", [{"name": "x"}], path=path)

    items, cached_at = browser_base.load_cache("trustmrr", path=path)
    assert items == [{"name": "x"}]
    assert cached_at

    stale_items, _ = browser_base.load_cache("trustmrr", max_age_days=-1, path=path)
    assert stale_items == []             # older than the allowed window


def test_missing_cache_is_empty(tmp_path):
    assert browser_base.load_cache("nope", path=tmp_path / "missing.json") == ([], "")


def test_money_parsing():
    assert browser_base.money_from("REVENUE $3.7k / mo") == 3700.0
    assert browser_base.money_from("no money here") is None


# --- listing extraction quality -------------------------------------------

def test_js_rendered_fixture_yields_real_listings():
    session = _FakeSession([
        _listing("/tool/astracode", "AstraCode", "AstraCode The AI-native code editor"),
        _listing("/tool/oneprovider", "OneProvider", "OneProvider Leading AI models in one API"),
        _listing("/tool/selvedge", "Selvedge", "Selvedge memory for coding agents"),
    ])
    items, status, meta = browser_sources.fetch("devhunt", session=session)

    assert status == "OK"
    assert [item["title"] for item in items] == ["AstraCode", "OneProvider", "Selvedge"]
    assert all(item["signal_type"] == S.PRODUCT_SIGNAL for item in items)
    assert meta["render_mode"] == "PLAYWRIGHT"
    assert meta["stale"] is False


def test_card_chrome_is_not_used_as_a_product_name():
    session = _FakeSession([
        _listing("/startup/fanpilott",
                 "FOR SALE FanPilott SaaS REVENUE $3 Recently listed View all", "..."),
    ])
    items, status, _ = browser_sources.fetch("trustmrr", session=session)
    assert status == "OK"
    assert items[0]["title"] == "fanpilott"
    assert "FOR SALE" not in items[0]["title"]


def test_navigation_only_page_is_reported_not_faked():
    session = _FakeSession([])            # page rendered, no listing anchors
    items, status, _ = browser_sources.fetch("trustmrr", session=session, use_cache=False)
    assert items == []
    assert status == "HTML_RENDERED_BUT_NO_LISTING_DATA"


def test_blocked_page_is_reported_and_not_parsed(tmp_path):
    session = _FakeSession(error="BLOCKED: anti-bot challenge page")
    items, status, _ = browser_sources.fetch("devhunt", session=session, use_cache=False)
    assert items == []
    assert status == "BLOCKED"


def test_empty_page_produces_empty_not_fake_records():
    session = _FakeSession([])
    items, status, _ = browser_sources.fetch("betalist", session=session, use_cache=False)
    assert items == []
    assert status == "HTML_RENDERED_BUT_NO_LISTING_DATA"


def test_source_limit_is_enforced():
    session = _FakeSession([
        _listing(f"/tool/tool-{i}", f"Tool {i}", f"Tool {i} description") for i in range(40)
    ])
    items, status, _ = browser_sources.fetch("devhunt", session=session, limit=5)
    assert len(items) == 5
    assert status == "OK"


# --- revenue / exit / corroboration semantics ------------------------------

def test_self_reported_revenue_is_never_verified():
    session = _FakeSession([_listing("/startup/homy", "Homy", "Homy Productivity $3.7k MRR")])
    items, _, _ = browser_sources.fetch("trustmrr", session=session)
    assert items[0]["revenue_confidence"] == S.REVENUE_PUBLIC_SELF_REPORTED
    assert items[0]["signal_type"] == S.REVENUE_SIGNAL


def test_verified_label_is_preserved_only_when_stated():
    session = _FakeSession([
        _listing("/startup/verified-one", "Verified One", "Verified One verified revenue $9k MRR"),
    ])
    items, _, _ = browser_sources.fetch("trustmrr", session=session)
    assert items[0]["revenue_confidence"] == S.REVENUE_VERIFIED


def test_build_or_skip_opinion_never_sets_our_verdict():
    session = _FakeSession([
        _listing("/launch/died-thing", "Died Thing", "Died Thing verdict: skip, gone"),
    ])
    items, status, _ = browser_sources.fetch("build_or_skip", session=session)
    assert status == "OK"
    signal = items[0]
    assert signal["signal_type"] == S.CORROBORATION_SIGNAL
    assert "verdict" not in signal
    assert signal["raw_metadata"]["external_opinion"]


def test_for_sale_listing_does_not_imply_a_healthy_exit():
    session = _FakeSession([
        _listing("/launch/for-sale-thing", "For Sale Thing",
                 "For Sale Thing for sale, $10k asking price"),
    ])
    items, _, _ = browser_sources.fetch("build_or_skip", session=session)
    assert items[0]["exit_signal_type"] == S.EXIT_UNKNOWN     # price alone is not health


# --- health / pipeline safety ---------------------------------------------

def test_failed_browser_source_does_not_fail_the_pipeline(monkeypatch):
    from collectors import adapters

    monkeypatch.setattr(browser_base, "PLAYWRIGHT_AVAILABLE", False)
    signals, rows = adapters.fetch_browser_all(limit_per_source=2)

    assert signals == []
    assert rows
    assert all(row["status"] == "DISABLED" for row in rows)
    assert all("render_mode" in row and "runtime_seconds" in row for row in rows)


def test_source_health_rows_carry_runtime_and_render_mode():
    session = _FakeSession([_listing("/tool/x", "X Tool", "X Tool description here")])
    items, status, meta = browser_sources.fetch("devhunt", session=session)
    assert meta["runtime_seconds"] >= 0
    assert meta["render_mode"] == "PLAYWRIGHT"
    assert status == "OK"


def test_stale_cache_is_labelled_and_not_new_novelty(tmp_path, monkeypatch):
    cache_file = tmp_path / "devhunt.json"
    browser_base.save_cache("devhunt", [{
        "source": "devhunt", "signal_type": S.PRODUCT_SIGNAL, "title": "Cached Tool",
        "description": "from cache", "source_url": "https://devhunt.org/tool/cached",
        "product_name": "Cached Tool", "raw_metadata": {},
    }], path=cache_file)

    # today's render fails and the cache is used
    session = _FakeSession(error="TimeoutError: Page.goto")
    monkeypatch.setattr(browser_base, "cache_path", lambda source: cache_file)
    items, status, meta = browser_sources.fetch("devhunt", session=session, use_cache=True)

    assert status == "STALE_CACHE"
    assert meta["stale"] is True
    assert items and items[0]["title"] == "Cached Tool"


def test_source_name_helper_prefers_slug_over_chrome():
    assert browser_sources._clean_name("FOR SALE X SaaS REVENUE $3", "", "/startup/x-saas") == "x saas"
    assert browser_sources._clean_name("AstraCode", "", "/tool/astracode") == "AstraCode"
    assert browser_sources._clean_name("12 AstraCode", "", "/tool/astracode") == "AstraCode"
