"""Shared headless-browser adapter helper (Phase 6.1, Steps 4, 14-17, 21).

One Chromium instance is reused across sources, pages are closed cleanly on
error, and a missing Playwright dependency degrades to a reported status
instead of crashing the pipeline. The browser drives an *installed* Chrome or
Edge channel when available (no browser download needed).

Never bypasses login walls, CAPTCHAs or anti-bot challenges: if a page shows a
challenge it is reported as BLOCKED and the source is skipped.
"""

import json
import re
import time
from pathlib import Path

from config import timeutil

try:                                            # pragma: no cover - env dependent
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:                             # pragma: no cover
    sync_playwright = None
    PLAYWRIGHT_AVAILABLE = False

CHANNELS = ("msedge", "chrome", None)
DEFAULT_TIMEOUT_MS = 25000
DEFAULT_WAIT_MS = 2500
RETRY_CAP = 1
POLITE_DELAY_SECONDS = 0.4
CACHE_MAX_AGE_DAYS = 3

# Rendered-but-not-a-listing markers (and Cloudflare-style challenges).
_BLOCK_MARKERS = [
    "正在进行安全验证", "verify you are human", "checking your browser",
    "cf-challenge", "attention required", "enable javascript and cookies",
]


def cache_path(source):
    return Path(__file__).resolve().parents[2] / "data" / "cache" / f"{source}.json"


def save_cache(source, items, path=None):
    target = Path(path) if path else cache_path(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(
        {"source": source, "cached_at": timeutil.now().isoformat(timespec="seconds"),
         "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_cache(source, max_age_days=CACHE_MAX_AGE_DAYS, path=None, today=None):
    """Return (items, cached_at) when a recent successful result exists."""
    target = Path(path) if path else cache_path(source)
    if not target.exists():
        return [], ""
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], ""
    cached_at = payload.get("cached_at") or ""
    if not cached_at:
        return [], ""
    try:
        from datetime import datetime
        age = (datetime.fromisoformat(cached_at) - timeutil.now()).days
    except ValueError:
        return [], ""
    if abs(age) > max_age_days:
        return [], ""
    return payload.get("items") or [], cached_at


class BrowserSession:
    """Reusable headless browser with safe cleanup."""

    def __init__(self, timeout_ms=DEFAULT_TIMEOUT_MS):
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self.channel = ""

    def available(self):
        return PLAYWRIGHT_AVAILABLE

    def start(self):
        """Start Playwright and launch the first working browser channel."""
        if not PLAYWRIGHT_AVAILABLE:
            return False, "playwright not installed"
        self._playwright = sync_playwright().start()
        last_error = ""
        for channel in CHANNELS:
            try:
                options = {"headless": True, "args": ["--no-sandbox"]}
                if channel:
                    options["channel"] = channel
                self._browser = self._playwright.chromium.launch(**options)
                self.channel = channel or "chromium"
                return True, ""
            except Exception as exc:              # noqa: BLE001
                last_error = f"{channel or 'chromium'}: {exc}"
        self.stop()
        return False, f"no usable browser channel ({last_error})"

    def render(self, url, wait_ms=DEFAULT_WAIT_MS, wait_selector=None, retries=RETRY_CAP,
               timeout_ms=None):
        """Render a public page. Returns (page_or_None, html, text, error)."""
        if not self._browser:
            return None, "", "", "browser not started"
        page_timeout = timeout_ms or self.timeout_ms
        last_error = ""
        for attempt in range(retries + 1):
            page = None
            try:
                page = self._browser.new_page()
                page.goto(url, timeout=page_timeout, wait_until="domcontentloaded")
                if wait_selector:
                    page.wait_for_selector(wait_selector, timeout=page_timeout)
                page.wait_for_timeout(wait_ms)
                html = page.content()
                text = page.inner_text("body")
                if any(marker in text.lower() or marker in html.lower()
                       for marker in _BLOCK_MARKERS):
                    return page, html, text, "BLOCKED: anti-bot challenge page"
                return page, html, text, ""
            except Exception as exc:              # noqa: BLE001
                last_error = f"{type(exc).__name__}: {exc}"
                if page is not None:
                    try:
                        page.close()
                    except Exception:             # noqa: BLE001
                        pass
            if attempt < retries:
                time.sleep(POLITE_DELAY_SECONDS)
        return None, "", "", last_error

    def close_page(self, page):
        if page is None:
            return
        try:
            page.close()
        except Exception:                         # noqa: BLE001
            pass

    def stop(self):
        for closer in (getattr(self._browser, "close", None),
                       getattr(self._playwright, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:                     # noqa: BLE001
                pass
        self._browser = None
        self._playwright = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc_info):
        self.stop()
        return False


LISTING_SCRIPT = """
(args) => {
  const rx = new RegExp(args.pattern);
  const out = [];
  for (const a of document.querySelectorAll('a[href]')) {
    const href = a.getAttribute('href') || '';
    if (!rx.test(href)) continue;
    const text = (a.innerText || a.textContent || '').replace(/\\s+/g, ' ').trim();
    let el = a;
    for (let i = 0; i < 3 && el; i++) el = el.parentElement;
    const block = el ? (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 400) : '';
    out.push({href, text, block});
  }
  return out;
}
"""


def extract_listings(page, href_pattern):
    """Anchors matching a stable href pattern, with their surrounding text."""
    try:
        return page.evaluate(LISTING_SCRIPT, {"pattern": href_pattern}) or []
    except Exception:                             # noqa: BLE001
        return []


def money_from(text):
    match = re.search(r"\$\s?([\d.,]+)\s?([km])?", (text or "").lower())
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    return value * {"k": 1_000, "m": 1_000_000}.get(match.group(2) or "", 1)
