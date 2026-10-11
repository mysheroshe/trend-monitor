"""One explicit timezone strategy for the whole project.

Previously report timestamps used PST via ``ZoneInfo`` while file names and
storage cutoffs used the system's local time. Everything now goes through the
helpers below so the project has a single notion of "today".
"""

from datetime import datetime
from zoneinfo import ZoneInfo

# Pacific time: the timezone the daily/weekly schedules and reports were
# always documented in (see README and the GitHub Actions cron comments).
TIMEZONE_NAME = "America/Los_Angeles"

TZ = ZoneInfo(TIMEZONE_NAME)


def now():
    """Current time as a timezone-aware datetime in Pacific time."""
    return datetime.now(TZ)


def today_str():
    """Today's date in Pacific time, as ``YYYY-MM-DD`` (used for file names)."""
    return now().strftime("%Y-%m-%d")


def timestamp_str():
    """Report timestamp, e.g. ``2026-10-11 07:00 (PDT)``."""
    return now().strftime("%Y-%m-%d %H:%M (%Z)")


def display_str():
    """Long human-readable timestamp, e.g. ``October 11, 2026 - 07:00 PDT``."""
    current = now()
    return current.strftime(f"%B %d, %Y - %H:%M {current.strftime('%Z')}")
