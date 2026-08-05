"""
Shared datetime formats for the dashboard.

Only two string shapes are used on purpose:

- Calendar day (``YYYY-MM-DD``): date picker, store keys, disabled dates, slider maths.
- STAC datetime (RFC 3339 via pystac ``datetime_to_str``): Item property queries
  such as ``forecast:reference_time``.

Slider mark labels use a short display form derived from each lead's valid
time, not a third storage format. Valid-time labels adapt to the forecast
step unit (hour / day / week / month) inferred from spacing between leads.
"""

from datetime import date, datetime, timezone

from pystac.utils import datetime_to_str, str_to_datetime

# UI / store: date only (no time).
CALENDAR_DAY_FMT = "%Y-%m-%d"
# Leadtime slider labels only (never stored or sent to STAC).
SLIDER_LABEL_FMT = "%d %b %y"
SLIDER_LABEL_HOUR_FMT = "%H:%M %d %b"
SLIDER_LABEL_WEEK_FMT = "%d %b %y"
SLIDER_LABEL_MONTH_FMT = "%b %y"
VALID_TIME_DAY_FMT = "%d %b %Y"
VALID_TIME_HOUR_FMT = "%H:%M %d %b %Y"
VALID_TIME_WEEK_FMT = "%d %b %Y"
VALID_TIME_MONTH_FMT = "%b %Y"


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


def format_slider_label(
    value: datetime | date, *, step_unit: str = "day"
) -> str:
    """Short label for the leadtime slider (display only)."""
    unit = (step_unit or "day").lower()
    if unit in ("hour", "hours"):
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        return value.strftime(SLIDER_LABEL_HOUR_FMT)
    if unit in ("month", "months"):
        if isinstance(value, datetime):
            value = value.date()
        return value.strftime(SLIDER_LABEL_MONTH_FMT)
    if unit in ("week", "weeks"):
        if isinstance(value, datetime):
            value = value.date()
        return value.strftime(SLIDER_LABEL_WEEK_FMT)
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime(SLIDER_LABEL_FMT)


def format_valid_time(
    value: datetime | date, *, step_unit: str = "day"
) -> str:
    """Primary valid-time label under the map (display only)."""
    unit = (step_unit or "day").lower()
    if unit in ("hour", "hours"):
        if isinstance(value, date) and not isinstance(value, datetime):
            value = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        return value.strftime(VALID_TIME_HOUR_FMT)
    if unit in ("month", "months"):
        if isinstance(value, datetime):
            value = value.date()
        return value.strftime(VALID_TIME_MONTH_FMT)
    if unit in ("week", "weeks"):
        if isinstance(value, datetime):
            value = value.date()
        return value.strftime(VALID_TIME_WEEK_FMT)
    if isinstance(value, datetime):
        value = value.date()
    return value.strftime(VALID_TIME_DAY_FMT)


def step_unit_subtitle(step_unit: str = "day") -> str:
    """Short copy explaining what one scrubber step represents."""
    unit = (step_unit or "day").lower()
    if unit in ("hour", "hours"):
        return "Each frame is one forecast step (hourly)"
    if unit in ("week", "weeks"):
        return "Each frame is one forecast step (weekly)"
    if unit in ("month", "months"):
        return "Each frame is one forecast step (monthly)"
    return "Each frame is one forecast step (daily)"
