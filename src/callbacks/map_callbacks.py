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
from components.controls import DEFAULT_COLORMAP
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

from map import (
    WEB_MERCATOR_QUAD,
    MapEngine,
    MapViewMode,
    bbox_fits_view_mode,
    build_cog_tile_url,
    build_map_state,
    list_view_mode_options,
    list_view_mode_presets,
    resolve_mode_and_engine,
    resolve_engine_for_mode,
    rewrite_layer_entries_style,
    rewrite_layer_entries_tms,
    rewrite_leadtime_cog_urls_style,
    tile_matrix_set_for_mode,
    to_tiler_asset_url,
    view_mode_and_hint,
)

from .display_style import cbar_ramp_style, cbar_slider_step, normalise_display_style
from .utils import get_cog_band_statistics, round_2dp


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
        [Output("collections-dropdown", "options")],
        [Input("page-load-trigger", "data")],
        # Must run on load: page-load-trigger is already True in the layout, so
        # prevent_initial_call=True would skip the only invocation and leave
        # the dropdown empty.
        prevent_initial_call=False,
    )
    def update_collections(_):
        stac = _get_stac_client()
        collections = stac.get_catalog_collection_ids(resolve=True)
        # Reuse summaries on these Collection objects for forecast inits
        # so selecting a collection does not GET /collections/{id} again.
        stac.cache_collections(collections)
        options = []
        for collection in collections:
            option = {"label": collection.id, "value": collection.id}
            options.append(option)
        return [options]

    @app.callback(
        Output("map-view-mode", "options"),
        Output("map-view-presets", "data"),
        Input("page-load-trigger", "data"),
        prevent_initial_call=False,
    )
    def update_map_view_mode_options(_):
        """Populate Global / Leaflet / Globe + custom EPSG#### views."""
        return (
            list_view_mode_options(TILER_INTERNAL_URL),
            list_view_mode_presets(TILER_INTERNAL_URL),
        )

    @app.callback(
        [
            Output("forecast-dates-store", "data"),
            Output("forecast-init-date-picker", "minDate"),
            Output("forecast-init-date-picker", "maxDate"),
            Output("forecast-init-date-picker", "defaultDate"),
            Output("forecast-init-date-picker", "disabledDates"),
            Output("forecast-init-date-picker", "value"),
        ],
        [
            Input("page-load-trigger", "data"),
            Input("collections-dropdown", "value"),
        ],
        prevent_initial_call=True,
    )
    def update_forecast_start_dates(
        _, collection_ids: list
    ) -> list:
        """
        Load available forecast init dates from STAC for the selected collections.

        Prefer inits already primed from Collection summaries at dropdown
        load; otherwise list_forecast_inits falls back to a slim Item Search.
        """
        if not collection_ids:
            return [None, None, None, None, None, None]

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
            return [None, None, None, None, None, None]

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

        return [
            forecast_dates_dict,
            min_date,
            max_date,
            initial_visible_month,
            disabled_dates,
            no_update,
        ]

    @app.callback(
        Output("variable-dropdown", "options"),
        Output("variable-dropdown", "value"),
        Input("forecast-init-date-picker", "value"),
        Input("collections-dropdown", "value"),
        State("variable-dropdown", "value"),
        prevent_initial_call=True,
    )
    def update_available_variables(selected_date, collection_ids: list, current_value):
        """
        Fill the variable dropdown for the selected forecast date.

        Loads variable names through a light catalogue query so the list can
        appear without waiting for a full forecast download. On first load,
        or when the current choice is gone, pick the first variable.
        """
        if not selected_date or not collection_ids:
            return [], None

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
            return [], None

        options = [
            {"label": var_name, "value": band_index}
            for var_name, band_index in combined_vars.items()
        ]
        values = {opt["value"] for opt in options}
        if current_value in values:
            return options, no_update
        return options, options[0]["value"]

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
        State("forecast-dates-store", "data"),
        State("leadtime-step-unit", "data"),
        prevent_initial_call=True,
    )
    def update_leadtime_slider(
        window_width,
        selected_date: str,
        leadtime: int,
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

        width = int(window_width or 1200)
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
            current = 0 if leadtime is None else int(leadtime)
            next_value = max(leadtime_min, min(current, leadtime_max))
            pause = False
            value_out = next_value

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
        Output("map-state", "data"),
        Output("cog-results-layer", "children"),
        Output("display-style", "data"),
        Output("map-view-mode", "value"),
        Input("colormap-dropdown", "value"),
        Input("forecast-init-date-picker", "value"),
        Input("variable-dropdown", "value"),
        Input("collections-dropdown", "value"),
        Input("leadtime-slider", "value"),
        Input("map-view-mode", "value"),
        Input("map-style-refresh", "data"),
        State("display-style", "data"),
        State("map-state", "data"),
        State("leadtime-playing", "data"),
        prevent_initial_call=True,
    )
    def update_cog_layer(
        colormap: str,
        forecast_start_date: str,
        band_index: int,
        collection_ids: list,
        leadtime: int,
        map_view_mode: str,
        style_refresh,
        display_style,
        map_state,
        leadtime_playing,
    ):
        """
        Update map COG layers from the cached forecast Item.

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

        Picking a new variable clears any pinned range from the previous
        band. ``map-style-refresh`` (fired by the colourbar Auto button)
        forces a fresh unlocked statistics rebuild even if a pinned range was
        active moments before.

        Leadtime changes while playing (and scrubbing with a known or pinned
        range) reuse the current range so stats are not re-queried
        mid-animation. View-mode changes rebuild tiles for the matching
        projection and host (engine is derived from the selected mode);
        collections whose extent does not fit the hemisphere are skipped, and
        polar modes that lack a TiTiler TMS fall back to global Web Mercator.
        """
        triggered = callback_context.triggered_id
        style = normalise_display_style(display_style)
        locked = bool(style.get("locked"))
        force_stats = triggered == "map-style-refresh"

        # A new variable must not keep a pinned range from the previous band.
        if triggered == "variable-dropdown" and locked:
            locked = False
            style["locked"] = False
            style["source"] = "stats"

        # Locked colormap edits are applied clientside by
        # apply_locked_display_style; nothing to do here.
        if triggered == "colormap-dropdown" and locked:
            return no_update, no_update, no_update, no_update

        active_colormap = colormap or style.get("colormap") or DEFAULT_COLORMAP

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

        def _publish(layer_entries, next_style):
            next_state = build_map_state(
                previous=map_state,
                engine=engine,
                mode=mode,
                layers=layer_entries,
                view=view,
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

        # Allow projection switches before a forecast date is chosen.
        if not forecast_start_date or band_index is None:
            if triggered != "map-view-mode":
                return no_update, no_update, no_update, no_update
            return _publish([], no_update)

        stac = _get_stac_client()
        forecast_reference_time_str = date_picker_to_reference_time(forecast_start_date)
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

        def _style_for(min_val, max_val, *, source: str):
            next_style = dict(style)
            next_style["colormap"] = active_colormap
            next_style["vmin"] = float(min_val)
            next_style["vmax"] = float(max_val)
            next_style["source"] = source
            next_style["locked"] = False
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
        if triggered == "map-view-mode":
            previous_layers = (map_state or {}).get("layers") or []
            rewritten = rewrite_layer_entries_tms(
                previous_layers, tile_matrix_set
            )
            if rewritten is not None:
                return _publish(rewritten, no_update)
            if "vmin" in style and "vmax" in style:
                layer_entries = _layers_for_scale(style["vmin"], style["vmax"])
                if layer_entries:
                    return _publish(layer_entries, no_update)
                return _publish([], no_update)

        # Colour map only, unlocked: reuse the current range from display-style.
        if triggered == "colormap-dropdown" and not locked:
            layer_entries = _layers_for_scale(style["vmin"], style["vmax"])
            if not layer_entries:
                return no_update, no_update, no_update, no_update
            return _publish(
                layer_entries,
                _style_for(
                    style["vmin"], style["vmax"], source=style.get("source") or "stats"
                ),
            )

        # Leadtime scrub/play: keep the current colour scale. Never re-query
        # band stats mid-animation (or while scrubbing with a known or pinned
        # scale).
        reuse_leadtime_scale = (
            not force_stats
            and triggered == "leadtime-slider"
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
                layer_entries = _layers_for_scale(min_val, max_val)
                if not layer_entries:
                    return no_update, no_update, no_update, no_update
                return _publish(layer_entries, no_update)

        min_vals: list[float] = []
        max_vals: list[float] = []
        # Collect hrefs first so we can resolve one shared display range, then build layers.
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
            # Handle exception where this collection does not have the selected date
            except Exception as e:
                logging.error("Error processing collection %s: %s", collection_id, e)
                continue

        if not layer_specs or not min_vals:
            # View-mode change may leave no fitting layers; still update the host.
            if triggered == "map-view-mode":
                return _publish([], no_update)
            return no_update, no_update, no_update, no_update

        # Use first min/max, or optionally min(min_vals)/max(max_vals) for all layers
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
            if triggered == "map-view-mode":
                return _publish([], no_update)
            return no_update, no_update, no_update, no_update

        next_style = _style_for(
            min_val, max_val, source="user" if (locked and not force_stats) else "stats"
        )
        return _publish(layer_entries, next_style)

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
        """Toggle the right-hand controls column without covering the map."""
        opened = not bool(is_open)
        base = "forecast-controls-column"
        class_name = base if opened else f"{base} forecast-controls-column--collapsed"
        icon = "tabler:chevron-right" if opened else "tabler:chevron-left"
        return class_name, opened, icon

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
    # colour range. update_cog_layer skips locked colormap edits; the
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
