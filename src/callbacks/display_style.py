"""Display-style helpers for the timeline colourbar."""

from components.controls import DEFAULT_COLORMAP

from .utils import convert_colormap_to_colorscale

DEFAULT_DISPLAY_STYLE = {
    "colormap": DEFAULT_COLORMAP,
    "vmin": 0.0,
    "vmax": 1.0,
    "domain_min": 0.0,
    "domain_max": 1.0,
    "locked": False,
    "source": "fallback",
}


def normalise_display_style(raw) -> dict:
    """
    Return a complete display-style dict from store data.

    Fills missing keys and keeps the colour domain at least as wide as the
    active min/max window.
    """
    style = dict(DEFAULT_DISPLAY_STYLE)
    if isinstance(raw, dict):
        for key in (
            "colormap",
            "vmin",
            "vmax",
            "domain_min",
            "domain_max",
            "locked",
            "source",
        ):
            if key in raw and raw[key] is not None:
                style[key] = raw[key]
    style["locked"] = bool(style.get("locked"))
    try:
        style["vmin"] = float(style["vmin"])
        style["vmax"] = float(style["vmax"])
    except (TypeError, ValueError):
        style["vmin"] = 0.0
        style["vmax"] = 1.0
    try:
        style["domain_min"] = float(style.get("domain_min", style["vmin"]))
        style["domain_max"] = float(style.get("domain_max", style["vmax"]))
    except (TypeError, ValueError):
        style["domain_min"] = style["vmin"]
        style["domain_max"] = style["vmax"]
    # Domain must always span the active window.
    style["domain_min"] = min(style["domain_min"], style["vmin"])
    style["domain_max"] = max(style["domain_max"], style["vmax"])
    if style["vmax"] < style["vmin"]:
        style["vmin"], style["vmax"] = style["vmax"], style["vmin"]
    if style["domain_max"] <= style["domain_min"]:
        style["domain_max"] = style["domain_min"] + 1.0
    if not style.get("colormap"):
        style["colormap"] = DEFAULT_COLORMAP
    return style


def cbar_ramp_style(colormap: str | None) -> dict:
    """Return a CSS style dict for the colourbar ramp gradient."""
    colorscale = convert_colormap_to_colorscale(colormap) if colormap else []
    ramp_colors = colorscale if isinstance(colorscale, list) and colorscale else []
    gradient = (
        f"linear-gradient(to right, {', '.join(ramp_colors)})" if ramp_colors else None
    )
    return {"background": gradient}


def cbar_slider_step(domain_min: float, domain_max: float) -> float:
    """Pick a RangeSlider step size from the colour domain span."""
    span = float(domain_max) - float(domain_min)
    if span <= 0:
        return 0.01
    raw = span / 100.0
    if raw >= 1:
        return max(1.0, round(raw))
    if raw >= 0.1:
        return round(raw, 2)
    return max(0.01, round(raw, 4))
