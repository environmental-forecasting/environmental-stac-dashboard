"""Rewrite colour-bar query params on titiler-pgstac Item tile URLs."""

import re
from typing import Any


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
