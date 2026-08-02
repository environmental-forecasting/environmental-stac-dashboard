"""Build browser-facing TiTiler XYZ URLs for forecast COGs."""

from .asset_urls import to_tiler_asset_url
from .projections import WEB_MERCATOR_QUAD


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
    tiler_base = tiler_url.rstrip("/")
    asset_url = to_tiler_asset_url(
        public_href, file_server_url, file_server_internal_url
    )
    tile_url = (
        f"{tiler_base}/cog/tiles/{tile_matrix_set}/{{z}}/{{x}}/{{y}}"
        f"?url={asset_url}"
    )

    if colormap:
        tile_url += f"&colormap_name={colormap}"
    if rescale is not None:
        min_val, max_val = rescale
        tile_url += f"&rescale={min_val},{max_val}"
    if band_index is not None:
        tile_url += f"&bidx={band_index}"

    return tile_url
