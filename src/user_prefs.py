"""Browser-persisted map control defaults (Dash ``storage_type="local"``)."""

from typing import Any

# Keep in sync with controls / header defaults (avoid importing Dash layout).
DEFAULT_COLORMAP = "blues_r"
DEFAULT_VIEW_MODE = "global_3857"
DEFAULT_BASEMAP_ID = "osm"


def normalise_user_prefs(raw: Any) -> dict[str, Any]:
    """Return a shallow, typed prefs dict from store data."""
    if not isinstance(raw, dict):
        return {}
    prefs: dict[str, Any] = {}

    collection = raw.get("collection")
    if isinstance(collection, str) and collection:
        prefs["collection"] = [collection]
    elif isinstance(collection, (list, tuple)):
        ids = [str(item) for item in collection if item]
        if ids:
            prefs["collection"] = ids

    forecast_start = raw.get("forecast_start")
    if isinstance(forecast_start, str) and forecast_start:
        prefs["forecast_start"] = forecast_start

    variable = raw.get("variable")
    if variable is not None and variable != "":
        try:
            prefs["variable"] = int(variable)
        except (TypeError, ValueError):
            pass

    colormap = raw.get("colormap")
    if isinstance(colormap, str) and colormap:
        prefs["colormap"] = colormap

    view_mode = raw.get("view_mode")
    if isinstance(view_mode, str) and view_mode:
        prefs["view_mode"] = view_mode

    basemap = raw.get("basemap")
    if isinstance(basemap, str) and basemap:
        prefs["basemap"] = basemap

    colorbar = raw.get("colorbar")
    if isinstance(colorbar, dict) and colorbar.get("locked"):
        try:
            vmin = float(colorbar["vmin"])
            vmax = float(colorbar["vmax"])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            if vmax < vmin:
                vmin, vmax = vmax, vmin
            prefs["colorbar"] = {"vmin": vmin, "vmax": vmax, "locked": True}

    return prefs


def merge_user_prefs(
    *,
    collection: Any = None,
    forecast_start: Any = None,
    variable: Any = None,
    colormap: Any = None,
    view_mode: Any = None,
    basemap: Any = None,
    display_style: Any = None,
) -> dict[str, Any] | None:
    """Build prefs from live controls. Returns None for factory-only / empty."""
    if isinstance(collection, str) and collection:
        collections = [collection]
    elif isinstance(collection, (list, tuple)):
        collections = [str(item) for item in collection if item]
    else:
        collections = []

    prefs: dict[str, Any] = {}
    if collections:
        prefs["collection"] = collections
        if isinstance(forecast_start, str) and forecast_start:
            prefs["forecast_start"] = forecast_start
        if variable is not None and variable != "":
            try:
                prefs["variable"] = int(variable)
            except (TypeError, ValueError):
                pass

    if isinstance(colormap, str) and colormap:
        prefs["colormap"] = colormap

    if isinstance(view_mode, str) and view_mode and view_mode != DEFAULT_VIEW_MODE:
        prefs["view_mode"] = view_mode

    if isinstance(basemap, str) and basemap and basemap != DEFAULT_BASEMAP_ID:
        prefs["basemap"] = basemap

    if isinstance(display_style, dict) and display_style.get("locked"):
        try:
            prefs["colorbar"] = {
                "vmin": float(display_style["vmin"]),
                "vmax": float(display_style["vmax"]),
                "locked": True,
            }
        except (KeyError, TypeError, ValueError):
            pass

    if not prefs:
        return None
    # Factory-only cosmetic prefs: clear storage.
    if set(prefs) <= {"colormap", "view_mode", "basemap"}:
        if prefs.get("colormap", DEFAULT_COLORMAP) == DEFAULT_COLORMAP:
            if prefs.get("view_mode", DEFAULT_VIEW_MODE) == DEFAULT_VIEW_MODE:
                if prefs.get("basemap", DEFAULT_BASEMAP_ID) == DEFAULT_BASEMAP_ID:
                    return None
    return prefs


def preferred_in(prefs: Any, key: str, valid: Any = None):
    """Return prefs[key] when present and in ``valid`` (if given)."""
    value = normalise_user_prefs(prefs).get(key)
    if value is None:
        return None
    if valid is not None and value not in set(valid):
        return None
    return value


def preferred_collections(prefs: Any, valid_ids) -> list[str] | None:
    wanted = normalise_user_prefs(prefs).get("collection") or []
    matched = [c for c in wanted if c in set(valid_ids)]
    return matched or None


def display_style_seed_from_prefs(prefs: Any) -> dict[str, Any] | None:
    """Seed display-style from colormap / locked colourbar prefs."""
    normalised = normalise_user_prefs(prefs)
    if "colormap" not in normalised and "colorbar" not in normalised:
        return None
    style = {
        "colormap": normalised.get("colormap") or DEFAULT_COLORMAP,
        "vmin": 0.0,
        "vmax": 1.0,
        "domain_min": 0.0,
        "domain_max": 1.0,
        "locked": False,
        "source": "fallback",
    }
    colorbar = normalised.get("colorbar")
    if colorbar:
        style.update(
            {
                "vmin": float(colorbar["vmin"]),
                "vmax": float(colorbar["vmax"]),
                "domain_min": float(colorbar["vmin"]),
                "domain_max": float(colorbar["vmax"]),
                "locked": True,
                "source": "user",
            }
        )
    return style
