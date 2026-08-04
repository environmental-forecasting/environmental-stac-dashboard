"""Intentional map paint requests (decoupled from control cascade races)."""

from typing import Any

DEFAULT_COLORMAP = "blues_r"
DEFAULT_VIEW_MODE = "global_3857"


def collections_list(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item]
    return []


def recipe_complete(
    *,
    collection: Any,
    forecast_start: Any,
    variable: Any,
) -> bool:
    """True when collection, init day, and band are all set."""
    if not collections_list(collection):
        return False
    if not isinstance(forecast_start, str) or not forecast_start:
        return False
    if variable is None or variable == "":
        return False
    return True


def build_map_request(
    previous: Any,
    *,
    collection: Any,
    forecast_start: Any,
    variable: Any,
    colormap: Any = None,
    view_mode: Any = None,
    lead: Any = None,
    force_stats: bool = False,
    clear_lock: bool = False,
    leadtime_only: bool = False,
    tms_only: bool = False,
    colormap_only: bool = False,
) -> dict[str, Any] | None:
    """
    Build the next ``map-request`` payload, or ``None`` to clear the map.

    Incomplete recipes return ``None``. ``revision`` always bumps when a
    non-None request is produced so Dash reliably triggers painting.
    """
    if not recipe_complete(
        collection=collection,
        forecast_start=forecast_start,
        variable=variable,
    ):
        return None

    prev = previous if isinstance(previous, dict) else {}
    try:
        band = int(variable)
    except (TypeError, ValueError):
        return None

    if lead is None:
        lead = 0
    try:
        lead = int(lead)
    except (TypeError, ValueError):
        lead = 0

    return {
        "collection": collections_list(collection),
        "forecast_start": forecast_start,
        "variable": band,
        "colormap": colormap or DEFAULT_COLORMAP,
        "view_mode": view_mode or DEFAULT_VIEW_MODE,
        "lead": lead,
        "force_stats": bool(force_stats),
        "clear_lock": bool(clear_lock),
        "leadtime_only": bool(leadtime_only),
        "tms_only": bool(tms_only),
        "colormap_only": bool(colormap_only),
        "revision": int(prev.get("revision", 0)) + 1,
    }
