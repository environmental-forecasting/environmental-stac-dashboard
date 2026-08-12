"""Place and coordinate lookup for the map search box."""

import re

from map.place_search import place_search

# lat then lon, with optional N/S/E/W. Two bare numbers are read as lat, lon.
_COORD_RE = re.compile(
    r"""
    ^\s*
    (?P<a>[+-]?\d+(?:\.\d+)?)\s*(?P<a_hem>[NnSsEeWw])?
    (?:\s*[,;/\s]\s*)
    (?P<b>[+-]?\d+(?:\.\d+)?)\s*(?P<b_hem>[NnSsEeWw])?
    \s*$
    """,
    re.VERBOSE,
)


def parse_lon_lat(text: str) -> tuple[float, float] | None:
    """
    Parse a typed coordinate pair.

    Args:
        text: Query text such as ``60.0 N, 86.0 W`` or ``60, -86``.

    Returns:
        ``(lon, lat)`` when the text is a coordinate pair inside valid
        ranges, otherwise None.
    """
    match = _COORD_RE.match(text or "")
    if not match:
        return None
    a = float(match.group("a"))
    b = float(match.group("b"))
    a_hem = (match.group("a_hem") or "").upper()
    b_hem = (match.group("b_hem") or "").upper()

    def _signed(value: float, hem: str, *, negative: str) -> float:
        if hem and hem in negative:
            return -abs(value)
        if hem:
            return abs(value)
        return value

    if a_hem in ("N", "S") or b_hem in ("E", "W"):
        lat = _signed(a, a_hem, negative="S")
        lon = _signed(b, b_hem, negative="W")
    elif a_hem in ("E", "W") or b_hem in ("N", "S"):
        lon = _signed(a, a_hem, negative="W")
        lat = _signed(b, b_hem, negative="S")
    else:
        lat, lon = a, b

    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return None
    return lon, lat


__all__ = [
    "parse_lon_lat",
    "place_search",
]
