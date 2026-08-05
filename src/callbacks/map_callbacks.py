import logging
import math
import os
import time
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import urlparse, urlunparse

import dash
import dash_leaflet as dl
import pandas as pd
from components.controls import AVAILABLE_COLORMAPS, DEFAULT_COLORMAP
from config import (
    FILE_SERVER_INTERNAL_URL,
    FILE_SERVER_URL,
    STAC_FASTAPI_URL,
    TILER_INTERNAL_URL,
    TILER_URL,
)
from dash import Input, Output, State, callback_context, no_update
from dash.exceptions import PreventUpdate
from pystac import Asset
from stac.process import STAC
from stac.timefmt import (
    date_picker_to_reference_time,
    format_slider_label,
    format_valid_time,
    parse_calendar_day,
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
    WEB_MERCATOR_QUAD,
    DEFAULT_BASEMAP_ID,
    MapEngine,
    MapViewMode,
    basemap_descriptor,
    bbox_fits_view_mode,
    build_cog_tile_url,
    build_leadtime_cog_urls,
    build_map_request,
    build_map_state,
    collections_list,
    resolve_live_colormap,
    initial_map_state,
    layers_from_leadtime_cog_urls,
    leadtime_cog_urls_match_style,
    list_basemap_options,
    list_view_mode_options,
    list_view_mode_presets,
    resolve_mode_and_engine,
    resolve_engine_for_mode,
    rewrite_layer_entries_style,
    rewrite_layer_entries_tms,
    rewrite_leadtime_cog_urls_style,
    rewrite_leadtime_cog_urls_tms,
    tile_matrix_set_for_mode,
    to_tiler_asset_url,
    view_mode_and_hint,
)

from .display_style import (
    DEFAULT_DISPLAY_STYLE,
    cbar_ramp_style,
    cbar_slider_step,
    normalise_display_style,
)
from .utils import get_cog_band_statistics, round_2dp

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


def normalise_url_path(url: str) -> str:
    """
    Normalise the path part of a URL by resolving `.` and `..`.

    Args:
        url: The original URL.

    Returns:
        The normalised URL.
    """
    parts = urlparse(url)
    normalised_path = os.path.normpath(parts.path)

    # Preserve trailing slash if it was present in the original URL
    if parts.path.endswith("/") and not normalised_path.endswith("/"):
        normalised_path += "/"

    # Rebuild and return the normalised URL
    return urlunparse(parts._replace(path=normalised_path))


# Function to generate tile URL for a STAC Item
def get_tile_url(cog_path: str, tile_matrix_set: str = WEB_MERCATOR_QUAD) -> str:
    """
    Return the XYZ tile URL template for a COG asset href.

    Args:
        cog_path: Public STAC asset href for the COG. Rewritten for TiTiler fetch.
        tile_matrix_set: TiTiler tile matrix set id. Defaults to Web Mercator.

    Returns:
        TiTiler XYZ template URL with ``{z}``, ``{x}``, and ``{y}`` placeholders.
    """
    # Browser hits TILER_URL; TiTiler itself fetches `url=`, so that must be
    # reachable from the titiler container (file-server Docker DNS).
    return build_cog_tile_url(
        cog_path,
        tiler_url=TILER_URL,
        file_server_url=FILE_SERVER_URL,
        file_server_internal_url=FILE_SERVER_INTERNAL_URL,
        tile_matrix_set=tile_matrix_set,
    )


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


def _resolve_band_minmax(
    stac: STAC, asset: Asset, band_index: int, cog_href: str
) -> tuple[float, float]:
    """
    Prefer band STATISTICS_* on the STAC asset; fall back to TiTiler statistics.
    """
    rescale = stac.get_band_rescale(asset, band_index)
    if rescale is not None:
        return rescale

    tiler_cog = to_tiler_asset_url(cog_href, FILE_SERVER_URL, FILE_SERVER_INTERNAL_URL)
    band_stats = get_cog_band_statistics(
        TILER_INTERNAL_URL, cog_url=tiler_cog, band_index=band_index
    )
    return float(band_stats.get("min", 0)), float(band_stats.get("max", 1))


