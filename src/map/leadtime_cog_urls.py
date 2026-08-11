"""Helpers for the map-state leadtime Item tile cache."""

from typing import Any


def rewrite_leadtime_cog_urls_style(
    leadtime_cog_urls: dict[str, Any] | None,
    *,
    colormap: str | None = None,
    rescale: tuple[float, float] | list[float] | None = None,
) -> dict[str, Any] | None:
    """
    Copy the leadtime Item tile cache with updated colour map and rescale.
    """
    if not isinstance(leadtime_cog_urls, dict):
        return None
    next_cache = dict(leadtime_cog_urls)
    if colormap is not None:
        next_cache["colormap"] = colormap
    if rescale is not None and len(rescale) >= 2:
        next_cache["rescale"] = [float(rescale[0]), float(rescale[1])]
    return next_cache
