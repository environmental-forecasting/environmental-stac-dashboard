"""Fetch and parse TiTiler tile matrix sets for OpenLayers views."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# Custom TMS files from generate_custom_tms.py use ids like EPSG6931.
CUSTOM_EPSG_TMS_ID_RE = re.compile(r"^EPSG(\d+)$")

# Remember good lookups only. If the tile server was briefly down, try again
# next time instead of treating that failure as permanent.
_tile_grid_cache: dict[tuple[str, str], dict[str, Any]] = {}
_tms_list_cache: dict[str, tuple[str, ...]] = {}


def tile_grid_from_tms(tms: dict[str, Any]) -> dict[str, Any]:
    """
    Build an OpenLayers tile-grid hint from an OGC TileMatrixSet document.

    Args:
        tms: TiTiler ``/tileMatrixSets/{id}`` JSON body.

    Returns:
        Dict with ``extent``, ``origin``, and ``resolutions`` (metres / pixel).

    Raises:
        ValueError: If the document has no usable tile matrices.
        KeyError: If required matrix fields are missing.
    """
    matrices = tms.get("tileMatrices") or []
    if not matrices:
        raise ValueError("tile matrix set has no tileMatrices")

    z0 = matrices[0]
    origin = [float(z0["pointOfOrigin"][0]), float(z0["pointOfOrigin"][1])]
    resolutions = [float(matrix["cellSize"]) for matrix in matrices]
    tile_width = int(z0.get("tileWidth", 256))
    tile_height = int(z0.get("tileHeight", 256))
    minx, maxy = origin
    width = int(z0["matrixWidth"]) * tile_width * float(z0["cellSize"])
    height = int(z0["matrixHeight"]) * tile_height * float(z0["cellSize"])
    extent = [minx, maxy - height, minx + width, maxy]
    return {
        "extent": extent,
        "origin": origin,
        "resolutions": resolutions,
    }


def _get_json(url: str, *, timeout: float = 5.0) -> Any | None:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        logger.warning("TiTiler request failed (%s): %s", url, exc)
        return None
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not load TiTiler URL %s: %s", url, exc)
        return None


def fetch_tile_matrix_set(
    tiler_url: str, tms_id: str, *, timeout: float = 5.0
) -> dict[str, Any] | None:
    """
    Fetch one tile matrix set document from TiTiler.

    Args:
        tiler_url: TiTiler base URL (internal or public).
        tms_id: Matrix set id such as ``EPSG6931``.
        timeout: HTTP timeout in seconds.

    Returns:
        Parsed JSON object, or None if the set is missing or unreachable.
    """
    base = (tiler_url or "").rstrip("/")
    if not base or not tms_id:
        return None

    payload = _get_json(f"{base}/tileMatrixSets/{tms_id}", timeout=timeout)
    if payload is None:
        return None
    if not isinstance(payload, dict):
        logger.warning("Unexpected TMS payload for %s", tms_id)
        return None
    return payload


def list_tile_matrix_set_ids(tiler_url: str) -> tuple[str, ...]:
    """
    Return all tile matrix set ids advertised by TiTiler.

    Good replies are remembered. If the tile server was unreachable, avoid
    remembering that failure, so a later call can still succeed.

    Args:
        tiler_url: TiTiler base URL.

    Returns:
        Tuple of TMS ids (empty when the tiler is unreachable).
    """
    base = (tiler_url or "").rstrip("/")
    if not base:
        return ()
    cached = _tms_list_cache.get(base)
    if cached is not None:
        return cached

    payload = _get_json(f"{base}/tileMatrixSets")
    if not isinstance(payload, dict):
        return ()

    ids: list[str] = []
    for entry in payload.get("tileMatrixSets") or []:
        if isinstance(entry, dict) and entry.get("id"):
            ids.append(str(entry["id"]))
    result = tuple(ids)
    _tms_list_cache[base] = result
    return result


def list_custom_epsg_tms_ids(tiler_url: str) -> list[str]:
    """
    Return custom-style ``EPSG####`` TMS ids registered on TiTiler.

    Filters out stock morecantile names (``WebMercatorQuad``, ``UPSArctic...``,
    etc.) so only grids named like this project's ``custom_tms`` files appear.

    Args:
        tiler_url: TiTiler base URL.

    Returns:
        Sorted list of TMS ids (by EPSG code).
    """
    matched = [
        tms_id
        for tms_id in list_tile_matrix_set_ids(tiler_url)
        if CUSTOM_EPSG_TMS_ID_RE.fullmatch(tms_id)
    ]
    return sorted(matched, key=lambda tms_id: int(tms_id[4:]))


def get_tile_grid(tiler_url: str, tms_id: str) -> dict[str, Any] | None:
    """
    Return a cached OpenLayers tile-grid hint for a TiTiler TMS id.

    Remember a grid once it has loaded cleanly. If the tile server did
    not answer, try again on the next call.

    Args:
        tiler_url: TiTiler base URL.
        tms_id: Matrix set id such as ``EPSG6931``.

    Returns:
        Tile-grid dict, or None when the TMS cannot be loaded or parsed.
    """
    base = (tiler_url or "").rstrip("/")
    if not base or not tms_id:
        return None
    cache_key = (base, tms_id)
    cached = _tile_grid_cache.get(cache_key)
    if cached is not None:
        return cached

    tms = fetch_tile_matrix_set(base, tms_id)
    if tms is None:
        return None
    try:
        grid = tile_grid_from_tms(tms)
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("Could not parse TiTiler TMS %s: %s", tms_id, exc)
        return None
    _tile_grid_cache[cache_key] = grid
    return grid


def clear_tile_grid_cache() -> None:
    """Clear cached TMS list and grid lookups (for tests)."""
    _tile_grid_cache.clear()
    _tms_list_cache.clear()