def _build_forecast_layer_entries(
    stac: STAC,
    collection_ids: list,
    forecast_reference_time_str: str,
    leadtime: int,
    band_index: int,
    colormap: str,
    min_val: float,
    max_val: float,
    tile_matrix_set: str = WEB_MERCATOR_QUAD,
    view_mode: str = MapViewMode.GLOBAL_3857.value,
) -> list[dict]:
    """
    Build shared forecast layer descriptors for map-state and Leaflet.

    Args:
        stac: Cached STAC client.
        collection_ids: Selected collection ids.
        forecast_reference_time_str: Forecast init as a STAC datetime string.
        leadtime: Leadtime index into COG assets.
        band_index: One-based band index for TiTiler.
        colormap: rio-tiler colormap name.
        min_val: Display rescale minimum.
        max_val: Display rescale maximum.
        tile_matrix_set: TiTiler tile matrix set id.
        view_mode: Active map view mode (filters unfit hemispheres).

    Returns:
        List of layer dicts with ``id``, ``title``, ``tileUrl``, ``opacity``,
        and ``visible``.
    """
    layers: list[dict] = []
    for collection_id in collection_ids or []:
        try:
            if not _collection_fits_view_mode(stac, collection_id, view_mode):
                logging.info(
                    "Skipping collection %s: does not fit view mode %s",
                    collection_id,
                    view_mode,
                )
                continue

            cogs = stac.get_item_cogs(collection_id, forecast_reference_time_str)
            cog_assets = list(cogs.values())

            if leadtime >= len(cog_assets):
                logging.warning(
                    "Leadtime %s out of range for %s", leadtime, collection_id
                )
                continue

            cog_asset = cog_assets[leadtime]
            tile_url = build_cog_tile_url(
                cog_asset.href,
                tiler_url=TILER_URL,
                file_server_url=FILE_SERVER_URL,
                file_server_internal_url=FILE_SERVER_INTERNAL_URL,
                tile_matrix_set=tile_matrix_set,
                colormap=colormap,
                rescale=(min_val, max_val),
                band_index=band_index,
            )
            logging.debug("tile_url: %s", tile_url)

            layers.append(
                {
                    "id": collection_id,
                    "title": collection_id,
                    "tileUrl": tile_url,
                    "opacity": 1,
                    "visible": True,
                }
            )
        except Exception as e:
            logging.error("Error processing collection %s: %s", collection_id, e)
            continue
    return layers


def _build_leadtime_cog_urls(
    stac: STAC,
    collection_ids: list,
    forecast_reference_time_str: str,
    band_index: int,
    colormap: str,
    min_val: float,
    max_val: float,
    tile_matrix_set: str,
    view_mode: str,
) -> dict | None:
    """
    Collect every leadtime COG URL for the current forecast and style.

    Published on map-state as ``leadtimeCogUrls`` so the browser can swap
    overlays while scrubbing or playing without a Python round trip.

    Args:
        stac: Cached STAC client.
        collection_ids: Selected collection ids.
        forecast_reference_time_str: Forecast init as a STAC datetime string.
        band_index: One-based band index for TiTiler.
        colormap: rio-tiler colormap name.
        min_val: Display rescale minimum.
        max_val: Display rescale maximum.
        tile_matrix_set: TiTiler tile matrix set id.
        view_mode: Active map view mode (filters unfit hemispheres).

    Returns:
        Payload for map-state, or None when no collection has COG assets.
    """
    hrefs_by_collection: dict[str, list[str]] = {}
    for collection_id in collection_ids or []:
        try:
            if not _collection_fits_view_mode(stac, collection_id, view_mode):
                continue
            cogs = stac.get_item_cogs(collection_id, forecast_reference_time_str)
            hrefs_by_collection[collection_id] = [
                to_tiler_asset_url(
                    asset.href, FILE_SERVER_URL, FILE_SERVER_INTERNAL_URL
                )
                for asset in cogs.values()
            ]
        except Exception as e:
            logging.error(
                "Error collecting leadtime COG URLs for %s: %s", collection_id, e
            )
            continue

    return build_leadtime_cog_urls(
        tiler_base=TILER_URL,
        tile_matrix_set=tile_matrix_set,
        hrefs_by_collection=hrefs_by_collection,
        colormap=colormap,
        rescale=(min_val, max_val),
        band_index=band_index,
        reference_time=forecast_reference_time_str,
    )


def _collection_fits_view_mode(
    stac: STAC, collection_id: str, view_mode: str
) -> bool:
    """Return whether a collection's spatial extent fits the map view mode."""
    try:
        _temporal, spatial_extent = stac.get_collection_extents(collection_id)
    except Exception as e:
        logging.debug(
            "Could not read extent for %s (%s); treating as a fit",
            collection_id,
            e,
        )
        return True
    return bbox_fits_view_mode(spatial_extent, view_mode)

