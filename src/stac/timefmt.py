"""
Shared datetime formats for the dashboard.

Only two string shapes are used on purpose:

- Calendar day (``YYYY-MM-DD``): date picker, store keys, disabled dates, slider maths.
- STAC datetime (RFC 3339 via pystac ``datetime_to_str``): Item property queries
  such as ``forecast:reference_time``.

Slider mark labels use a short display form derived from a calendar day, not a
third storage format.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from pystac.utils import datetime_to_str, str_to_datetime

# UI / store: date only (no time).
CALENDAR_DAY_FMT = "%Y-%m-%d"
# Leadtime slider labels only (never stored or sent to STAC).
SLIDER_LABEL_FMT = "%d %b %y"


def to_calendar_day(value: datetime | date) -> str:
    """Format a datetime or date as ``YYYY-MM-DD``."""
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime(CALENDAR_DAY_FMT)


def parse_calendar_day(day: str) -> datetime:
    """Parse ``YYYY-MM-DD`` as midnight UTC."""
    return datetime.strptime(day, CALENDAR_DAY_FMT).replace(tzinfo=timezone.utc)


def to_stac_datetime(value: datetime) -> str:
    """Format a datetime the same way STAC Item properties are written."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return datetime_to_str(value)


def parse_stac_datetime(value: str | datetime) -> datetime:
    """Parse a STAC datetime string (or pass through an existing datetime)."""
    if isinstance(value, datetime):
        return value
    return str_to_datetime(value)


def date_picker_to_reference_time(day: str) -> str:
    """
    Convert a date-picker value (``YYYY-MM-DD``) to ``forecast:reference_time``.

    Assumes forecast initialisation at midnight UTC on that calendar day.
    """
    return to_stac_datetime(parse_calendar_day(day))


def format_slider_label(value: datetime | date) -> str:
    """Short label for the leadtime slider (display only)."""
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime(SLIDER_LABEL_FMT)
