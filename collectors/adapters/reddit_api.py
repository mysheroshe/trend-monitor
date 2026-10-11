"""Reddit demand adapter using the OFFICIAL API only (Phase 7).

App-only OAuth (client credentials) - no HTML scraping, no login bypass, no
CAPTCHA/paywall circumvention, no tight loops. When credentials are absent the
adapter reports NOT_CONFIGURED and the pipeline continues normally.

Config (environment only):
    REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT
    optional: REDDIT_USERNAME, REDDIT_PASSWORD (script/password flow)
"""

import os
import time

import requests

from analyzers.reddit_demand import (
    DEFAULT_SUBREDDITS,
    dedup_signals,
    enrich_metadata,
    quality_gate,
    to_signals,
)

SOURCE = "reddit"
TIER = 1
RENDER_MODE = "PUBLIC_JSON"           # official API, not a browser render

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"

DEFAULT_LIMIT_PER_SUBREDDIT = 15
MAX_SUBREDDITS_PER_RUN = 20
MAX_ACCEPTED_SIGNALS = 60
REQUEST_TIMEOUT = 12
LOW_QUOTA_THRESHOLD = 10

AUTH_STATUS = "UNKNOWN"
RATE_LIMIT_REMAINING = None
LAST_ERROR = ""


def _env(name, default=""):
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value or default


def credentials():
    return {
        "client_id": _env("REDDIT_CLIENT_ID"),
        "client_secret": _env("REDDIT_CLIENT_SECRET"),
        "user_agent": _env("REDDIT_USER_AGENT", "trend-monitor/1.1 (personal research)"),
        "username": _env("REDDIT_USERNAME"),
        "password": _env("REDDIT_PASSWORD"),
    }


def configured():
    creds = credentials()
    return bool(creds["client_id"] and creds["client_secret"])


def _health(**overrides):
    health = {
        "source": SOURCE, "tier": TIER, "status": "EMPTY", "auth_status": AUTH_STATUS,
        "requests_made": 0, "posts_fetched": 0, "posts_accepted": 0,
        "comments_fetched": 0, "rate_limit_remaining": RATE_LIMIT_REMAINING,
        "last_error": LAST_ERROR, "runtime_seconds": 0.0,
        "render_mode": RENDER_MODE, "signal_types": ["PAIN_SIGNAL", "DEMAND_SIGNAL",
                                                     "FEATURE_GAP_SIGNAL", "COMPETITION_SIGNAL",
                                                     "PAYMENT_SIGNAL"],
    }
    health.update(overrides)
    return health


def _token(creds, stats):
    """App-only OAuth token (password flow only when a user is configured)."""
    data = {"grant_type": "client_credentials"}
    if creds["username"] and creds["password"]:
        data = {"grant_type": "password", "username": creds["username"],
                "password": creds["password"]}
    response = requests.post(
        TOKEN_URL, auth=(creds["client_id"], creds["client_secret"]), data=data,
        headers={"User-Agent": creds["user_agent"]}, timeout=REQUEST_TIMEOUT,
    )
    stats["requests_made"] += 1
    if response.status_code in (401, 403):
        return None, "AUTH_FAILED"
    if response.status_code == 429:
        return None, "RATE_LIMITED"
    if response.status_code != 200:
        return None, f"API_ERROR (token HTTP {response.status_code})"
    try:
        token = response.json().get("access_token")
    except ValueError:
        return None, "API_ERROR (invalid token JSON)"
    return (token, "") if token else (None, "AUTH_FAILED")


def _get(path, creds, token, stats):
    global RATE_LIMIT_REMAINING
    response = requests.get(
        API_BASE + path,
        headers={"Authorization": f"bearer {token}", "User-Agent": creds["user_agent"]},
        timeout=REQUEST_TIMEOUT,
    )
    stats["requests_made"] += 1
    remaining = response.headers.get("x-ratelimit-remaining")
    if remaining is not None:
        try:
            RATE_LIMIT_REMAINING = float(remaining)
        except ValueError:
            pass
    if response.status_code == 429:
        return None, "RATE_LIMITED"
    if response.status_code in (401, 403):
        return None, "AUTH_FAILED"
    if response.status_code != 200:
        return None, f"API_ERROR (HTTP {response.status_code})"
    try:
        return response.json(), ""
    except ValueError:
        return None, "API_ERROR (invalid JSON)"


