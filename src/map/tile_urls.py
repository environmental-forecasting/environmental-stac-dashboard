"""Build browser-facing TiTiler XYZ URLs for forecast COGs."""

import re
from typing import Any

from .asset_urls import to_tiler_asset_url
from .projections import WEB_MERCATOR_QUAD


def build_xyz_tile_url(
    *,
    tiler_base: str,
    tile_matrix_set: str,
    asset_url: str,
    colormap: str | None = None,
    rescale: tuple[float, float] | list[float] | None = None,
    band_index: int | None = None,
) -> str:
    """
    Build an XYZ tile template from a TiTiler-facing asset URL.

    Args:
        tiler_base: Browser-facing TiTiler origin.
        tile_matrix_set: TiTiler tile matrix set id.
        asset_url: Value for the ``url`` query parameter.
        colormap: Optional rio-tiler colormap name.
        rescale: Optional display range as ``(min, max)``.
        band_index: Optional one-based band number (``bidx``).

    Returns:
        XYZ template URL with ``{z}``, ``{x}``, and ``{y}`` placeholders.
    """
    tile_url = (
        f"{tiler_base.rstrip('/')}/cog/tiles/{tile_matrix_set}/{{z}}/{{x}}/{{y}}"
        f"?url={asset_url}"
    )
    if colormap:
        tile_url += f"&colormap_name={colormap}"
    if rescale is not None:
        min_val, max_val = rescale[0], rescale[1]
        tile_url += f"&rescale={min_val},{max_val}"
    if band_index is not None:
        tile_url += f"&bidx={band_index}"
    return tile_url


def rewrite_tile_url_style(
    tile_url: str,
    *,
    colormap: str | None = None,
    rescale: tuple[float, float] | list[float] | None = None,
) -> str:
    """
    Update colour map and rescale values on a TiTiler tile URL.

    Adds missing parameters, or replaces them when they are already present.
    """
    if not isinstance(tile_url, str) or not tile_url:
        return tile_url
    next_url = tile_url
    if colormap is not None:
        if "colormap_name=" in next_url:
            next_url = re.sub(
                r"([?&])colormap_name=[^&]*",
                rf"\1colormap_name={colormap}",
                next_url,
                count=1,
            )
        else:
            sep = "&" if "?" in next_url else "?"
            next_url = f"{next_url}{sep}colormap_name={colormap}"
    if rescale is not None and len(rescale) >= 2:
        pair = f"{rescale[0]},{rescale[1]}"
        if "rescale=" in next_url:
            next_url = re.sub(
                r"([?&])rescale=[^&]*",
                rf"\1rescale={pair}",
                next_url,
                count=1,
            )
        else:
            sep = "&" if "?" in next_url else "?"
            next_url = f"{next_url}{sep}rescale={pair}"
    return next_url


def rewrite_layer_entries_style(
    layers: list[dict[str, Any]] | None,
    *,
    colormap: str | None = None,
    rescale: tuple[float, float] | list[float] | None = None,
) -> list[dict[str, Any]] | None:
    """
    Copy overlay layers with colour map and rescale query values updated.
    """
    if not layers:
        return None
    rewritten: list[dict[str, Any]] = []
    for layer in layers:
        if not isinstance(layer, dict):
            return None
        url = layer.get("tileUrl")
        if not isinstance(url, str):
            return None
        next_layer = dict(layer)
        next_layer["tileUrl"] = rewrite_tile_url_style(
            url, colormap=colormap, rescale=rescale
        )
        rewritten.append(next_layer)
    return rewritten


def build_cog_tile_url(
    public_href: str,
    *,
    tiler_url: str,
    file_server_url: str,
    file_server_internal_url: str,
    tile_matrix_set: str = WEB_MERCATOR_QUAD,
    colormap: str | None = None,
    rescale: tuple[float, float] | None = None,
    band_index: int | None = None,
) -> str:
    """
    Build a TiTiler XYZ template URL for a COG asset.

    The browser calls ``tiler_url``; the ``url`` query parameter points at an
    href TiTiler can open (``file:///data/...`` when under the data mount).

    Args:
        public_href: Public STAC asset href for the COG.
        tiler_url: Browser-facing TiTiler base URL.
        file_server_url: Public file-server prefix used in STAC hrefs.
        file_server_internal_url: File-server URL reachable from TiTiler
            (fallback for non-``/data/`` paths).
        tile_matrix_set: TiTiler tile matrix set id (for example
            ``WebMercatorQuad`` or ``EPSG6931``).
        colormap: Optional rio-tiler colormap name.
        rescale: Optional ``(min, max)`` display range.
        band_index: Optional one-based band index (``bidx``).

    Returns:
        XYZ template URL with ``{z}``, ``{x}``, and ``{y}`` placeholders.
    """
    asset_url = to_tiler_asset_url(
        public_href, file_server_url, file_server_internal_url
    )
    return build_xyz_tile_url(
        tiler_base=tiler_url,
        tile_matrix_set=tile_matrix_set,
        asset_url=asset_url,
        colormap=colormap,
        rescale=rescale,
        band_index=band_index,
    )
