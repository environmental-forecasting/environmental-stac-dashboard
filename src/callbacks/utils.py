import math
from functools import lru_cache

from rio_tiler.colormap import ColorMaps

# One registry for the process: ColorMaps() loads cmap data on construction.
COLOR_MAPS = ColorMaps()


def round_2dp(value):
    return math.floor(value * 100) / 100


@lru_cache(maxsize=64)
def convert_colormap_to_colorscale(cmap: str):
    """
    Convert a rio_tiler colormap to colorscale format.

    Uses a shared `ColorMaps` instance and caches the colours as rgba
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
