"""Reddit demand-source tests (Phase 7) - mocked API, no live calls."""

import pytest

from analyzers import signals as S
from analyzers.reddit_demand import (
    PAYMENT_ACTUAL,
    PAYMENT_STATED,
    PAYMENT_UNKNOWN,
    classify_post,
    dedup_signals,
    engagement_strength,
    keyword_seeds,
    payment_confidence,
    quality_gate,
    recurring_pain,
    reddit_demand_score,
    theme_key,
    to_signals,
)
from collectors.adapters import reddit_api


def _post(title, selftext="", subreddit="SaaS", post_id="p1", score=50, comments=10,
          age=6):
    return {"id": post_id, "title": title, "selftext": selftext, "subreddit": subreddit,
            "score": score, "num_comments": comments, "permalink": f"/r/{subreddit}/comments/{post_id}/x",
            "created_utc": 1730000000, "post_age_hours": age}


# --- configuration / credentials ------------------------------------------

def test_missing_credentials_reports_not_configured(monkeypatch):
    for name in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT"):
        monkeypatch.delenv(name, raising=False)
    signals, health = reddit_api.fetch()

    assert signals == []
    assert health["status"] == "NOT_CONFIGURED"
    assert health["auth_status"] == "NOT_CONFIGURED"
    assert "REDDIT_CLIENT_ID" in health["last_error"]


def test_auth_failure_does_not_raise(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")

    class _Resp:
        status_code = 401

    monkeypatch.setattr(reddit_api.requests, "post", lambda *a, **k: _Resp())
    signals, health = reddit_api.fetch()

    assert signals == []
    assert health["status"] == "AUTH_FAILED"
    assert health["auth_status"] == "AUTH_FAILED"


def test_rate_limit_is_reported_and_survived(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "secret")

    class _Token:
        status_code = 200

        @staticmethod
        def json():
            return {"access_token": "t"}

    class _Limited:
        status_code = 429
        headers = {}

    monkeypatch.setattr(reddit_api.requests, "post", lambda *a, **k: _Token())
    monkeypatch.setattr(reddit_api.requests, "get", lambda *a, **k: _Limited())
    signals, health = reddit_api.fetch(subreddits=["SaaS"])

    assert signals == []
    assert health["status"] in ("RATE_LIMITED", "API_ERROR")
    assert "RATE_LIMITED" in (health["last_error"] or "")


def test_credential_helper_reads_the_environment(monkeypatch):
    monkeypatch.setenv("REDDIT_CLIENT_ID", "abc")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "def")
    assert reddit_api.configured() is True


# --- classification --------------------------------------------------------

def test_is_there_a_tool_becomes_demand_signal():
    types, _ = classify_post(_post("Is there a tool that checks Excel formulas for mistakes?"))
    assert S.DEMAND_SIGNAL in types


def test_too_expensive_becomes_pain_and_competition():
    types, _ = classify_post(_post("Notion is too expensive, any alternative to it?"))
    assert S.PAIN_SIGNAL in types
    assert S.COMPETITION_SIGNAL in types


def test_missing_feature_becomes_feature_gap():
    types, _ = classify_post(_post("X needs bulk export, the missing feature is painful"))
    assert S.FEATURE_GAP_SIGNAL in types


def test_actual_spend_is_detected():
    assert payment_confidence("I pay a VA $300/month to clean these reports") == PAYMENT_ACTUAL
    assert payment_confidence("we spend $120 per month on this") == PAYMENT_ACTUAL


def test_stated_willingness_is_not_actual_spend():
    assert payment_confidence("I would pay for this") == PAYMENT_STATED
    assert payment_confidence("happy to pay for a good tool") == PAYMENT_STATED
    assert payment_confidence("nice idea") == PAYMENT_UNKNOWN


def test_self_promo_without_demand_is_rejected():
    ok, reason = quality_gate(_post("Check out my new tool, shameless plug"))
    assert ok is False
    assert "self-promotion" in reason


def test_meme_and_offtopic_posts_are_rejected():
    assert quality_gate(_post("Best meme about startups"))[0] is False
    assert quality_gate(_post("What business should I start in 2026?"))[0] is False
    assert quality_gate(_post("AI is the future and here is why it matters a lot"))[0] is False


def test_engagement_strength_bands():
    assert engagement_strength(500, 10) == "HIGH"
    assert engagement_strength(60, 5) == "MEDIUM"
    assert engagement_strength(3, 1) == "LOW"


