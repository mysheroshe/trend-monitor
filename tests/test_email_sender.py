"""Email is optional: a missing or broken mail configuration must never fail the
daily pipeline.

Regression: GitHub Actions substitutes an **empty string** for secrets that are
not configured, and ``int(os.getenv("SMTP_PORT", "587"))`` raised
``ValueError`` on ``""``. That failed the "Run trend monitor" step of the first
real workflow run (run 38138386505) after the report had already been produced.
"""

import smtplib
import sys
import types

import pytest

from senders import email_sender

EMAIL_ENV = ("EMAIL_SENDER", "EMAIL_PASSWORD", "EMAIL_RECEIVER",
             "SMTP_SERVER", "SMTP_PORT")


class _FakeSMTP:
    """Records what the sender did, without touching the network."""

    instances = []

    def __init__(self, server, port, *args, **kwargs):
        self.server = server
        self.port = port
        self.started_tls = False
        self.login_args = None
        self.mail = None
        _FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user, password):
        self.login_args = (user, password)

    def sendmail(self, sender, recipient, message):
        self.mail = (sender, recipient, message)


def _clear_email_env(monkeypatch):
    for name in EMAIL_ENV:
        monkeypatch.delenv(name, raising=False)


def _configure_email(monkeypatch, port="587"):
    monkeypatch.setenv("EMAIL_SENDER", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-password")
    monkeypatch.setenv("EMAIL_RECEIVER", "receiver@example.com")
    monkeypatch.setenv("SMTP_SERVER", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", port)


@pytest.fixture(autouse=True)
def _reset_fake_smtp():
    _FakeSMTP.instances = []


# ---------------------------------------------------------------------------
# Missing / blank configuration
# ---------------------------------------------------------------------------

def test_missing_email_env_skips_sending(monkeypatch):
    _clear_email_env(monkeypatch)
    assert email_sender.send_email_report("# report") is False


def test_blank_email_env_skips_sending(monkeypatch):
    """The exact CI condition that broke the first real run."""
    for name in EMAIL_ENV:
        monkeypatch.setenv(name, "")

    assert email_sender.send_email_report("# report") is False


def test_partial_email_config_skips_sending_with_warning(monkeypatch, capsys):
    _clear_email_env(monkeypatch)
    monkeypatch.setenv("EMAIL_SENDER", "sender@example.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "")
    monkeypatch.setenv("EMAIL_RECEIVER", "")

    assert email_sender.send_email_report("# report") is False
    assert "跳过" in capsys.readouterr().out


@pytest.mark.parametrize("bad_port", ["not-a-port", "58 7", "587abc"])
def test_invalid_smtp_port_skips_sending_with_warning(monkeypatch, capsys, bad_port):
    _configure_email(monkeypatch, port=bad_port)

    assert email_sender.send_email_report("# report") is False
    assert "SMTP_PORT" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Configured: keep working, and never raise on failure
# ---------------------------------------------------------------------------

def test_blank_port_falls_back_to_default_and_still_sends(monkeypatch):
    _configure_email(monkeypatch, port="")
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    assert email_sender.send_email_report("# report") is True
    assert _FakeSMTP.instances[0].port == 587


def test_configured_email_is_actually_sent(monkeypatch):
    _configure_email(monkeypatch)
    monkeypatch.setattr(smtplib, "SMTP", _FakeSMTP)

    assert email_sender.send_email_report("# report") is True

    smtp = _FakeSMTP.instances[0]
    assert (smtp.server, smtp.port) == ("smtp.example.com", 587)
    assert smtp.started_tls is True
    assert smtp.login_args == ("sender@example.com", "app-password")
    assert smtp.mail[0] == "sender@example.com"
    assert smtp.mail[1] == "receiver@example.com"


def test_authentication_failure_is_logged_and_returns_false(monkeypatch, capsys):
    _configure_email(monkeypatch)

    class _AuthFailSMTP:
        def __init__(self, *args, **kwargs):
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(smtplib, "SMTP", _AuthFailSMTP)

    assert email_sender.send_email_report("# report") is False
    assert "认证失败" in capsys.readouterr().out


def test_unexpected_send_error_never_raises(monkeypatch, capsys):
    _configure_email(monkeypatch)

    class _BoomSMTP:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("connection reset by peer")

    monkeypatch.setattr(smtplib, "SMTP", _BoomSMTP)

    assert email_sender.send_email_report("# report") is False
    assert "发送错误" in capsys.readouterr().out


def test_markdown_rendering_error_never_raises(monkeypatch):
    _configure_email(monkeypatch)

    def _boom(*args, **kwargs):
        raise ValueError("bad markdown extension")

    monkeypatch.setattr(email_sender, "markdown_to_html", _boom)
    assert email_sender.send_email_report("# report") is False


# ---------------------------------------------------------------------------
# Whole pipeline
# ---------------------------------------------------------------------------

def _stub_playwright(monkeypatch):
    """main.py imports the collectors, and collectors/__init__ imports playwright."""
    package = types.ModuleType("playwright")
    sync_api = types.ModuleType("playwright.sync_api")

    class _TimeoutError(Exception):
        pass

    sync_api.sync_playwright = lambda *args, **kwargs: None
    sync_api.TimeoutError = _TimeoutError
    package.sync_api = sync_api
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api)


def test_pipeline_finishes_successfully_without_email_secrets(monkeypatch, tmp_path):
    """`python main.py` must exit cleanly when the email secrets are unset."""
    _stub_playwright(monkeypatch)
    import main as trend_monitor

    monkeypatch.setattr(sys, "argv", ["main.py"])
    for name in ("fetch_product_hunt_posts", "fetch_ai_tools", "fetch_chrome_extensions",
                 "fetch_trending_repos", "fetch_hackernews_posts"):
        monkeypatch.setattr(trend_monitor, name, lambda *args, **kwargs: [])
    monkeypatch.setattr(trend_monitor, "fetch_toolify_tools",
                        lambda *args, **kwargs: {"new": [], "trending": []})
    # the Phase 6/6.1 signal stages must not touch the network in a unit test
    monkeypatch.setattr(trend_monitor, "fetch_adapter_signals",
                        lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(trend_monitor, "fetch_browser_signals",
                        lambda *args, **kwargs: ([], []))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("storage.data_store.DATA_DIR", tmp_path / "data" / "daily")
    monkeypatch.setattr("storage.validation_store.default_path",
                        lambda: tmp_path / "validation" / "evidence.json")

    # exactly what GitHub Actions does when the email secrets are not configured
    for name in EMAIL_ENV:
        monkeypatch.setenv(name, "")

    trend_monitor.main()          # must not raise

    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "docs" / "index.html").exists()
    assert (tmp_path / "docs" / "indie.html").exists()
    assert (tmp_path / "analysis" / "daily").exists()
    assert (tmp_path / "data" / "daily").exists()
