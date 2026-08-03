"""Shared helpers for place-search hits."""

import re

_MIN_BBOX_SPAN_DEG = 0.01


def geojson_is_point_only(geojson: dict) -> bool:
    """
    Return whether a geometry only carries points and no area outline.

    Args:
        geojson: Geometry, Feature, or FeatureCollection dict.

    Returns:
        True when every geometry in ``geojson`` is Point or MultiPoint.
    """
    geom_type = geojson.get("type")
    if geom_type in ("Point", "MultiPoint"):
        return True
    if geom_type == "Feature":
        geometry = geojson.get("geometry")
        return isinstance(geometry, dict) and geojson_is_point_only(geometry)
    if geom_type == "FeatureCollection":
        features = geojson.get("features") or []
        return bool(features) and all(
            isinstance(feature, dict) and geojson_is_point_only(feature)
            for feature in features
        )
    return False


def bbox_is_usable(bbox: list[float] | None) -> bool:
    """
    Return whether a bounding box has a real extent.

    Args:
        bbox: Bounding box as ``[west, south, east, north]``.

    Returns:
        True when the box is well formed and not degenerate.
    """
    if not bbox or len(bbox) < 4:
        return False
    try:
        west, south, east, north = (
            float(bbox[0]),
            float(bbox[1]),
            float(bbox[2]),
            float(bbox[3]),
        )
    except (TypeError, ValueError):
        return False
    if east <= west or north <= south:
        return False
    if (east - west) < _MIN_BBOX_SPAN_DEG and (north - south) < _MIN_BBOX_SPAN_DEG:
        return False
    return True


def hit_has_area(hit: dict) -> bool:
    """
    Return whether a hit already carries a usable outline or extent.

    Args:
        hit: Search hit dict.

    Returns:
        True when the hit has an area geometry or a usable bbox.
    """
    geojson = hit.get("geojson")
    if isinstance(geojson, dict) and geojson.get("type"):
        if not geojson_is_point_only(geojson):
            return True
    return bbox_is_usable(hit.get("bbox"))


def normalise_place_name(text: str) -> str:
    """
    Lowercase a place name and collapse punctuation for matching.

    Args:
        text: Raw place name.

    Returns:
        Normalised lookup key.
    """
    cleaned = re.sub(r"[^\w\s]", " ", (text or "").lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip()


def title_from_label(label: str) -> str:
    """
    Return the first comma-separated segment of a display label.

    Args:
        label: Full display label from a search provider.

    Returns:
        Leading segment, which is usually the place name.
    """
    text = (label or "").strip()
    if not text:
        return ""
    return text.split(",", 1)[0].strip()


def default_zoom_for_kind(*, has_area: bool, kind: str | None = None) -> int:
    """
    Pick a sensible display zoom for a hit.

    Kind wins over ``has_area`` so seas and bays keep a wide framing zoom even
    after Natural Earth attaches a polygon to them.

    Args:
        has_area: Whether the hit already carries an outline or bbox.
        kind: Provider place type such as ``bay``, ``state``, or ``city``.

    Returns:
        Zoom level for the hit.
    """
    token = (kind or "").lower()
    if token in {
        "bay",
        "sea",
        "ocean",
        "strait",
        "sound",
        "gulf",
        "marine",
        "ice_shelf",
        "ice shelf",
    }:
        return 5
    if token in {"state", "province", "region", "county", "boundary"}:
        return 7
    if token in {"city", "town"}:
        return 11
    if has_area:
        return 16
    return 14
