import logging
import math
import time
from datetime import datetime, timedelta
from functools import lru_cache

import dash
import dash_leaflet as dl
from components.controls import (
    AVAILABLE_COLORMAPS,
    DEFAULT_COLORMAP,
    forecast_init_disabled_dates,
)
from config import (
    STAC_FASTAPI_URL,
    TILER_INTERNAL_URL,
)
from dash import Input, Output, State, callback_context, no_update
from dash.exceptions import PreventUpdate
from stac.process import STAC
from stac.timefmt import (
    format_slider_label,
    format_valid_time,
    parse_stac_datetime,
    step_unit_subtitle,
    to_calendar_day,
)
from user_prefs import (
    DEFAULT_VIEW_MODE,
    display_style_seed_from_prefs,
    merge_user_prefs,
    normalise_user_prefs,
    preferred_collections,
    preferred_in,
)

from map import (
    DEFAULT_BASEMAP_ID,
    MapEngine,
    MapViewMode,
    basemap_descriptor,
    build_map_request,
    build_map_state,
    resolve_live_colormap,
    initial_map_state,
    list_basemap_options,
    list_view_mode_options,
    list_view_mode_presets,
    resolve_engine_for_mode,
    rewrite_layer_entries_style,
    rewrite_leadtime_cog_urls_style,
    view_mode_and_hint,
)

from .display_style import (
    DEFAULT_DISPLAY_STYLE,
    cbar_ramp_style,
    cbar_slider_step,
    normalise_display_style,
)
from .utils import round_2dp

_BUSY_HIDDEN = "forecast-busy is-hidden"
# Match --bp-drawer / --layout-* in forecast_map.css (media queries cannot
# read custom properties, so keep the pixel values mirrored here).
_DRAWER_BREAKPOINT_PX = 900
_CONTROLS_COLUMN_PX = 320
_CONTROLS_SEAM_PX = 22
_ULTRAWIDE_CONTROLS_PX = 360
_ULTRAWIDE_BREAKPOINT_PX = 1600


def _map_face_width(window_width: int | None, controls_open: bool | None) -> int:
    """Approximate the map column width for leadtime mark density."""
    width = int(window_width or 1200)
    if width <= _DRAWER_BREAKPOINT_PX:
        # Overlay drawer: map is full-bleed.
        return max(320, width)
    if not controls_open:
        return max(320, width)
    controls = (
        _ULTRAWIDE_CONTROLS_PX
        if width >= _ULTRAWIDE_BREAKPOINT_PX
        else _CONTROLS_COLUMN_PX
    )
    return max(320, width - controls - _CONTROLS_SEAM_PX)


@lru_cache(maxsize=1)
def _get_stac_client() -> STAC:
    """Return a cached STAC client singleton to avoid re-creating
    HTTP connections on every callback invocation."""
    return STAC(STAC_FASTAPI_URL)


def _end_calendar_day_from_init(row: dict) -> str | None:
    """Calendar end day for the leadtime slider, from a list_forecast_inits row."""
    end_time = row.get("end_time")
    if end_time:
        try:
            return to_calendar_day(parse_stac_datetime(end_time))
        except (TypeError, ValueError):
            pass

    leadtime_length = row.get("leadtime_length")
    init_dt = row.get("datetime")
    if leadtime_length is not None and init_dt is not None:
        return to_calendar_day(init_dt + timedelta(days=int(leadtime_length)))
    return None


_WEB_MERCATOR_Z0 = 156543.03392804097


def _mercator_max_native_zoom(gsd: object) -> int | None:
    """Highest Web Mercator z to fetch before the browser stretches tiles."""
    try:
        size = float(gsd)
    except (TypeError, ValueError):
        return None
    if size <= 0:
        return None
    min_cell = size / 32
    for zoom in range(0, 23):
        if _WEB_MERCATOR_Z0 / (2**zoom) < min_cell:
            return max(0, zoom - 1)
    return None


def _build_leaflet_overlays(layer_entries: list[dict]) -> list:
    """Build Leaflet Overlay children from shared layer descriptors."""
    tile_layers = []
    for index, layer in enumerate(layer_entries):
        tile_kwargs: dict = {
            "id": {"type": "cog-collections", "index": index},
            "url": layer["tileUrl"],
            "zIndex": 100,
            "opacity": layer.get("opacity", 1),
        }
        max_native = _mercator_max_native_zoom(layer.get("gsd"))
        if max_native is not None:
            tile_kwargs["maxNativeZoom"] = max_native
        tile_layers.append(
            dl.Overlay(
                dl.TileLayer(**tile_kwargs),
                name=layer.get("title") or layer["id"],
                checked=layer.get("visible", True),
            )
        )
    return tile_layers