def test_signal_keeps_only_public_reddit_fields():
    post = _post("Is there a tool for spreadsheet reconciliation?",
                 "I currently do this in excel and it takes hours", post_id="abc", score=88)
    signals = to_signals(post, [{"body": "we do this manually too", "author": "u1"},
                                {"body": "is there a tool for this?", "author": "u2"}])
    assert signals
    signal = signals[0]
    assert signal["source"] == "reddit"
    assert signal["raw_metadata"]["supporting_comment_count"] == 2
    assert "author" not in signal                   # no user profiling stored


def test_comment_confirmation_increases_evidence_modestly():
    post = _post("Is there a tool that validates invoices?")
    alone = to_signals(post, [])[0]
    confirmed = to_signals(post, [{"body": "is there a tool for this?", "author": "a"},
                                  {"body": "I wish there was a tool", "author": "b"}])[0]
    assert alone["evidence_strength"] == "LOW"
    assert confirmed["evidence_strength"] == "MEDIUM"
    assert confirmed["raw_metadata"]["confirmed_by_multiple_users"] is True


# --- dedup / recurrence / score -------------------------------------------

def test_duplicate_reddit_posts_are_deduped():
    post = _post("Is there a tool for invoice checking?", post_id="dup1")
    signals = to_signals(post) + to_signals(dict(post))
    for signal in signals:
        signal.setdefault("raw_metadata", {})["post_id"] = "dup1"
    assert len(dedup_signals(signals)) < len(signals)


def test_same_pain_across_independent_posts_increases_recurrence():
    posts = [_post("Is there a tool for spreadsheet reconciliation?", post_id=f"p{i}",
                   subreddit=sub, score=40)
             for i, sub in enumerate(["excel", "smallbusiness", "SaaS", "analytics"])]
    signals = []
    for post in posts:
        for signal in to_signals(post):
            signal["subreddit"] = post["subreddit"]
            signal["score"] = post["score"]
            signals.append(signal)
    themes = recurring_pain(signals)
    assert len(themes) == 1
    theme = themes[0]
    assert theme["independent_post_count"] == 4
    assert theme["pain_persistence"] in ("REPEATED", "PERSISTENT")
    assert theme["reddit_demand_level"] in ("MEDIUM", "HIGH")


def test_one_viral_post_cannot_reach_high_demand():
    signals = []
    for signal in to_signals(_post("Is there a tool for X?", post_id="viral", score=5000,
                                   comments=900)):
        signal["subreddit"] = "SaaS"
        signal["score"] = 5000
        signals.append(signal)
    theme = recurring_pain(signals)[0]
    assert theme["independent_post_count"] == 1
    assert theme["reddit_demand_level"] == "LOW"
    assert theme["reddit_demand_score"] < 60


def test_demand_score_bounds():
    score, level = reddit_demand_score({"independent_post_count": 100, "subreddits": ["a"] * 20,
                                        "engagement_total": 10**6, "has_actual_spend": True})
    assert 0 <= score <= 100
    assert level in ("LOW", "MEDIUM", "HIGH")


# --- keyword seeds / unmatched --------------------------------------------

def test_reddit_keyword_seed_passes_normal_filters():
    seeds = keyword_seeds("I need something that checks formulas in spreadsheets")
    assert seeds, "an anchored pain phrase should yield a seed"
    from analyzers.keyword_quality import keyword_maturity
    assert all(keyword_maturity(seed) in ("NICHE", "BROAD") for seed in seeds)


def test_brand_and_awkward_rules_still_hold_for_seeds():
    from analyzers.keyword_quality import MATURITY_AWKWARD, MATURITY_BRAND, keyword_maturity
    assert keyword_maturity("monica all one summarizer") == MATURITY_AWKWARD
    assert keyword_maturity("harpa ai summarizer", None, ["harpa"]) == MATURITY_BRAND


def test_theme_key_is_deterministic_for_the_same_pain():
    a = to_signals(_post("Is there a tool that checks spreadsheet formulas?", post_id="x1"))[0]
    b = to_signals(_post("Is there a tool that checks spreadsheet formulas?", post_id="x2"))[0]
    assert theme_key(a) == theme_key(b)


def test_reddit_never_sets_a_verdict():
    signals = to_signals(_post("Is there a tool for invoice checking?"), [])
    for signal in signals:
        assert "verdict" not in signal
        assert signal["signal_type"] in (S.PAIN_SIGNAL, S.DEMAND_SIGNAL,
                                         S.FEATURE_GAP_SIGNAL, S.COMPETITION_SIGNAL,
                                         S.PAYMENT_SIGNAL)