def _build_leaflet_overlays(layer_entries: list[dict]) -> list:
    """Build Leaflet Overlay children from shared layer descriptors."""
    tile_layers = []
    for index, layer in enumerate(layer_entries):
        tile_layers.append(
            dl.Overlay(
                dl.TileLayer(
                    id={"type": "cog-collections", "index": index},
                    url=layer["tileUrl"],
                    zIndex=100,
                    opacity=layer.get("opacity", 1),
                ),
                name=layer.get("title") or layer["id"],
                checked=layer.get("visible", True),
            )
        )
    return tile_layers


def _build_tile_layers(
    stac: STAC,
    collection_ids: list,
    forecast_reference_time_str: str,
    leadtime: int,
    band_index: int,
    colormap: str,
    min_val: float,
    max_val: float,
) -> list:
    """Build Leaflet overlays for each selected collection at the given leadtime."""
    # Kept as a thin wrapper for call sites that still expect Overlay children.
    entries = _build_forecast_layer_entries(
        stac,
        collection_ids,
        forecast_reference_time_str,
        leadtime,
        band_index,
        colormap,
        min_val,
        max_val,
    )
    return _build_leaflet_overlays(entries)


# Callback function that will update the output container based on input
def register_callbacks(app: dash.Dash):
    """
    Registers Dash callbacks for updating COG layers and their opacities on the map.

    Args:
        The Dash app instance.
    """

    # # Get first `collection_id` for testing
    # collection_id = stac.get_catalog_collection_ids(resolve=True)[0].id

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
    # widening — leave the user's toggle choice alone.
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
                return [nu, nu];
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

    # A new forecast init makes the published COG URLs stale, so drop them
    # before the scrubber resets and asks for a swap.
    app.clientside_callback(
        """
        function(_date) {
            if (window.ForecastMap
                    && typeof window.ForecastMap.clearLeadtimeCogUrls === "function") {
                window.ForecastMap.clearLeadtimeCogUrls();
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("map-bridge-tick", "data", allow_duplicate=True),
        Input("forecast-init-date-picker", "value"),
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
                window.ForecastMap.applyLeadtimeIndex(lead);
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
        collections = stac.get_catalog_collection_ids(resolve=True)
        # Reuse summaries on these Collection objects for forecast inits
        # so selecting a collection does not GET /collections/{id} again.
        stac.cache_collections(collections)
        options = []
        for collection in collections:
            option = {"label": collection.id, "value": collection.id}
            options.append(option)
        valid_ids = {collection.id for collection in collections}
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
        Seed the picker from browser prefs when the current day is empty or
        no longer available.
        """
        if not collection_ids:
            return [None, None, None, None, None, None, _BUSY_HIDDEN]

        stac = _get_stac_client()
        all_forecast_dates: set[datetime] = set()
        # Calendar day YYYY-MM-DD -> forecast end calendar day YYYY-MM-DD
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

        # Calculate disabled dates
        date_range = pd.date_range(min_date, max_date)
        available_dates = {d.date() for d in sorted_dates}
        disabled_dates = [
            to_calendar_day(d) for d in date_range if d.date() not in available_dates
        ]

        preferred_day = preferred_in(user_prefs, "forecast_start", forecast_dates_dict)
        current_ok = (
            isinstance(current_date, str) and current_date in forecast_dates_dict
        )
        if current_ok:
            date_value = no_update
        elif preferred_day is not None:
            date_value = preferred_day
        elif current_date:
            # Stale day for this collection set; clear rather than leave disabled.
            date_value = None
        else:
            date_value = no_update

        return [
            forecast_dates_dict,
            min_date,
            max_date,
            initial_visible_month,
            disabled_dates,
            date_value,
            _BUSY_HIDDEN,
        ]

    @app.callback(
        Output("variable-dropdown", "options"),
        Output("variable-dropdown", "value"),
        Output("forecast-busy", "className", allow_duplicate=True),
        Output("forecast-busy-label", "children", allow_duplicate=True),
        Output("map-request", "data", allow_duplicate=True),
        Input("forecast-init-date-picker", "value"),
        Input("collections-dropdown", "value"),
        State("variable-dropdown", "value"),
        State("user-prefs", "data"),
        State("colormap-dropdown", "value"),
        State("map-view-mode", "value"),
        State("map-request", "data"),
        State("leadtime-slider", "value"),
        prevent_initial_call=True,
    )
    def update_available_variables(
        selected_date,
        collection_ids: list,
        current_value,
        user_prefs,
        colormap,
        map_view_mode,
        previous_request,
        leadtime_slider,
    ):
        """
        Fill the variable dropdown for the selected forecast date.

        Loads variable names through a light catalogue query so the list can
        appear without waiting for a full forecast download. Prefer a
        browser-saved band when it is still offered; otherwise keep the
        current choice when valid, or pick the first variable.

        Also emits ``map-request`` once the recipe is complete. Cascading
        programmatic writes to collection/date/variable Inputs are not a
        reliable paint trigger after prefs rehydration; writing the request
        here (where the resolved band is known) is.
        """
        if not selected_date or not collection_ids:
            # Collection-only: leave the dates busy banner alone (owned by
            # update_forecast_start_dates). Do not hide/show here.
            return [], None, no_update, no_update, no_update

        stac = _get_stac_client()
        forecast_reference_time_str = date_picker_to_reference_time(selected_date)
        combined_vars: dict[str, int] = {}

        for collection_id in collection_ids:
            try:
                available_vars = stac.list_forecast_bands(
                    collection_id, forecast_reference_time_str
                )
                for var_name, band_index in available_vars.items():
                    # Prefer the first collection that offers this name.
                    if var_name not in combined_vars:
                        combined_vars[var_name] = band_index
            except Exception as e:
                logging.warning(
                    "Error retrieving variables for %s: %s", collection_id, e
                )
                continue

        if not combined_vars:
            return [], None, _BUSY_HIDDEN, no_update, no_update

        options = [
            {"label": var_name, "value": band_index}
            for var_name, band_index in combined_vars.items()
        ]
        values = {opt["value"] for opt in options}
        preferred = preferred_in(user_prefs, "variable", values)
        if preferred is not None:
            value_out = preferred if preferred != current_value else no_update
        elif current_value in values:
            value_out = no_update
        else:
            value_out = options[0]["value"]

        resolved_band = (
            value_out if value_out is not no_update else current_value
        )
        if resolved_band not in values:
            resolved_band = None

        # Date change with an unchanged band still needs a paint (variable
        # Input may not fire). Seed the request from the resolved recipe.
        if resolved_band is None:
            request_out = no_update
        else:
            clear_lock = (
                previous_request is not None
                and isinstance(previous_request, dict)
                and previous_request.get("variable") != resolved_band
            )
            lead = 0
            if (
                isinstance(previous_request, dict)
                and previous_request.get("collection")
                == collections_list(collection_ids)
                and previous_request.get("forecast_start") == selected_date
                and previous_request.get("variable") == resolved_band
                and leadtime_slider is not None
            ):
                lead = leadtime_slider
            request_out = build_map_request(
                previous_request,
                collection=collection_ids,
                forecast_start=selected_date,
                variable=resolved_band,
                colormap=colormap,
                view_mode=map_view_mode,
                lead=lead,
                clear_lock=clear_lock,
            )
            logging.debug(
                "map-request from variables: collection=%s date=%s band=%s rev=%s",
                collection_ids,
                selected_date,
                resolved_band,
                (request_out or {}).get("revision"),
            )

        # Dropdown is ready; remaining wait is the map rebuild / tile paint.
        return options, value_out, "forecast-busy", "Updating map…", request_out

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
        State("forecast-dates-store", "data"),
        State("leadtime-step-unit", "data"),
        prevent_initial_call=True,
    )
    def update_leadtime_slider(
        window_width,
        selected_date: str,
        leadtime: int,
        controls_open,
        forecast_dates: dict,
        step_unit: str,
    ):
        """
        selected_date: Calendar day 'YYYY-MM-DD'.
        forecast_dates: Dict of calendar day -> forecast end calendar day.
        """
        idle = "forecast-timeline forecast-chrome forecast-timeline--idle"
        active = "forecast-timeline forecast-chrome"
        step_unit = step_unit or "day"
        triggered = callback_context.triggered_id

        if (
            not forecast_dates
            or not selected_date
            or selected_date not in forecast_dates
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

        forecast_start_date = parse_calendar_day(selected_date)
        forecast_end_date = parse_calendar_day(forecast_dates[selected_date])

        logging.info("forecast start date: %s", forecast_start_date)
        logging.info("forecast end date: %s", forecast_end_date)

        # leadtime_length end day is init+N; indices are 0..N-1.
        num_days = (forecast_end_date - forecast_start_date).days
        if num_days < 1:
            num_days = 1

        leadtime_min = 0
        leadtime_max = num_days - 1
        leadtimes = list(range(num_days))

        # Mark density tracks the map face, not the full window (sidebar
        # push layout deducts the open controls column below the drawer bp).
        width = _map_face_width(window_width, controls_open)
        desired_marks = max(2, width // 100)
        step = max(1, math.ceil(len(leadtimes) / desired_marks))

        marks = [
            {
                "value": idx,
                "label": format_slider_label(
                    forecast_start_date + timedelta(days=idx),
                    step_unit=step_unit,
                ),
            }
            for idx in leadtimes[::step]
        ]

        if triggered == "forecast-init-date-picker":
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

        valid = format_valid_time(
            forecast_start_date + timedelta(days=next_value),
            step_unit=step_unit,
        )
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
        Input("collections-dropdown", "value"),
        Input("forecast-init-date-picker", "value"),
        Input("variable-dropdown", "value"),
        Input("colormap-dropdown", "value"),
        Input("map-view-mode", "value"),
        Input("map-style-refresh", "data"),
        Input("leadtime-confirm", "data"),
        State("display-style", "data"),
        State("map-request", "data"),
        State("leadtime-slider", "value"),
        prevent_initial_call=True,
    )
    def publish_map_request(
        collection_ids,
        forecast_start,
        variable,
        colormap,
        map_view_mode,
        style_refresh,
        leadtime_confirm,
        display_style,
        previous_request,
        leadtime_slider,
    ):
        """
        Translate control changes into a single paint intent.

        Incomplete recipes clear the request (and thus the map). Locked
        colormap edits are left to ``apply_locked_display_style`` so this
        path does not fight the clientside pin callbacks.

        Leadtime confirms that carry ``force`` (init-day rewind) rebuild even
        while playing; routine confirms are marked ``leadtime_only`` so the
        painter can drop them mid-animation.
        """
        triggered = callback_context.triggered_id
        prev = previous_request if isinstance(previous_request, dict) else None

        # Locked colormap edits are applied once overlays exist.
        if triggered == "colormap-dropdown" and normalise_display_style(
            display_style
        ).get("locked"):
            raise PreventUpdate

        # Auto (map-style-refresh) forces a fresh unlocked statistics rebuild.
        force_stats = triggered == "map-style-refresh"
        leadtime_only = False
        lead = leadtime_slider if leadtime_slider is not None else 0
        cols = collections_list(collection_ids)

        if triggered == "leadtime-confirm":
            if not prev or not isinstance(leadtime_confirm, dict):
                raise PreventUpdate
            if leadtime_confirm.get("lead") is not None:
                lead = leadtime_confirm["lead"]
            else:
                lead = prev.get("lead", 0)
            # force=True: update_leadtime_slider rewound for a new init.
            # Routine confirms stay leadtime_only so play ticks skip Python.
            leadtime_only = not bool(leadtime_confirm.get("force"))
            # Prefer the live dropdown / display-style over a stale request.
            # Locked colormap edits skip this publisher, so prev.colormap can
            # still be blues_r while play soft-swaps the user's ramp from the
            # rewritten leadtimeCogUrls cache — and Pause would snap back.
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
                leadtime_only=leadtime_only,
            )

        if triggered == "forecast-init-date-picker":
            # The step held in State belongs to the previous forecast until
            # the scrubber callback rewinds it.
            lead = 0
        elif (
            triggered in ("map-view-mode", "colormap-dropdown", "map-style-refresh")
            and prev
        ):
            lead = prev.get("lead", 0)

        try:
            band = int(variable) if variable is not None and variable != "" else None
        except (TypeError, ValueError):
            band = None

        # A new variable must not keep a pinned range from the previous band.
        clear_lock = (
            triggered == "variable-dropdown"
            and prev is not None
            and band is not None
            and prev.get("variable") != band
        )
        tms_only = (
            triggered == "map-view-mode"
            and prev is not None
            and band is not None
            and prev.get("collection") == cols
            and prev.get("forecast_start") == forecast_start
            and prev.get("variable") == band
        )
        colormap_only = (
            triggered == "colormap-dropdown"
            and prev is not None
            and not force_stats
            and band is not None
            and prev.get("collection") == cols
            and prev.get("forecast_start") == forecast_start
            and prev.get("variable") == band
        )

        request = build_map_request(
            prev,
            collection=collection_ids,
            forecast_start=forecast_start,
            variable=variable,
            colormap=colormap,
            view_mode=map_view_mode,
            lead=lead,
            force_stats=force_stats,
            clear_lock=clear_lock,
            leadtime_only=leadtime_only,
            tms_only=tms_only,
            colormap_only=colormap_only,
        )
        if request is None:
            if prev is None:
                raise PreventUpdate
            return None
        return request

    @app.callback(
        Output("map-state", "data"),
        Output("cog-results-layer", "children"),
        Output("display-style", "data"),
        Output("map-view-mode", "value"),
        Input("map-request", "data"),
        State("display-style", "data"),
        State("map-state", "data"),
        State("leadtime-playing", "data"),
        prevent_initial_call=True,
    )
    def update_cog_layer(
        map_request,
        display_style,
        map_state,
        leadtime_playing,
    ):
        """
        Resolve tiles from ``map-request`` and publish ``map-state``.

        Control widgets never paint directly; ``publish_map_request`` (and the
        variables bootstrap path) turn their values into this store so prefs
        rehydration and user edits share one path.

        Writes shared ``map-state`` for OpenLayers (default). When the engine is
        ``leaflet_legacy``, also builds Leaflet Overlay children.

        The display range and lock flag live in ``display-style`` (the single
        source of truth for the colourbar). When locked, that pinned range is
        used to build tiles here; when unlocked, this callback computes fresh
        statistics (Item STATISTICS_* first, TiTiler statistics as a
        fallback). Locked colormap edits are applied by
        ``apply_locked_display_style`` instead of here, so this callback does
        not take the colourbar min/max inputs as Inputs (that would create a
        feedback loop with the clientside pin callbacks).

        Picking a new variable clears any pinned range from the previous band
        (``clear_lock`` on the request). ``map-style-refresh`` (colourbar Auto)
        sets ``force_stats`` so a fresh unlocked statistics rebuild runs even
        if a pin was active moments before.

        Leadtime comes from ``leadtime-confirm`` via the publisher (the browser
        swaps overlay URLs from the published ``leadtimeCogUrls`` cache while
        scrubbing). Confirms that arrive while playing are dropped unless
        ``force`` is set (init-day rewind). Polar modes that lack a TiTiler TMS
        fall back to global Web Mercator and the view-mode control is synced.
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

        collection_ids = map_request.get("collection") or []
        forecast_start_date = map_request.get("forecast_start")
        band_index = map_request.get("variable")
        colormap = map_request.get("colormap")
        map_view_mode = map_request.get("view_mode")
        leadtime = map_request.get("lead", 0)
        force_stats = bool(map_request.get("force_stats"))
        clear_lock = bool(map_request.get("clear_lock"))
        leadtime_only = bool(map_request.get("leadtime_only"))
        tms_only = bool(map_request.get("tms_only"))
        colormap_only = bool(map_request.get("colormap_only"))

        style = normalise_display_style(display_style)
        locked = bool(style.get("locked"))

        # The browser owns the frame while playing; confirming every step
        # would queue a Python rebuild behind each tick.
        if leadtime_only and leadtime_playing:
            return no_update, no_update, no_update, no_update

        # A new variable must not keep a pinned range from the previous band.
        if clear_lock and locked:
            locked = False
            style["locked"] = False
            style["source"] = "stats"

        # Leadtime confirms should honour the ramp already on screen
        # (display-style / soft-swap cache). map-request.colormap can lag after
        # locked colormap edits, which skip publish_map_request.
        # All other paints take the request first so unlocked colormap_only
        # applies before display-style is rewritten in this same callback.
        if leadtime_only:
            active_colormap = resolve_live_colormap(
                style.get("colormap"),
                colormap,
            )
        else:
            active_colormap = resolve_live_colormap(
                colormap,
                style.get("colormap"),
            )

        ui_mode = map_view_mode or MapViewMode.GLOBAL_3857.value
        requested_mode, _ = resolve_mode_and_engine(ui_mode)

        resolved_mode, view = view_mode_and_hint(requested_mode, TILER_INTERNAL_URL)
        mode = resolved_mode
        engine = resolve_engine_for_mode(mode)
        # Sync the view-mode control when mode was adjusted (TMS fallback).
        mode_control = mode if mode != ui_mode else no_update
        try:
            tile_matrix_set = tile_matrix_set_for_mode(mode)
        except ValueError:
            tile_matrix_set = WEB_MERCATOR_QUAD
            mode = MapViewMode.GLOBAL_3857.value
            view = view_mode_and_hint(mode, TILER_INTERNAL_URL)[1]
            engine = resolve_engine_for_mode(mode)
            mode_control = mode if mode != ui_mode else no_update

        def _publish(layer_entries, next_style, *, leadtime_cog_urls):
            logging.debug(
                "painting map-request rev=%s layers=%s mode=%s",
                map_request.get("revision"),
                len(layer_entries or []),
                mode,
            )
            next_state = build_map_state(
                previous=map_state,
                engine=engine,
                mode=mode,
                layers=layer_entries,
                view=view,
                leadtime_cog_urls=leadtime_cog_urls,
                lead=leadtime,
                # Warm the next step so a play tick or a forward scrub finds
                # the tiles already in the browser and tiler caches.
                prefetch_layers=layers_from_leadtime_cog_urls(
                    leadtime_cog_urls, (leadtime or 0) + 1
                ),
            )
            leaflet_children = (
                _build_leaflet_overlays(layer_entries)
                if engine == MapEngine.LEAFLET_LEGACY.value
                else []
            )
            return (
                next_state,
                leaflet_children,
                next_style,
                mode_control,
            )

        # Incomplete recipes should not stamp an empty map-state (prefs
        # rehydration used to leave the map blank that way).
        if not forecast_start_date or band_index is None or not collection_ids:
            return no_update, no_update, no_update, no_update

        stac = _get_stac_client()
        forecast_reference_time_str = date_picker_to_reference_time(
            forecast_start_date
        )
        leadtime = 0 if leadtime is None else leadtime

        def _layers_for_scale(min_val, max_val):
            return _build_forecast_layer_entries(
                stac,
                collection_ids,
                forecast_reference_time_str,
                leadtime,
                band_index,
                active_colormap,
                min_val,
                max_val,
                tile_matrix_set=tile_matrix_set,
                view_mode=mode,
            )

        def _cog_urls_for_scale(min_val, max_val):
            return _build_leadtime_cog_urls(
                stac,
                collection_ids,
                forecast_reference_time_str,
                band_index,
                active_colormap,
                min_val,
                max_val,
                tile_matrix_set,
                mode,
            )

        def _style_for(min_val, max_val, *, source: str):
            next_style = dict(style)
            next_style["colormap"] = active_colormap
            next_style["vmin"] = float(min_val)
            next_style["vmax"] = float(max_val)
            next_style["source"] = source
            # Keep a user pin across rebuilds that reused the pinned window.
            next_style["locked"] = source == "user"
            if source == "stats":
                next_style["domain_min"] = float(min_val)
                next_style["domain_max"] = float(max_val)
            else:
                # Keep the prior domain; expand it if the window moves outside.
                dmin = float(next_style.get("domain_min", min_val))
                dmax = float(next_style.get("domain_max", max_val))
                next_style["domain_min"] = min(dmin, float(min_val))
                next_style["domain_max"] = max(dmax, float(max_val))
            return next_style

        # TMS / view-mode switch: rewrite TileMatrixSet on existing URLs.
        # Skip STAC walks, extent filtering, and TiTiler statistics so the
        # control feels instant (client already applied an optimistic state).
        if tms_only:
            previous_layers = (map_state or {}).get("layers") or []
            rewritten = rewrite_layer_entries_tms(
                previous_layers, tile_matrix_set
            )
            if rewritten is not None:
                return _publish(
                    rewritten,
                    no_update,
                    leadtime_cog_urls=rewrite_leadtime_cog_urls_tms(
                        (map_state or {}).get("leadtimeCogUrls"), tile_matrix_set
                    ),
                )
            # No reusable overlays yet (e.g. prefs just set the mode): fall
            # through to the full catalogue rebuild below instead of publishing
            # an empty layer list.
            if "vmin" in style and "vmax" in style:
                layer_entries = _layers_for_scale(style["vmin"], style["vmax"])
                if layer_entries:
                    return _publish(
                        layer_entries,
                        no_update,
                        leadtime_cog_urls=_cog_urls_for_scale(
                            style["vmin"], style["vmax"]
                        ),
                    )

        # Colour map only, unlocked: reuse the current range from display-style.
        if colormap_only and not locked:
            layer_entries = _layers_for_scale(style["vmin"], style["vmax"])
            if not layer_entries:
                return no_update, no_update, no_update, no_update
            return _publish(
                layer_entries,
                _style_for(
                    style["vmin"],
                    style["vmax"],
                    source=style.get("source") or "stats",
                ),
                leadtime_cog_urls=_cog_urls_for_scale(style["vmin"], style["vmax"]),
            )

        # Leadtime scrub/play: keep the current colour scale. Never re-query
        # band stats mid-animation (or while scrubbing with a known or pinned
        # scale).
        reuse_leadtime_scale = (
            not force_stats
            and leadtime_only
            and (
                bool(leadtime_playing)
                or ("vmin" in style and "vmax" in style)
                or locked
            )
        )
        if reuse_leadtime_scale:
            min_val = style.get("vmin")
            max_val = style.get("vmax")
            if min_val is not None and max_val is not None:
                cached_cog_urls = (map_state or {}).get("leadtimeCogUrls")
                if leadtime_cog_urls_match_style(
                    cached_cog_urls,
                    tile_matrix_set=tile_matrix_set,
                    colormap=active_colormap,
                    rescale=(float(min_val), float(max_val)),
                    band_index=band_index,
                    collection_ids=collection_ids,
                ):
                    # The published cache already covers this step: build the
                    # overlay URLs from it instead of walking the catalogue.
                    layer_entries = layers_from_leadtime_cog_urls(
                        cached_cog_urls, leadtime
                    )
                    if layer_entries:
                        return _publish(
                            layer_entries,
                            no_update,
                            leadtime_cog_urls=cached_cog_urls,
                        )
                layer_entries = _layers_for_scale(min_val, max_val)
                if not layer_entries:
                    return no_update, no_update, no_update, no_update
                return _publish(
                    layer_entries,
                    no_update,
                    leadtime_cog_urls=_cog_urls_for_scale(min_val, max_val),
                )

        # Collect hrefs first so we can resolve one shared display range, then
        # build layers.
        min_vals: list[float] = []
        max_vals: list[float] = []
        layer_specs: list[tuple[str, Asset, str]] = []

        for collection_id in collection_ids or []:
            try:
                if not _collection_fits_view_mode(stac, collection_id, mode):
                    logging.info(
                        "Skipping collection %s: does not fit view mode %s",
                        collection_id,
                        mode,
                    )
                    continue

                # Get COG assets for this collection and date
                cogs = stac.get_item_cogs(
                    collection_id, forecast_reference_time_str
                )
                cog_assets = list(cogs.values())
                if leadtime >= len(cog_assets):
                    logging.warning(
                        "Leadtime %s out of range for %s", leadtime, collection_id
                    )
                    continue
                cog_asset = cog_assets[leadtime]
                layer_specs.append((collection_id, cog_asset, cog_asset.href))

                # Determine rescale range: a user pin wins unless this is a
                # forced Auto reset, otherwise resolve fresh statistics.
                if locked and not force_stats:
                    min_val = style["vmin"]
                    max_val = style["vmax"]
                else:
                    # Prefer Item STATISTICS_*; fall back to TiTiler /cog/statistics
                    min_val, max_val = _resolve_band_minmax(
                        stac, cog_asset, band_index, cog_asset.href
                    )

                min_vals.append(round_2dp(min_val))
                max_vals.append(round_2dp(max_val))
            except Exception as e:
                # Handle exception where this collection does not have the selected date
                logging.error(
                    "Error processing collection %s: %s", collection_id, e
                )
                continue

        if not layer_specs or not min_vals:
            # View-mode change with no fitting collections: clear overlays only
            # when we already had some (avoid stamping empty map-state on boot).
            if tms_only and (map_state or {}).get("layers"):
                return _publish([], no_update, leadtime_cog_urls=None)
            return no_update, no_update, no_update, no_update

        min_val = min(min_vals)
        max_val = max(max_vals)

        layer_entries = _build_forecast_layer_entries(
            stac,
            [spec[0] for spec in layer_specs],
            forecast_reference_time_str,
            leadtime,
            band_index,
            active_colormap,
            min_val,
            max_val,
            tile_matrix_set=tile_matrix_set,
            view_mode=mode,
        )
        if not layer_entries:
            if tms_only and (map_state or {}).get("layers"):
                return _publish([], no_update, leadtime_cog_urls=None)
            return no_update, no_update, no_update, no_update

        next_style = _style_for(
            min_val,
            max_val,
            source="user" if (locked and not force_stats) else "stats",
        )
        return _publish(
            layer_entries,
            next_style,
            leadtime_cog_urls=_cog_urls_for_scale(min_val, max_val),
        )

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
