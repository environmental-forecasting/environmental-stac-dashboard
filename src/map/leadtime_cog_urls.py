"""Helpers for the map-state leadtime COG URL cache."""

from typing import Any

from .projections import WEB_MERCATOR_QUAD
from .tile_urls import build_xyz_tile_url


def build_leadtime_cog_urls(
    *,
    tiler_base: str,
    tile_matrix_set: str,
    hrefs_by_collection: dict[str, list[str]],
    colormap: str | None = None,
    rescale: tuple[float, float] | list[float] | None = None,
    band_index: int | None = None,
    reference_time: str | None = None,
    bbox_by_collection: dict[str, list[float]] | None = None,
) -> dict[str, Any] | None:
    """
    Build the ``leadtimeCogUrls`` payload published on map-state.

    Holds every leadtime step of the current forecast so the browser can swap
    overlay URLs while scrubbing or playing without another catalogue query.

    Args:
        tiler_base: Browser-facing TiTiler origin.
        tile_matrix_set: TiTiler tile matrix set id.
        hrefs_by_collection: TiTiler-facing COG URLs per collection, ordered
            by leadtime step.
        colormap: rio-tiler colormap name shared by every step.
        rescale: Display range as ``(min, max)`` shared by every step.
        band_index: One-based band number (``bidx``).
        reference_time: Forecast init as a STAC datetime string.
        bbox_by_collection: Optional WGS84 ``[west, south, east, north]`` per
            collection so the map can clamp tile requests to the data footprint.

    Returns:
        Payload for map-state ``leadtimeCogUrls``, or None when no collection
        has usable hrefs.
    """
    collections: dict[str, Any] = {}
    bboxes = bbox_by_collection or {}
    for collection_id, hrefs in (hrefs_by_collection or {}).items():
        usable = [href for href in (hrefs or []) if href]
        if not usable:
            continue
        meta: dict[str, Any] = {"hrefs": usable}
        bbox = bboxes.get(collection_id)
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            meta["bbox"] = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
        collections[collection_id] = meta
    if not collections or not tiler_base:
        return None

    payload: dict[str, Any] = {
        "tilerBase": tiler_base.rstrip("/"),
        "tileMatrixSet": tile_matrix_set or WEB_MERCATOR_QUAD,
        "colormap": colormap,
        "bidx": band_index,
        "collections": collections,
    }
    if rescale is not None and len(rescale) >= 2:
        payload["rescale"] = [float(rescale[0]), float(rescale[1])]
    else:
        payload["rescale"] = None
    if reference_time:
        payload["refTime"] = reference_time
    return payload


def leadtime_cog_urls_match_style(
    leadtime_cog_urls: dict[str, Any] | None,
    *,
    tile_matrix_set: str,
    colormap: str | None,
    rescale: tuple[float, float] | list[float] | None,
    band_index: int | None,
    collection_ids: list[str] | None,
) -> bool:
    """
    Return whether a cached payload can still serve the requested style.

    The cache may hold fewer collections than the dropdown when some were
    dropped for not fitting the view mode, so every cached collection must
    still be selected but the cache need not cover all of them.
    """
    if not isinstance(leadtime_cog_urls, dict):
        return False
    if leadtime_cog_urls.get("tileMatrixSet") != tile_matrix_set:
        return False
    if leadtime_cog_urls.get("colormap") != colormap:
        return False
    if leadtime_cog_urls.get("bidx") != band_index:
        return False
    cached_rescale = leadtime_cog_urls.get("rescale")
    if rescale is None or len(rescale) < 2:
        return False
    if not isinstance(cached_rescale, (list, tuple)) or len(cached_rescale) < 2:
        return False
    if float(cached_rescale[0]) != float(rescale[0]):
        return False
    if float(cached_rescale[1]) != float(rescale[1]):
        return False
    cached_ids = set((leadtime_cog_urls.get("collections") or {}).keys())
    selected = {cid for cid in (collection_ids or []) if cid}
    return bool(cached_ids) and cached_ids.issubset(selected)


def layers_from_leadtime_cog_urls(
    leadtime_cog_urls: dict[str, Any] | None, lead: int
) -> list[dict[str, Any]]:
    """
    Build overlay layers for one leadtime from the cached COG URL list.

    The cache stores one COG URL per leadtime step for each collection, plus
    the shared colour and band settings used to build tile URLs without
    another catalogue request.

    Args:
        leadtime_cog_urls: Payload stored on map-state as ``leadtimeCogUrls``.
        lead: Zero-based leadtime step.

    Returns:
        Layer dicts ready for map-state ``layers``.
    """
    if not isinstance(leadtime_cog_urls, dict) or lead < 0:
        return []
    tiler_base = leadtime_cog_urls.get("tilerBase")
    tile_matrix_set = leadtime_cog_urls.get("tileMatrixSet") or WEB_MERCATOR_QUAD
    collections = leadtime_cog_urls.get("collections")
    if not tiler_base or not isinstance(collections, dict):
        return []
    colormap = leadtime_cog_urls.get("colormap")
    rescale = leadtime_cog_urls.get("rescale")
    band_index = leadtime_cog_urls.get("bidx")
    rescale_pair: tuple[float, float] | None = None
    if isinstance(rescale, (list, tuple)) and len(rescale) >= 2:
        rescale_pair = (float(rescale[0]), float(rescale[1]))

    layers: list[dict[str, Any]] = []
    for collection_id, meta in collections.items():
        if not isinstance(meta, dict):
            continue
        hrefs = meta.get("hrefs") or []
        if lead >= len(hrefs):
            continue
        asset_url = hrefs[lead]
        if not asset_url:
            continue
        entry: dict[str, Any] = {
            "id": collection_id,
            "title": collection_id,
            "tileUrl": build_xyz_tile_url(
                tiler_base=tiler_base,
                tile_matrix_set=tile_matrix_set,
                asset_url=asset_url,
                colormap=colormap,
                rescale=rescale_pair,
                band_index=band_index,
            ),
            "opacity": 1,
            "visible": True,
        }
        bbox = meta.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            entry["bbox"] = [float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])]
        layers.append(entry)
    return layers


def rewrite_leadtime_cog_urls_style(
    leadtime_cog_urls: dict[str, Any] | None,
    *,
    colormap: str | None = None,
    rescale: tuple[float, float] | list[float] | None = None,
) -> dict[str, Any] | None:
    """
    Copy the leadtime COG URL cache with updated colour map and rescale.
    """
    if not isinstance(leadtime_cog_urls, dict):
        return None
    next_cache = dict(leadtime_cog_urls)
    if colormap is not None:
        next_cache["colormap"] = colormap
    if rescale is not None and len(rescale) >= 2:
        next_cache["rescale"] = [float(rescale[0]), float(rescale[1])]
    return next_cache


def rewrite_leadtime_cog_urls_tms(
    leadtime_cog_urls: dict[str, Any] | None, tile_matrix_set: str
) -> dict[str, Any] | None:
    """
    Copy the leadtime COG URL cache with an updated tile matrix set id.
    """
    if not isinstance(leadtime_cog_urls, dict) or not tile_matrix_set:
        return None
    next_cache = dict(leadtime_cog_urls)
    next_cache["tileMatrixSet"] = tile_matrix_set
    return next_cache
