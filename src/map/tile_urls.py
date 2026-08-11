"""Build browser-facing titiler-pgstac Item tile URLs."""

import re
from typing import Any
from urllib.parse import quote


def build_item_tile_url(
    *,
    tiler_base: str,
    tile_matrix_set: str,
    collection_id: str,
    item_id: str,
    asset_key: str,
    colormap: str | None = None,
    rescale: tuple[float, float] | list[float] | None = None,
    band_index: int | None = None,
) -> str:
    """
    Build an XYZ template for a titiler-pgstac Item tile.

    titiler-pgstac 3.0 selects the COG with ``assets={key}|bidx={n}``.
    Scrubbing changes ``assets=`` only; style stays on the query string.
    """
    assets = quote(asset_key, safe="")
    if band_index is not None:
        assets = quote(f"{asset_key}|bidx={band_index}", safe="")
    tile_url = (
        f"{tiler_base.rstrip('/')}/collections/{quote(collection_id, safe='')}"
        f"/items/{quote(item_id, safe='')}"
        f"/tiles/{tile_matrix_set}/{{z}}/{{x}}/{{y}}.webp?assets={assets}"
    )
    if colormap:
        tile_url += f"&colormap_name={colormap}"
    if rescale is not None:
        min_val, max_val = rescale[0], rescale[1]
        tile_url += f"&rescale={min_val},{max_val}"
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