# Callback function that will update the output container based on input
def register_callbacks(app: dash.Dash):
    """
    Registers Dash callbacks for updating COG layers and their opacities on the map.

    Args:
        The Dash app instance.
    """

    # Publish viewport width on load and whenever the window is resized.
    # Only write when the width changes so leadtime mark density updates
    # without a polling Interval.
    app.clientside_callback(
        """
        function(_) {
            if (!window._stacWindowWidthBound) {
                window._stacWindowWidthBound = true;
                let lastWidth = window.innerWidth;
                window.addEventListener("resize", function() {
                    const width = window.innerWidth;
                    if (width === lastWidth) {
                        return;
                    }
                    lastWidth = width;
                    dash_clientside.set_props("window-width", {data: width});
                });
            }
            return window.innerWidth;
        }
        """,
        Output("window-width", "data"),
        Input("page-load-trigger", "data"),
    )

    # Overlay-drawer breakpoint (≤900): auto-collapse controls when entering
    # drawer mode or on first load if already narrow. Do not auto-open when
    # widening - leave the user's toggle choice alone.
    app.clientside_callback(
        """
        function(width, isOpen) {
            var nu = window.dash_clientside.no_update;
            var bp = 900;
            var nowWide = (width == null ? window.innerWidth : Number(width)) > bp;
            var wasWide = window.__controlsLayoutWide;
            window.__controlsLayoutWide = nowWide;
            if (nowWide) {
                return [nu, nu, nu];
            }
            // First paint on a narrow viewport, or crossing down through bp.
            var enteringDrawer = wasWide === undefined || wasWide === true;
            if (!enteringDrawer || !isOpen) {
                return [nu, nu, nu];
            }
            return [
                "forecast-controls-column forecast-controls-column--collapsed",
                false,
                "tabler:chevron-left",
            ];
        }
        """,
        Output("controls-column", "className", allow_duplicate=True),
        Output("controls-open", "data", allow_duplicate=True),
        Output("controls-seam-icon", "icon", allow_duplicate=True),
        Input("window-width", "data"),
        State("controls-open", "data"),
        prevent_initial_call=True,
    )

    # Push map-state into the OpenLayers / Leaflet bridge.
    app.clientside_callback(
        """
        function(mapState) {
            if (window.ForecastMap && typeof window.ForecastMap.applyState === "function") {
                window.ForecastMap.applyState(mapState);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("map-bridge-tick", "data"),
        Input("map-state", "data"),
    )

    # Map busy labels: Dash owns the banner text. Soft-swap handoff to
    # "Loading tiles…" lives in ForecastMap.applyState after map-state lands.
    app.clientside_callback(
        """
        function(collections, date, variable, colormap, confirm, mode, resetClicks, style) {
            var nu = window.dash_clientside.no_update;
            var trig = window.dash_clientside.callback_context.triggered_id;
            if (!trig) {
                return [nu, nu];
            }
            // Locked colormap / style-only edits apply clientside - no wait.
            if (trig === "colormap-dropdown" && style && style.locked) {
                return [nu, nu];
            }
            // Routine leadtime confirms soft-swap in the browser; only forced
            // rebuilds (Auto / first paint) should show a map wait.
            if (trig === "leadtime-confirm") {
                if (!(confirm && confirm.force)) {
                    return [nu, nu];
                }
                return ["forecast-busy", "Updating map…"];
            }
            // Collection / date STAC waits are separate Outputs below.
            if (trig === "collections-dropdown" || trig === "forecast-init-date-picker") {
                return [nu, nu];
            }
            if (trig === "map-view-mode") {
                return ["forecast-busy", "Updating map…"];
            }
            if (trig === "colorbar-range-reset") {
                return ["forecast-busy", "Updating colour range…"];
            }
            return ["forecast-busy", "Updating map…"];
        }
        """,
        Output("forecast-busy", "className", allow_duplicate=True),
        Output("forecast-busy-label", "children", allow_duplicate=True),
        Input("collections-dropdown", "value"),
        Input("forecast-init-date-picker", "value"),
        Input("variable-dropdown", "value"),
        Input("colormap-dropdown", "value"),
        Input("leadtime-confirm", "data"),
        Input("map-view-mode", "value"),
        Input("colorbar-range-reset", "n_clicks"),
        State("display-style", "data"),
        prevent_initial_call=True,
    )

    # STAC busy banner: Dash owns #forecast-busy className/label.
    app.clientside_callback(
        """
        function(collections) {
            var nu = window.dash_clientside.no_update;
            if (!collections || (Array.isArray(collections) && collections.length === 0)) {
                return ["forecast-busy is-hidden", nu];
            }
            return ["forecast-busy", "Loading forecast dates…"];
        }
        """,
        Output("forecast-busy", "className", allow_duplicate=True),
        Output("forecast-busy-label", "children", allow_duplicate=True),
        Input("collections-dropdown", "value"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(date, collections) {
            var nu = window.dash_clientside.no_update;
            if (!date || !collections || (Array.isArray(collections) && collections.length === 0)) {
                return [nu, nu];
            }
            return ["forecast-busy", "Loading variables…"];
        }
        """,
        Output("forecast-busy", "className", allow_duplicate=True),
        Output("forecast-busy-label", "children", allow_duplicate=True),
        Input("forecast-init-date-picker", "value"),
        State("collections-dropdown", "value"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(pageLoad) {
            return ["forecast-busy", "Loading catalog…"];
        }
        """,
        Output("forecast-busy", "className", allow_duplicate=True),
        Output("forecast-busy-label", "children", allow_duplicate=True),
        Input("page-load-trigger", "data"),
        prevent_initial_call="initial_duplicate",
    )

    # Optimistic view-mode switch (engine + TMS + projection; no Python wait).
    app.clientside_callback(
        """
        function(mode, presets) {
            if (window.ForecastMap && typeof window.ForecastMap.applyViewMode === "function") {
                window.ForecastMap.applyViewMode(mode, presets || {});
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("map-bridge-tick", "data", allow_duplicate=True),
        Input("map-view-mode", "value"),
        State("map-view-presets", "data"),
        prevent_initial_call=True,
    )

    # Show north-up controls only for polar / custom EPSG#### modes.
    app.clientside_callback(
        """
        function(mode) {
            var polar = !!(mode && /^EPSG\\d+$/.test(mode));
            return polar
                ? "forecast-map-north-up"
                : "forecast-map-north-up is-hidden";
        }
        """,
        Output("map-north-up-wrap", "className"),
        Input("map-view-mode", "value"),
        prevent_initial_call=False,
    )

    # Toggle one-shot pick vs continuous lock (mutually exclusive; Esc clears).
    app.clientside_callback(
        """
        function(pickN, lockN, mode) {
            if (window.__forecastNorthUpOn == null) {
                window.__forecastNorthUpOn = false;
            }
            if (window.__forecastNorthUpLockOn == null) {
                window.__forecastNorthUpLockOn = false;
            }
            var triggered = window.dash_clientside.callback_context.triggered_id;
            var polar = !!(mode && /^EPSG\\d+$/.test(mode));
            if (triggered === "map-north-up-btn" && polar && pickN) {
                if (window.__forecastNorthUpOn) {
                    // Cancel pick mode without changing orientation.
                    window.__forecastNorthUpOn = false;
                } else {
                    // Enter pick mode (also when already rotated from a prior pick).
                    window.__forecastNorthUpOn = true;
                    window.__forecastNorthUpLockOn = false;
                }
            } else if (triggered === "map-north-up-lock-btn" && polar && lockN) {
                window.__forecastNorthUpLockOn = !window.__forecastNorthUpLockOn;
                if (window.__forecastNorthUpLockOn) {
                    window.__forecastNorthUpOn = false;
                }
            }
            if (!polar) {
                window.__forecastNorthUpOn = false;
                window.__forecastNorthUpLockOn = false;
            }
            var on = !!(polar && window.__forecastNorthUpOn);
            var lockOn = !!(polar && window.__forecastNorthUpLockOn);
            if (window.ForecastMap) {
                if (typeof window.ForecastMap.setNorthUpClickEnabled === "function") {
                    window.ForecastMap.setNorthUpClickEnabled(on);
                }
                if (typeof window.ForecastMap.setNorthUpLockEnabled === "function") {
                    window.ForecastMap.setNorthUpLockEnabled(lockOn);
                }
            }
            return [
                on ? "forecast-map-north-up__btn is-active" : "forecast-map-north-up__btn",
                lockOn ? "forecast-map-north-up__btn is-active" : "forecast-map-north-up__btn",
            ];
        }
        """,
        Output("map-north-up-btn", "className"),
        Output("map-north-up-lock-btn", "className"),
        Input("map-north-up-btn", "n_clicks"),
        Input("map-north-up-lock-btn", "n_clicks"),
        Input("map-view-mode", "value"),
        prevent_initial_call=False,
    )

    # One browser STAC search per date / collection. Keep the last overlay
    # until the new Item is in hand (do not clear leadtimeCogUrls here).
    app.clientside_callback(
        """
        function(date, collections, variable, colormap, viewMode, displayStyle, userPrefs) {
            if (window.ForecastMap
                    && typeof window.ForecastMap.loadForecast === "function") {
                var prefs = userPrefs || {};
                window.ForecastMap.loadForecast({
                    date: date,
                    collections: collections,
                    variable: variable != null ? variable : prefs.variable,
                    colormap: colormap,
                    viewMode: viewMode,
                    displayStyle: displayStyle,
                });
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("map-bridge-tick", "data", allow_duplicate=True),
        Input("forecast-init-date-picker", "value"),
        Input("collections-dropdown", "value"),
        State("variable-dropdown", "value"),
        State("colormap-dropdown", "value"),
        State("map-view-mode", "value"),
        State("display-style", "data"),
        State("user-prefs", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(variable, displayStyle) {
            if (window.ForecastMap
                    && typeof window.ForecastMap.applyBand === "function") {
                window.ForecastMap.applyBand(variable, displayStyle);
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("map-bridge-tick", "data", allow_duplicate=True),
        Input("variable-dropdown", "value"),
        State("display-style", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(colormap, displayStyle) {
            var nu = window.dash_clientside.no_update;
            if (!window.ForecastMap
                    || typeof window.ForecastMap.applyStyle !== "function") {
                return [nu, nu];
            }
            var style = displayStyle || {};
            window.ForecastMap.applyStyle({
                colormap: colormap,
                vmin: style.vmin,
                vmax: style.vmax,
            });
            if (style.locked || !colormap || colormap === style.colormap) {
                return [nu, nu];
            }
            return [Object.assign({}, style, { colormap: colormap }), nu];
        }
        """,
        Output("display-style", "data", allow_duplicate=True),
        Output("map-bridge-tick", "data", allow_duplicate=True),
        Input("colormap-dropdown", "value"),
        State("display-style", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(refresh) {
            if (window.ForecastMap
                    && typeof window.ForecastMap.applyAutoScale === "function") {
                window.ForecastMap.applyAutoScale();
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("map-bridge-tick", "data", allow_duplicate=True),
        Input("map-style-refresh", "data"),
        prevent_initial_call=True,
    )

    # Swap overlay URLs straight from the published leadtimeCogUrls cache, then
    # ask Python to confirm once scrubbing settles. Playback never confirms:
    # the browser owns every frame until the user pauses.
    app.clientside_callback(
        """
        function(lead, playing) {
            var nu = window.dash_clientside.no_update;
            if (window.ForecastMap
                    && typeof window.ForecastMap.applyLeadtimeIndex === "function") {
                window.ForecastMap.applyLeadtimeIndex(lead, {
                    playing: !!playing,
                });
            }
            if (window.__leadtimeConfirmTimer) {
                clearTimeout(window.__leadtimeConfirmTimer);
                window.__leadtimeConfirmTimer = null;
            }
            if (playing) {
                return nu;
            }
            // Without a cache the first paint still comes from Python, which
            // the date / variable / collection inputs already trigger.
            if (!window.ForecastMap
                    || typeof window.ForecastMap.hasLeadtimeCogUrls !== "function"
                    || !window.ForecastMap.hasLeadtimeCogUrls()) {
                return nu;
            }
            var leadValue = lead;
            window.__leadtimeConfirmTimer = setTimeout(function () {
                window.__leadtimeConfirmTimer = null;
                window.dash_clientside.set_props("leadtime-confirm", {
                    data: {lead: leadValue, ts: Date.now()},
                });
            }, 350);
            return nu;
        }
        """,
        Output("map-bridge-tick", "data", allow_duplicate=True),
        Input("leadtime-slider", "value"),
        State("leadtime-playing", "data"),
        prevent_initial_call=True,
    )

    # Pausing leaves the slider where playback stopped, so confirm that step
    # right away instead of waiting for another scrub.
    app.clientside_callback(
        """
        function(playing, lead) {
            var nu = window.dash_clientside.no_update;
            if (playing) {
                return nu;
            }
            if (!window.ForecastMap
                    || typeof window.ForecastMap.hasLeadtimeCogUrls !== "function"
                    || !window.ForecastMap.hasLeadtimeCogUrls()) {
                return nu;
            }
            if (window.__leadtimeConfirmTimer) {
                clearTimeout(window.__leadtimeConfirmTimer);
                window.__leadtimeConfirmTimer = null;
            }
            window.dash_clientside.set_props("leadtime-confirm", {
                data: {lead: lead, ts: Date.now()},
            });
            return nu;
        }
        """,
        Output("map-bridge-tick", "data", allow_duplicate=True),
        Input("leadtime-playing", "data"),
        State("leadtime-slider", "value"),
        prevent_initial_call=True,
    )

    # Leadtime transport / pace / keyboard (clientside for snappy playback).
    # Programmatic slider writes set window.__forecastTimelineProgrammatic so
    # pause-on-scrub does not immediately cancel play/interval advances.
    app.clientside_callback(
        """
        function(n, playing, bounds, sliderMin, sliderMax, value) {
            var nu = window.dash_clientside.no_update;
            if (!playing) {
                return [nu, nu, true];
            }
            var min = (bounds && bounds.min != null) ? Number(bounds.min)
                : (sliderMin != null ? Number(sliderMin) : 0);
            var max = (bounds && bounds.max != null) ? Number(bounds.max)
                : (sliderMax != null ? Number(sliderMax) : 0);
            var current = (value == null) ? min : Number(value);
            if (!(max > min)) {
                return [nu, false, true];
            }
            if (current >= max) {
                return [nu, false, true];
            }
            // Hold the frame until the active map reports forecast tiles loaded.
            if (window.ForecastMap && window.ForecastMap.isTilesReady
                    && !window.ForecastMap.isTilesReady()) {
                return [nu, true, false];
            }
            // Do not outrun an overlay swap that is still fading in.
            if (window.ForecastMapOpenLayers
                    && typeof window.ForecastMapOpenLayers.hasPendingSwap === "function"
                    && window.ForecastMapOpenLayers.hasPendingSwap()) {
                return [nu, true, false];
            }
            if (window.ForecastMapCesium
                    && typeof window.ForecastMapCesium.hasPendingSwap === "function"
                    && window.ForecastMapCesium.hasPendingSwap()) {
                return [nu, true, false];
            }
            window.__forecastTimelineProgrammatic = true;
            if (window.ForecastMap && window.ForecastMap.setTilesReady) {
                window.ForecastMap.setTilesReady(false);
            }
            return [current + 1, true, false];
        }
        """,
        Output("leadtime-slider", "value", allow_duplicate=True),
        Output("leadtime-playing", "data", allow_duplicate=True),
        Output("leadtime-play-interval", "disabled", allow_duplicate=True),
        Input("leadtime-play-interval", "n_intervals"),
        State("leadtime-playing", "data"),
        State("leadtime-bounds", "data"),
        State("leadtime-slider", "min"),
        State("leadtime-slider", "max"),
        State("leadtime-slider", "value"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(playClicks, firstClicks, prevClicks, nextClicks, lastClicks, playing, bounds, sliderMin, sliderMax, value) {
            var nu = window.dash_clientside.no_update;
            var triggered = window.dash_clientside.callback_context.triggered_id;
            var min = (bounds && bounds.min != null) ? Number(bounds.min)
                : (sliderMin != null ? Number(sliderMin) : 0);
            var max = (bounds && bounds.max != null) ? Number(bounds.max)
                : (sliderMax != null ? Number(sliderMax) : 0);
            var current = (value == null) ? min : Number(value);
            var nextValue = current;
            var nextPlaying = !!playing;

            if (triggered === "leadtime-play") {
                nextPlaying = !playing;
                if (nextPlaying && current >= max) {
                    nextValue = min;
                }
                // Single-frame forecasts have nothing to animate.
                if (nextPlaying && !(max > min)) {
                    nextPlaying = false;
                }
            } else if (triggered === "leadtime-first") {
                nextValue = min;
                nextPlaying = false;
            } else if (triggered === "leadtime-prev") {
                nextValue = Math.max(min, current - 1);
                nextPlaying = false;
            } else if (triggered === "leadtime-next") {
                nextValue = Math.min(max, current + 1);
                nextPlaying = false;
            } else if (triggered === "leadtime-last") {
                nextValue = max;
                nextPlaying = false;
            }

            var valueOut = nu;
            if (nextValue !== current) {
                window.__forecastTimelineProgrammatic = true;
                if (window.ForecastMap && window.ForecastMap.setTilesReady) {
                    window.ForecastMap.setTilesReady(false);
                }
                valueOut = nextValue;
            }
            return [valueOut, nextPlaying, !nextPlaying];
        }
        """,
        Output("leadtime-slider", "value", allow_duplicate=True),
        Output("leadtime-playing", "data"),
        Output("leadtime-play-interval", "disabled"),
        Input("leadtime-play", "n_clicks"),
        Input("leadtime-first", "n_clicks"),
        Input("leadtime-prev", "n_clicks"),
        Input("leadtime-next", "n_clicks"),
        Input("leadtime-last", "n_clicks"),
        State("leadtime-playing", "data"),
        State("leadtime-bounds", "data"),
        State("leadtime-slider", "min"),
        State("leadtime-slider", "max"),
        State("leadtime-slider", "value"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(value, playing) {
            var nu = window.dash_clientside.no_update;
            if (window.__forecastTimelineProgrammatic) {
                window.__forecastTimelineProgrammatic = false;
                return [nu, nu];
            }
            if (!playing) {
                return [nu, nu];
            }
            return [false, true];
        }
        """,
        Output("leadtime-playing", "data", allow_duplicate=True),
        Output("leadtime-play-interval", "disabled", allow_duplicate=True),
        Input("leadtime-slider", "value"),
        State("leadtime-playing", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(playing) {
            var on = !!playing;
            var icon = on ? "tabler:player-pause" : "tabler:player-play";
            var cls = "forecast-timeline__btn forecast-timeline__btn--play";
            if (on) {
                cls += " is-playing";
            }
            return [icon, cls];
        }
        """,
        Output("leadtime-play-icon", "icon"),
        Output("leadtime-play", "className"),
        Input("leadtime-playing", "data"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(_) {
            if (window.__forecastTimelineKeysBound) {
                return window.dash_clientside.no_update;
            }
            window.__forecastTimelineKeysBound = true;
            window.addEventListener("keydown", function (event) {
                if (window.ForecastTimelineKeys && window.ForecastTimelineKeys.isEditableTarget(event.target)) {
                    return;
                }
                var key = event.key;
                if (key !== " " && key !== "ArrowLeft" && key !== "ArrowRight" && key !== "Home" && key !== "End") {
                    return;
                }
                event.preventDefault();
                var btnId = null;
                if (key === " ") {
                    btnId = "leadtime-play";
                } else if (key === "ArrowLeft") {
                    btnId = "leadtime-prev";
                } else if (key === "ArrowRight") {
                    btnId = "leadtime-next";
                } else if (key === "Home") {
                    btnId = "leadtime-first";
                } else if (key === "End") {
                    btnId = "leadtime-last";
                }
                var btn = btnId && document.getElementById(btnId);
                if (btn) {
                    btn.click();
                }
            });
            return window.dash_clientside.no_update;
        }
        """,
        Output("leadtime-keys-bound", "data"),
        Input("page-load-trigger", "data"),
        prevent_initial_call=False,
    )

    @app.callback(
        Output("collections-dropdown", "options"),
        Output("collections-dropdown", "value"),
        Output("forecast-busy", "className", allow_duplicate=True),
        Input("page-load-trigger", "data"),
        State("user-prefs", "data"),
        # Must run on load: page-load-trigger is already True in the layout, so
        # prevent_initial_call=True would skip the only invocation and leave
        # the dropdown empty. initial_duplicate keeps the busy Output legal.
        prevent_initial_call="initial_duplicate",
    )
    def update_collections(_, user_prefs):
        stac = _get_stac_client()
        # Ids only. The selected Collection (with summaries) is loaded
        # when the date picker asks for forecast inits.
        collection_ids = stac.get_catalog_collection_ids()
        options = [
            {"label": collection_id, "value": collection_id}
            for collection_id in collection_ids
        ]
        valid_ids = set(collection_ids)
        preferred = preferred_collections(user_prefs, valid_ids)
        # None / empty: leave the multi-select cleared (factory / stale prefs).
        value = preferred if preferred else None
        return options, value, _BUSY_HIDDEN

    @app.callback(
        Output("colormap-dropdown", "value"),
        Output("display-style", "data", allow_duplicate=True),
        Input("page-load-trigger", "data"),
        State("user-prefs", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def apply_style_prefs(_, user_prefs):
        """Seed colormap and locked colour range from browser prefs on load."""
        colormap = preferred_in(user_prefs, "colormap", AVAILABLE_COLORMAPS)
        style_seed = display_style_seed_from_prefs(user_prefs)
        colormap_out = colormap if colormap else no_update
        style_out = style_seed if style_seed is not None else no_update
        if colormap_out is no_update and style_out is no_update:
            raise PreventUpdate
        return colormap_out, style_out

    @app.callback(
        Output("map-view-mode", "options"),
        Output("map-view-presets", "data"),
        Output("map-view-mode", "value", allow_duplicate=True),
        Input("page-load-trigger", "data"),
        State("user-prefs", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def update_map_view_mode_options(_, user_prefs):
        """Populate Global / Leaflet / Globe + custom EPSG#### views."""
        options = list_view_mode_options(TILER_INTERNAL_URL)
        presets = list_view_mode_presets(TILER_INTERNAL_URL)
        preferred = preferred_in(
            user_prefs, "view_mode", {opt["value"] for opt in options}
        )
        return options, presets, preferred if preferred is not None else no_update

    @app.callback(
        Output("basemap-style", "value"),
        Input("page-load-trigger", "data"),
        State("user-prefs", "data"),
        prevent_initial_call="initial_duplicate",
    )
    def apply_basemap_prefs(_, user_prefs):
        """Seed the basemap control from browser prefs on load."""
        preferred = preferred_in(
            user_prefs,
            "basemap",
            {opt["value"] for opt in list_basemap_options()},
        )
        if preferred is None:
            raise PreventUpdate
        return preferred

    @app.callback(
        Output("map-state", "data", allow_duplicate=True),
        Output("map-base-layer", "url"),
        Output("map-base-layer", "attribution"),
        Input("basemap-style", "value"),
        State("map-state", "data"),
        State("map-view-mode", "value"),
        prevent_initial_call=True,
    )
    def apply_basemap_choice(basemap_id, map_state, map_view_mode):
        """
        Swap the XYZ basemap without rebuilding forecast tiles.

        Engine / projection come from the live view-mode control, not only
        ``map-state``. Optimistic Globe/TMS switches update that control (and
        the client) before Python finishes painting; republishing a stale
        Global OpenLayers ``map-state`` here used to flatten the map.
        """
        descriptor = basemap_descriptor(basemap_id)
        previous = map_state if isinstance(map_state, dict) else initial_map_state()
        if (previous.get("basemap") or {}).get("url") == descriptor["url"]:
            raise PreventUpdate

        ui_mode = (
            map_view_mode
            or previous.get("mode")
            or MapViewMode.GLOBAL_3857.value
        )
        mode, view_hint = view_mode_and_hint(ui_mode, TILER_INTERNAL_URL)
        engine = resolve_engine_for_mode(mode)
        # Keep the current framing when we are already on this mode/engine.
        if (
            previous.get("mode") == mode
            and previous.get("engine") == engine
            and isinstance(previous.get("view"), dict)
        ):
            view = previous["view"]
        else:
            view = view_hint

        next_state = build_map_state(
            previous=previous,
            engine=engine,
            mode=mode,
            layers=previous.get("layers") or [],
            view=view,
            basemap=descriptor,
            prefetch_layers=previous.get("prefetchLayers") or [],
        )
        return next_state, descriptor["url"], descriptor["attribution"]

    @app.callback(
        [
            Output("forecast-dates-store", "data"),
            Output("forecast-init-date-picker", "minDate"),
            Output("forecast-init-date-picker", "maxDate"),
            Output("forecast-init-date-picker", "defaultDate"),
            Output("forecast-init-date-picker", "disabledDates"),
            Output("forecast-init-date-picker", "value"),
            Output("forecast-busy", "className", allow_duplicate=True),
        ],
        [
            Input("page-load-trigger", "data"),
            Input("collections-dropdown", "value"),
        ],
        State("user-prefs", "data"),
        State("forecast-init-date-picker", "value"),
        prevent_initial_call=True,
    )
    def update_forecast_start_dates(
        _, collection_ids: list, user_prefs, current_date
    ) -> list:
        """
        Load available forecast init dates from STAC for the selected collections.

        Prefer inits already primed from Collection summaries at dropdown
        load; otherwise list_forecast_inits falls back to a slim Item Search.
        The picker is given those init days only, not every gap in the
        calendar range. Seed from browser prefs when possible, otherwise
        the latest available init so the leadtime axis can activate.
        """
        if not collection_ids:
            return [None, None, None, None, None, None, _BUSY_HIDDEN]

        stac = _get_stac_client()
        all_forecast_dates: set[datetime] = set()
        # Calendar day YYYY-MM-DD to forecast end calendar day YYYY-MM-DD
        forecast_dates_dict: dict[str, str] = {}

        for collection_id in collection_ids:
            try:
                for row in stac.list_forecast_inits(collection_id):
                    init_dt = row["datetime"]
                    end_day = _end_calendar_day_from_init(row)
                    if end_day is None:
                        logging.warning(
                            "No end date for %s init %s", collection_id, init_dt
                        )
                        continue

                    all_forecast_dates.add(init_dt)
                    day_key = to_calendar_day(init_dt)
                    # Keep the latest end date when several collections share a day
                    previous = forecast_dates_dict.get(day_key)
                    if previous is None or end_day > previous:
                        forecast_dates_dict[day_key] = end_day
            except Exception as e:
                logging.error(
                    "Failed to retrieve forecast dates for %s: %s", collection_id, e
                )

        if not all_forecast_dates:
            logging.debug("No forecast dates loaded from any selected collection.")
            return [None, None, None, None, None, None, _BUSY_HIDDEN]

        sorted_dates = sorted(all_forecast_dates)
        # Date picker and store keys use calendar days (YYYY-MM-DD) only.
        min_date = to_calendar_day(sorted_dates[0])
        max_date = to_calendar_day(sorted_dates[-1])
        initial_visible_month = max_date

        logging.debug(
            "Available forecast start dates from %s to %s", min_date, max_date
        )

        preferred_day = preferred_in(user_prefs, "forecast_start", forecast_dates_dict)
        current_ok = (
            isinstance(current_date, str) and current_date in forecast_dates_dict
        )
        if current_ok:
            date_value = no_update
        elif preferred_day is not None:
            date_value = preferred_day
        else:
            # No valid selection yet (first load, or stale day after collection
            # change). Seed the latest init so the leadtime axis can activate.
            date_value = max_date

        return [
            forecast_dates_dict,
            min_date,
            max_date,
            initial_visible_month,
            forecast_init_disabled_dates(forecast_dates_dict),
            date_value,
            _BUSY_HIDDEN,
        ]

    @app.callback(
        Output("time-slider-div", "className"),
        Output("selected-time", "children"),
        Output("leadtime-step-subtitle", "children"),
        Output("leadtime-slider", "min"),
        Output("leadtime-slider", "max"),
        Output("leadtime-slider", "marks"),
        Output("leadtime-slider", "value"),
        Output("leadtime-bounds", "data"),
        Output("leadtime-step-unit", "data"),
        Output("leadtime-playing", "data", allow_duplicate=True),
        Output("leadtime-play-interval", "disabled", allow_duplicate=True),
        Input("window-width", "data"),
        Input("forecast-init-date-picker", "value"),
        Input("leadtime-slider", "value"),
        Input("controls-open", "data"),
        Input("leadtime-axis", "data"),
        State("forecast-dates-store", "data"),
        prevent_initial_call=True,
    )
    def update_leadtime_slider(
        window_width,
        selected_date: str,
        leadtime: int,
        controls_open,
        leadtime_axis: dict,
        forecast_dates: dict,
    ):
        """
        Drive the scrubber from STAC COG valid times (``leadtime-axis``).

        ``forecast-dates-store`` only gates whether an init is selected; lead
        count and spacing come from ordered asset valid times.
        """
        idle = "forecast-timeline forecast-chrome forecast-timeline--idle"
        active = "forecast-timeline forecast-chrome"
        triggered = callback_context.triggered_id

        axis_times = (leadtime_axis or {}).get("times") or []
        step_unit = (leadtime_axis or {}).get("step_unit") or "day"

        if (
            not forecast_dates
            or not selected_date
            or selected_date not in forecast_dates
            or not axis_times
        ):
            return (
                idle,
                "Select a forecast start",
                "",
                0,
                1,
                [],
                0,
                {"min": 0, "max": 0},
                step_unit,
                False,
                True,
            )

        leadtime_min = 0
        leadtime_max = len(axis_times) - 1
        leadtimes = list(range(len(axis_times)))

        # Mark density tracks the map face, not the full window (sidebar
        # push layout deducts the open controls column below the drawer bp).
        width = _map_face_width(window_width, controls_open)
        desired_marks = max(2, width // 100)
        step = max(1, math.ceil(len(leadtimes) / desired_marks))

        marks = []
        for idx in leadtimes[::step]:
            try:
                valid_dt = parse_stac_datetime(axis_times[idx])
            except (TypeError, ValueError):
                continue
            marks.append(
                {
                    "value": idx,
                    "label": format_slider_label(valid_dt, step_unit=step_unit),
                }
            )

        if triggered == "forecast-init-date-picker" or triggered == "leadtime-axis":
            next_value = 0
            pause = True
            value_out = next_value
        elif triggered == "leadtime-slider":
            current = 0 if leadtime is None else int(leadtime)
            next_value = max(leadtime_min, min(current, leadtime_max))
            pause = False
            # Avoid rewriting the scrubber on its own Input - that re-triggers
            # pause-on-scrub and cancels playback after each Interval tick.
            value_out = no_update if next_value == current else next_value
        else:
            # window-width / controls-open: refresh marks only unless clamped.
            current = 0 if leadtime is None else int(leadtime)
            next_value = max(leadtime_min, min(current, leadtime_max))
            pause = False
            value_out = no_update if next_value == current else next_value

        try:
            valid_dt = parse_stac_datetime(axis_times[next_value])
            valid = format_valid_time(valid_dt, step_unit=step_unit)
        except (TypeError, ValueError, IndexError):
            valid = "Invalid leadtime"
        subtitle = step_unit_subtitle(step_unit)
        bounds = {"min": leadtime_min, "max": leadtime_max}

        if pause:
            return (
                active,
                valid,
                subtitle,
                leadtime_min,
                leadtime_max,
                marks,
                value_out,
                bounds,
                step_unit,
                False,
                True,
            )
        # Slider ticks (play/scrub): only refresh the valid-time label. Rewriting
        # marks/min/max every Interval step re-renders the scrubber and fights
        # the soft-swap, which looks like tile flicker.
        if triggered == "leadtime-slider":
            return (
                active,
                valid,
                no_update,
                no_update,
                no_update,
                no_update,
                value_out,
                no_update,
                no_update,
                no_update,
                no_update,
            )
        return (
            active,
            valid,
            subtitle,
            leadtime_min,
            leadtime_max,
            marks,
            value_out,
            bounds,
            step_unit,
            no_update,
            no_update,
        )

    @app.callback(
        Output("map-request", "data"),
        Input("leadtime-confirm", "data"),
        State("colormap-dropdown", "value"),
        State("display-style", "data"),
        State("map-request", "data"),
        State("leadtime-slider", "value"),
        State("map-view-mode", "value"),
        prevent_initial_call=True,
    )
    def publish_map_request(
        leadtime_confirm,
        colormap,
        display_style,
        previous_request,
        leadtime_slider,
        map_view_mode,
    ):
        """Record the settled leadtime on ``map-request`` (Reset still clears it)."""
        prev = previous_request if isinstance(previous_request, dict) else None
        if not prev or not isinstance(leadtime_confirm, dict):
            raise PreventUpdate
        if leadtime_confirm.get("lead") is not None:
            lead = leadtime_confirm["lead"]
        else:
            lead = (
                leadtime_slider
                if leadtime_slider is not None
                else prev.get("lead", 0)
            )
        style_cmap = normalise_display_style(display_style).get("colormap")
        return build_map_request(
            prev,
            collection=prev["collection"],
            forecast_start=prev["forecast_start"],
            variable=prev["variable"],
            colormap=resolve_live_colormap(
                colormap,
                style_cmap,
                prev.get("colormap"),
            ),
            view_mode=map_view_mode or prev.get("view_mode"),
            lead=lead,
            force_stats=False,
            clear_lock=False,
            leadtime_only=not bool(leadtime_confirm.get("force")),
        )

    @app.callback(
        Output("map-state", "data"),
        Output("cog-results-layer", "children"),
        Output("display-style", "data"),
        Output("map-view-mode", "value"),
        Input("map-request", "data"),
        State("map-state", "data"),
        prevent_initial_call=True,
    )
    def update_cog_layer(
        map_request,
        map_state,
    ):
        """
        Clear overlays when ``map-request`` is cleared.

        Item tiles are painted in the browser from ``/api/search``. This
        callback must not load the same Item or overwrite ``map-state``.
        """
        if not isinstance(map_request, dict):
            if not (map_state or {}).get("layers"):
                raise PreventUpdate
            logging.debug("map-request cleared; removing overlays")
            cleared = build_map_state(
                previous=map_state,
                engine=(map_state or {}).get("engine")
                or MapEngine.OPENLAYERS.value,
                mode=(map_state or {}).get("mode")
                or MapViewMode.GLOBAL_3857.value,
                layers=[],
                view=(map_state or {}).get("view"),
                leadtime_cog_urls=None,
                lead=None,
            )
            return cleared, [], no_update, no_update

        return no_update, no_update, no_update, no_update

    @app.callback(
        Output("map-state", "data", allow_duplicate=True),
        Output("cog-results-layer", "children", allow_duplicate=True),
        Input("display-style", "data"),
        State("map-state", "data"),
        prevent_initial_call=True,
    )
    def apply_locked_display_style(display_style, map_state):
        """
        Rewrite tile URLs on the current layers when a pinned range changes.

        Runs after the clientside pin callbacks write a locked colormap or
        min/max onto ``display-style``. Only rewrites query parameters on
        existing tile URLs; it never re-queries STAC or TiTiler statistics.
        """
        style = normalise_display_style(display_style)
        if not style.get("locked"):
            raise PreventUpdate

        layers = (map_state or {}).get("layers") or []
        if not layers:
            raise PreventUpdate

        rescale = (style["vmin"], style["vmax"])
        rewritten = rewrite_layer_entries_style(
            layers, colormap=style.get("colormap"), rescale=rescale
        )
        if rewritten is None:
            raise PreventUpdate

        build_kwargs = {}
        leadtime_cog_urls = (map_state or {}).get("leadtimeCogUrls")
        rewritten_cog_urls = rewrite_leadtime_cog_urls_style(
            leadtime_cog_urls, colormap=style.get("colormap"), rescale=rescale
        )
        if rewritten_cog_urls is not None:
            build_kwargs["leadtime_cog_urls"] = rewritten_cog_urls

        engine = (map_state or {}).get("engine")
        next_state = build_map_state(
            previous=map_state,
            engine=engine,
            mode=(map_state or {}).get("mode"),
            layers=rewritten,
            view=(map_state or {}).get("view"),
            **build_kwargs,
        )
        leaflet_children = (
            _build_leaflet_overlays(rewritten)
            if engine == MapEngine.LEAFLET_LEGACY.value
            else []
        )
        return next_state, leaflet_children

    @app.callback(
        Output("cog-results-layer", "children", allow_duplicate=True),
        Input("map-state", "data"),
        State("cog-results-layer", "children"),
        prevent_initial_call=True,
    )
    def sync_leaflet_overlays(map_state, current_children):
        """
        Build Leaflet Overlay children from published ``map-state``.

        Same layer count keeps the existing TileLayers so play can swap
        URLs in place. Count or engine changes rebuild or clear.
        """
        if not isinstance(map_state, dict):
            raise PreventUpdate
        if map_state.get("engine") != MapEngine.LEAFLET_LEGACY.value:
            if current_children:
                return []
            raise PreventUpdate
        layers = map_state.get("layers") or []
        if not layers:
            if current_children:
                return []
            raise PreventUpdate
        n = len(current_children) if current_children else 0
        if n == len(layers):
            raise PreventUpdate
        return _build_leaflet_overlays(layers)

    @app.callback(
        Output("controls-column", "className"),
        Output("controls-open", "data"),
        Output("controls-seam-icon", "icon"),
        Input("controls-seam", "n_clicks"),
        State("controls-open", "data"),
        prevent_initial_call=True,
    )
    def toggle_main_controller(_seam, is_open):
        """Toggle forecast controls (push column on desktop, overlay drawer ≤900px)."""
        opened = not bool(is_open)
        base = "forecast-controls-column"
        class_name = base if opened else f"{base} forecast-controls-column--collapsed"
        icon = "tabler:chevron-right" if opened else "tabler:chevron-left"
        return class_name, opened, icon

    @app.callback(
        Output("user-prefs", "data"),
        Input("collections-dropdown", "value"),
        Input("forecast-init-date-picker", "value"),
        Input("variable-dropdown", "value"),
        Input("colormap-dropdown", "value"),
        Input("map-view-mode", "value"),
        Input("basemap-style", "value"),
        Input("display-style", "data"),
        prevent_initial_call=True,
    )
    def save_user_prefs(
        collection_ids,
        forecast_start,
        variable,
        colormap,
        view_mode,
        basemap_id,
        display_style,
    ):
        """Persist live control choices to localStorage via ``user-prefs``."""
        return merge_user_prefs(
            collection=collection_ids,
            forecast_start=forecast_start,
            variable=variable,
            colormap=colormap,
            view_mode=view_mode,
            basemap=basemap_id,
            display_style=display_style,
        )

    @app.callback(
        Output("user-prefs-reset", "disabled"),
        Input("collections-dropdown", "value"),
        Input("forecast-init-date-picker", "value"),
        Input("variable-dropdown", "value"),
        Input("colormap-dropdown", "value"),
        Input("map-view-mode", "value"),
        Input("basemap-style", "value"),
        Input("display-style", "data"),
        Input("user-prefs", "data"),
        prevent_initial_call=False,
    )
    def project_reset_defaults_disabled(
        collection_ids,
        forecast_start,
        variable,
        colormap,
        view_mode,
        basemap_id,
        display_style,
        user_prefs,
    ):
        """Disable Reset when live controls and storage already match factory."""
        live = merge_user_prefs(
            collection=collection_ids,
            forecast_start=forecast_start,
            variable=variable,
            colormap=colormap,
            view_mode=view_mode,
            basemap=basemap_id,
            display_style=display_style,
        )
        # Prefer listening to user-prefs as Input (not State): after Reset clears
        # storage, this must re-run with the empty store or the button stays on.
        stored = bool(normalise_user_prefs(user_prefs))
        return live is None and not stored

    @app.callback(
        Output("user-prefs", "data", allow_duplicate=True),
        Output("collections-dropdown", "value", allow_duplicate=True),
        Output("colormap-dropdown", "value", allow_duplicate=True),
        Output("map-view-mode", "value", allow_duplicate=True),
        Output("basemap-style", "value", allow_duplicate=True),
        Output("display-style", "data", allow_duplicate=True),
        Output("map-request", "data", allow_duplicate=True),
        Output("map-state", "data", allow_duplicate=True),
        Output("map-base-layer", "url", allow_duplicate=True),
        Output("map-base-layer", "attribution", allow_duplicate=True),
        Output("cog-results-layer", "children", allow_duplicate=True),
        Input("user-prefs-reset", "n_clicks"),
        prevent_initial_call=True,
    )
    def reset_user_prefs(_n_clicks):
        """Clear saved prefs and restore factory controls in the live session."""
        if not _n_clicks:
            raise PreventUpdate
        factory_basemap = basemap_descriptor(DEFAULT_BASEMAP_ID)
        # Clearing collection cascades date/variable via existing STAC callbacks.
        return (
            None,
            None,
            DEFAULT_COLORMAP,
            DEFAULT_VIEW_MODE,
            DEFAULT_BASEMAP_ID,
            dict(DEFAULT_DISPLAY_STYLE),
            None,
            initial_map_state(),
            factory_basemap["url"],
            factory_basemap["attribution"],
            [],
        )

    @app.callback(
        Output("fixed-min", "value"),
        Output("fixed-max", "value"),
        Output("colorbar-range-reset", "disabled"),
        Output("forecast-cbar-ramp", "style"),
        Output("colorbar-range-slider", "value"),
        Output("colorbar-range-slider", "min"),
        Output("colorbar-range-slider", "max"),
        Output("colorbar-range-slider", "step"),
        Output("colorbar-range-slider-wrap", "style"),
        Input("display-style", "data"),
        prevent_initial_call=False,
    )
    def project_display_style(display_style):
        """
        Drive the timeline colourbar and range controls from display-style.

        display-style is the single source of truth for colour range. This
        callback only reads it and updates the visible min/max text, the
        ramp gradient, and the range slider; it never writes back to
        display-style.
        """
        style = normalise_display_style(display_style)
        locked = bool(style["locked"])
        vmin = round_2dp(style["vmin"])
        vmax = round_2dp(style["vmax"])
        dmin = round_2dp(style["domain_min"])
        dmax = round_2dp(style["domain_max"])
        ramp = cbar_ramp_style(style.get("colormap"))
        gradient = ramp.get("background")
        return (
            str(vmin),
            str(vmax),
            # Auto reset is only useful once the user has pinned a range.
            not locked,
            ramp,
            [vmin, vmax],
            dmin,
            dmax,
            cbar_slider_step(dmin, dmax),
            {"--cbar-gradient": gradient} if gradient else {},
        )

    @app.callback(
        Output("colorbar-range-popover", "opened"),
        Input("colorbar-range-reset", "n_clicks"),
        prevent_initial_call=True,
    )
    def close_colorbar_range_popover(_reset_clicks):
        """Close the colour-range popover after the Auto button is pressed."""
        return False

    @app.callback(
        Output("display-style", "data", allow_duplicate=True),
        Output("map-style-refresh", "data"),
        Input("colorbar-range-reset", "n_clicks"),
        State("display-style", "data"),
        prevent_initial_call=True,
    )
    def reset_colorbar_range(_reset_clicks, display_style):
        """Unlock the colour range and force a fresh statistics rebuild."""
        style = normalise_display_style(display_style)
        if not style.get("locked"):
            raise PreventUpdate
        style["locked"] = False
        style["source"] = "stats"
        return style, {"ts": time.time()}

    # Typing a fixed min/max, or picking a colormap while locked, pins the
    # colour range. publish_map_request skips locked colormap edits; the
    # apply_locked_display_style Python callback rewrites tile URLs.
    app.clientside_callback(
        """
        function(colormap, vmin, vmax, style) {
            var nu = window.dash_clientside.no_update;
            if (!style) {
                return nu;
            }
            var nextVmin = (vmin == null || vmin === "") ? style.vmin : Number(vmin);
            var nextVmax = (vmax == null || vmax === "") ? style.vmax : Number(vmax);
            if (!isFinite(nextVmin) || !isFinite(nextVmax)) {
                return nu;
            }
            if (nextVmax < nextVmin) {
                var swap = nextVmin;
                nextVmin = nextVmax;
                nextVmax = swap;
            }
            var nextCmap = colormap || style.colormap || "blues_r";
            var nearly = function (a, b) {
                return Math.abs(Number(a) - Number(b)) < 1e-9;
            };
            var rangeChanged =
                !nearly(nextVmin, style.vmin) || !nearly(nextVmax, style.vmax);
            var cmapChanged = nextCmap !== style.colormap;
            // Typing min/max pins the range. Colormap alone only rewrites tiles
            // when the range is already pinned.
            if (!rangeChanged && !cmapChanged) {
                return nu;
            }
            if (!rangeChanged && !style.locked) {
                return nu;
            }
            var domainMin = Number(style.domain_min);
            var domainMax = Number(style.domain_max);
            if (!isFinite(domainMin)) domainMin = nextVmin;
            if (!isFinite(domainMax)) domainMax = nextVmax;
            var nextStyle = Object.assign({}, style, {
                colormap: nextCmap,
                vmin: nextVmin,
                vmax: nextVmax,
                domain_min: Math.min(domainMin, nextVmin),
                domain_max: Math.max(domainMax, nextVmax),
                locked: true,
                source: "user",
            });
            return nextStyle;
        }
        """,
        Output("display-style", "data", allow_duplicate=True),
        Input("colormap-dropdown", "value"),
        Input("fixed-min", "value"),
        Input("fixed-max", "value"),
        State("display-style", "data"),
        prevent_initial_call=True,
    )

    # Dragging the range slider also pins the colour range.
    app.clientside_callback(
        """
        function(range, style) {
            var nu = window.dash_clientside.no_update;
            if (!style || !range || range.length < 2) {
                return nu;
            }
            var nextVmin = Number(range[0]);
            var nextVmax = Number(range[1]);
            if (!isFinite(nextVmin) || !isFinite(nextVmax)) {
                return nu;
            }
            if (nextVmax < nextVmin) {
                var swap = nextVmin;
                nextVmin = nextVmax;
                nextVmax = swap;
            }
            var nearly = function (a, b) {
                return Math.abs(Number(a) - Number(b)) < 1e-9;
            };
            if (nearly(nextVmin, style.vmin) && nearly(nextVmax, style.vmax) && style.locked) {
                return nu;
            }
            if (nearly(nextVmin, style.vmin) && nearly(nextVmax, style.vmax) && !style.locked) {
                // Opening/projecting the slider should not pin until the user moves it.
                return nu;
            }
            var domainMin = Number(style.domain_min);
            var domainMax = Number(style.domain_max);
            if (!isFinite(domainMin)) domainMin = nextVmin;
            if (!isFinite(domainMax)) domainMax = nextVmax;
            var nextStyle = Object.assign({}, style, {
                vmin: nextVmin,
                vmax: nextVmax,
                domain_min: Math.min(domainMin, nextVmin),
                domain_max: Math.max(domainMax, nextVmax),
                locked: true,
                source: "user",
            });
            return nextStyle;
        }
        """,
        Output("display-style", "data", allow_duplicate=True),
        Input("colorbar-range-slider", "value"),
        State("display-style", "data"),
        prevent_initial_call=True,
    )