def _top_comments(post_id, creds, token, stats, limit=3):
    data, error = _get(f"/comments/{post_id}?limit={limit}&sort=top", creds, token, stats)
    if error or not data:
        return []
    comments = []
    for listing in data[1:2]:
        for child in (listing.get("data", {}) or {}).get("children", [])[:limit]:
            body = (child.get("data", {}) or {}).get("body")
            if body:
                comments.append({"body": body,
                                 "author": (child.get("data", {}) or {}).get("author")})
    return comments


def fetch(limit_per_subreddit=DEFAULT_LIMIT_PER_SUBREDDIT, subreddits=None,
          top_comments=3, use_comments=True):
    """Return (signals, health). Never raises."""
    global LAST_ERROR, AUTH_STATUS
    started = time.time()
    LAST_ERROR = ""
    stats = {"requests_made": 0}

    if not configured():
        AUTH_STATUS = "NOT_CONFIGURED"
        LAST_ERROR = "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not configured"
        return [], _health(status="NOT_CONFIGURED", auth_status="NOT_CONFIGURED",
                           last_error=LAST_ERROR,
                           runtime_seconds=round(time.time() - started, 1))

    creds = credentials()
    token, error = _token(creds, stats)
    if error:
        AUTH_STATUS = "AUTH_FAILED" if error == "AUTH_FAILED" else error
        LAST_ERROR = error
        status = {"AUTH_FAILED": "AUTH_FAILED", "RATE_LIMITED": "RATE_LIMITED"}.get(error, "API_ERROR")
        return [], _health(status=status, auth_status=AUTH_STATUS, last_error=error,
                           requests_made=stats["requests_made"],
                           runtime_seconds=round(time.time() - started, 1))
    AUTH_STATUS = "OK"

    subs = (subreddits or DEFAULT_SUBREDDITS)[:MAX_SUBREDDITS_PER_RUN]
    signals, posts_fetched, accepted, comments_fetched = [], 0, 0, 0
    for subreddit in subs:
        if RATE_LIMIT_REMAINING is not None and RATE_LIMIT_REMAINING < LOW_QUOTA_THRESHOLD:
            LAST_ERROR = (LAST_ERROR or "") + f"stopped early: rate-limit quota "
            LAST_ERROR += f"remaining={RATE_LIMIT_REMAINING}"
            break
        if accepted >= MAX_ACCEPTED_SIGNALS:
            break
        data, error = _get(f"/r/{subreddit}/top?t=day&limit={limit_per_subreddit}",
                           creds, token, stats)
        if error:
            LAST_ERROR = f"{subreddit}: {error}"
            if error == "RATE_LIMITED":
                break
            continue
        children = (data.get("data", {}) or {}).get("children", []) if data else []
        for child in children:
            post = child.get("data") or {}
            posts_fetched += 1
            ok, _reason = quality_gate(post)
            if not ok:
                continue
            comments = []
            if use_comments and top_comments:
                comments = _top_comments(post.get("id"), creds, token, stats, top_comments)
                comments_fetched += len(comments)
            for signal in to_signals(post, comments):
                signal.setdefault("raw_metadata", {})["post_id"] = post.get("id")
                signals.append(enrich_metadata(signal, post))
            accepted += 1
            if accepted >= MAX_ACCEPTED_SIGNALS:
                break

    signals = dedup_signals(signals)
    if signals:
        status = "OK"
    elif LAST_ERROR:
        status = "API_ERROR"
    else:
        status = "EMPTY"
    return signals, _health(
        status=status, auth_status=AUTH_STATUS, requests_made=stats["requests_made"],
        posts_fetched=posts_fetched, posts_accepted=accepted,
        comments_fetched=comments_fetched, last_error=LAST_ERROR,
        runtime_seconds=round(time.time() - started, 1),
    )
