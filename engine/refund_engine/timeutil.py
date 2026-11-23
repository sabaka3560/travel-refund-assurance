"""Integer-seconds interval maths, tz handling, day-unit readings.

Intervals are strictly integer seconds (Invariant I2). Floating point hours
are used exclusively for presentation/display.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400


def seconds_between(earlier: datetime, later: datetime) -> int:
    """Both must be tz-aware. Returns an exact integer second count (may be negative)."""
    if earlier.tzinfo is None or later.tzinfo is None:
        raise ValueError(
            "scheduled_departure and cancellation instant must be timezone-aware. "
            "A naive datetime cannot be positioned on the real timeline and would "
            "silently mis-place the boundary."
        )
    return int((later - earlier).total_seconds())


def hours_display(seconds: int) -> Decimal:
    """Two-decimal Decimal for presentation only. Never used for comparison."""
    return (Decimal(seconds) / Decimal(SECONDS_PER_HOUR)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calendar_days_between(later: datetime, earlier: datetime, tz: ZoneInfo) -> int:
    """Local-calendar-date difference in `tz`. Used only for DAYS-unit rules."""
    if earlier.tzinfo is None or later.tzinfo is None:
        raise ValueError("Both datetimes must be timezone-aware.")
    d_later = later.astimezone(tz).date()
    d_earlier = earlier.astimezone(tz).date()
    return (d_later - d_earlier).days


def elapsed_days(seconds: int) -> int:
    """seconds // 86400. Used only for DAYS-unit rules."""
    return seconds // SECONDS_PER_DAY
