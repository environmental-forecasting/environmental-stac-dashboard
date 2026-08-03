"""Helpers for the map-state leadtime COG URL cache."""

from typing import Any

from .projections import WEB_MERCATOR_QUAD
from .tile_urls import build_xyz_tile_url


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
        layers.append(
            {
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
        )
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
