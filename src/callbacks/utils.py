import math
from functools import lru_cache

import requests
from rio_tiler.colormap import ColorMaps

# One registry for the process: ColorMaps() loads cmap data on construction.
COLOR_MAPS = ColorMaps()


def round_2dp(value):
    return math.floor(value * 100) / 100


@lru_cache(maxsize=64)
def convert_colormap_to_colorscale(cmap: str):
    """
    Convert a rio_tiler colormap to colorscale format.

    Uses a shared `ColorMaps` instance and caches the Dash-leaflet colorscale
    strings so colormap changes do not rebuild the same palette repeatedly.

    Args:
        cmap: The name of the rio_tiler colormap to convert.

    Returns:
        A list of rgba color tuples in colorscale format.
            Each tuple is represented as a string with the format "rgba(R,G,B,A)".

    Example:
        >>> convert_colormap_to_colorscale("viridis")
        [
            'rgba(68,1,84,1.0)',
            ...
            'rgba(253,231,36,1.0)'
        ]
    """
    cmap_dict = COLOR_MAPS.get(cmap)
    return [
        f"rgba({cmap_dict[i][0]},{cmap_dict[i][1]},{cmap_dict[i][2]},{cmap_dict[i][3] / 255})"
        for i in range(len(cmap_dict))
    ]


def to_tiler_asset_url(href: str, file_server_url: str, file_server_internal_url: str) -> str:
    """Rewrite public file-server hrefs so TiTiler can fetch them on the Docker network."""
    if not file_server_url or not file_server_internal_url:
        return href
    public = file_server_url.rstrip("/")
    internal = file_server_internal_url.rstrip("/")
    if href == public or href.startswith(public + "/"):
        return internal + href[len(public) :]
    return href


def get_cog_band_statistics(TITILER_URL: str, cog_url: str, band_index: int) -> dict:
    stats_url = f"{TITILER_URL}/cog/statistics"
    r = requests.get(stats_url, params={"url": cog_url, "bidx": band_index})
    r.raise_for_status()
    stats = r.json()

    # Use the first key in the stats dictionary,
    # this should match the band returned.
    first_band_key = next(iter(stats))
    band_stats = stats[first_band_key]

    return band_stats
