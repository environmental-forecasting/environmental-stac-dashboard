"""OSM Nominatim place-search provider."""

import logging

import requests

from .hits import (
    bbox_is_usable,
    default_zoom_for_kind,
    geojson_is_point_only,
)

logger = logging.getLogger(__name__)

_NOMINATIM = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "environmental-stac-dashboard/1.0 (forecast map search)"
ATTRIBUTION = "(c) OpenStreetMap Nominatim"


def _bbox_from_nominatim(row: dict) -> list[float] | None:
    """
    Convert a Nominatim bounding box into ``[west, south, east, north]``.

    Args:
        row: One Nominatim result, whose ``boundingbox`` is ordered
            south, north, west, east.

    Returns:
        Bounding box in west, south, east, north order, or None when the
        box is missing or degenerate.
    """
    raw = row.get("boundingbox")
    if not raw or len(raw) < 4:
        return None
    try:
        south, north, west, east = (
            float(raw[0]),
            float(raw[1]),
            float(raw[2]),
            float(raw[3]),
        )
    except (TypeError, ValueError):
        return None
    bbox = [west, south, east, north]
    return bbox if bbox_is_usable(bbox) else None


def search(query: str, *, limit: int = 5) -> list[dict]:
    """
    Resolve a place name through OSM Nominatim.

    Args:
        query: Free-text place name.
        limit: Maximum number of results to request.

    Returns:
        Hits shaped as ``{label, lon, lat, zoom, source, bbox?, geojson?}``.
        An empty list is returned when the query is too short or the
        request fails.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return []
    try:
        response = requests.get(
            _NOMINATIM,
            params={
                "q": q,
                "format": "json",
                "limit": limit,
                "polygon_geojson": 1,
            },
            headers={"User-Agent": _USER_AGENT},
            timeout=8,
        )
        response.raise_for_status()
        rows = response.json()
    except Exception as exc:
        logger.warning("Nominatim search failed for %r: %s", q, exc)
        return []

    hits: list[dict] = []
    for row in rows or []:
        try:
            lon = float(row["lon"])
            lat = float(row["lat"])
        except (KeyError, TypeError, ValueError):
            continue
        label = (row.get("display_name") or "").strip() or f"{lat:.4f}, {lon:.4f}"
        hit: dict = {
            "label": label,
            "lon": lon,
            "lat": lat,
            "source": "nominatim",
        }
        bbox = _bbox_from_nominatim(row)
        if bbox is not None:
            hit["bbox"] = bbox
        geojson = row.get("geojson")
        area_geojson = None
        if isinstance(geojson, dict) and geojson.get("type"):
            if not geojson_is_point_only(geojson):
                area_geojson = geojson
                hit["geojson"] = geojson
            elif bbox is None:
                hit["geojson"] = geojson
        place_type = (row.get("type") or row.get("class") or "").lower()
        has_area = area_geojson is not None or bbox is not None
        hit["zoom"] = default_zoom_for_kind(has_area=has_area, kind=place_type)
        hits.append(hit)
    return hits
