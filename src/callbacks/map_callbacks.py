import logging
import math
import os
from datetime import datetime, timedelta
from functools import lru_cache
from urllib.parse import urlparse, urlunparse

import dash
import dash_leaflet as dl
import pandas as pd
from config import (
    FILE_SERVER_INTERNAL_URL,
    FILE_SERVER_URL,
    STAC_FASTAPI_URL,
    TILER_INTERNAL_URL,
    TILER_URL,
)
from dash import Input, Output, State, callback_context, no_update
from pystac import Asset
from stac.process import STAC
from stac.timefmt import (
    date_picker_to_reference_time,
    format_slider_label,
    parse_calendar_day,
    parse_stac_datetime,
    to_calendar_day,
)

from .utils import (
    convert_colormap_to_colorscale,
    get_cog_band_statistics,
    round_2dp,
    to_tiler_asset_url,
)


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
def get_tile_url(cog_path: str):
    """
    Returns the tile URL for the given STAC Item (i.e. COG path).

    Args:
        cog_path: Public STAC asset href for the COG. Rewritten for TiTiler fetch.

    Returns:
        The URL using the specified tiler and format, with placeholders for z, x, y.
    """
    # Browser hits TILER_URL; TiTiler itself fetches `url=`, so that must be
    # reachable from the titiler container (file-server Docker DNS).
    tiler_cog = to_tiler_asset_url(cog_path, FILE_SERVER_URL, FILE_SERVER_INTERNAL_URL)
    return f"{TILER_URL}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?url={tiler_cog}"
    # To return tiles back in EPSG:6931
    # Useful when Leaflet reprojection code is working.
    # return f"{TILER_URL}/cog/tiles/EPSG6931/{{z}}/{{x}}/{{y}}?url={cog_path}"


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
    tile_layers = []
    for collection_id in collection_ids or []:
        try:
            cogs = stac.get_item_cogs(collection_id, forecast_reference_time_str)
            cog_assets = list(cogs.values())

            if leadtime >= len(cog_assets):
                logging.warning(
                    "Leadtime %s out of range for %s", leadtime, collection_id
                )
                continue

            cog_asset = cog_assets[leadtime]
            tile_url = (
                get_tile_url(cog_asset.href)
                + f"&colormap_name={colormap}&rescale={min_val},{max_val}&bidx={band_index}"
            )
            logging.debug("tile_url: %s", tile_url)

            tile_layers.append(
                dl.Overlay(
                    dl.TileLayer(
                        id={"type": "cog-collections", "index": 0},
                        url=tile_url,
                        zIndex=100,
                        opacity=1,
                    ),
                    name=collection_id,
                    checked=True,
                )
            )
        except Exception as e:
            logging.error("Error processing collection %s: %s", collection_id, e)
            continue
    return tile_layers


# Callback function that will update the output container based on input
def register_callbacks(app: dash.Dash):
    """
    Registers Dash callbacks for updating COG layers and their opacities on the map.

    Args:
        The Dash app instance.
    """

    # # Get first `collection_id` for testing
    # collection_id = stac.get_catalog_collection_ids(resolve=True)[0].id

    # Get window width
    app.clientside_callback(
        """
        function(n) {
            return top.innerWidth;
        }
        """,
        Output("window-width", "data"),
        Input("interval", "n_intervals"),
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
        options = []
        for collection in collections:
            option = {"label": collection.id, "value": collection.id}
            options.append(option)
        return [options]

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

        Uses one slim Item Search per collection (via list_forecast_inits) so
        leadtime end dates do not need a second request per init.
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
        Input("forecast-init-date-picker", "value"),
        Input("collections-dropdown", "value"),
        prevent_initial_call=True,
    )
    def update_available_variables(selected_date, collection_ids: list):
        """
        Update the variable dropdown from the selected forecast Item.

        Band names are read from the first COG asset on the cached Item.
        """
        if not selected_date or not collection_ids:
            return []

        stac = _get_stac_client()
        forecast_reference_time_str = date_picker_to_reference_time(selected_date)
        combined_vars: dict[str, int] = {}

        for collection_id in collection_ids:
            try:
                cogs = stac.get_item_cogs(
                    collection_id, forecast_reference_time_str
                )
                if not cogs:
                    continue
                first_asset_id = next(iter(cogs))
                available_vars = stac.get_asset_bands(
                    collection_id,
                    forecast_reference_time_str,
                    first_asset_id,
                )
                if not available_vars:
                    continue
                for var_name, band_index in available_vars.items():
                    # Avoid collisions: only keep first occurrence
                    if var_name not in combined_vars:
                        combined_vars[var_name] = band_index
            except Exception as e:
                logging.warning(
                    "Error retrieving variables for %s: %s", collection_id, e
                )
                continue

        if not combined_vars:
            return []

        return [
            {"label": var_name, "value": band_index}
            for var_name, band_index in combined_vars.items()
        ]

    @app.callback(
        Output("time-slider-div", "style"),
        Output("selected-time", "children"),
        Output("leadtime-slider", "min"),
        Output("leadtime-slider", "max"),
        Output("leadtime-slider", "marks"),
        Input("window-width", "data"),
        Input("forecast-init-date-picker", "value"),
        Input("leadtime-slider", "value"),
        State("forecast-dates-store", "data"),
        State("time-slider-div", "style"),
        prevent_initial_call=True,
    )
    def update_leadtime_slider(
        window_width: str,
        selected_date: str,
        leadtime: int,
        forecast_dates: dict,
        slider_style,
    ):
        """
        selected_date: Calendar day 'YYYY-MM-DD'.
        forecast_dates: Dict of calendar day -> forecast end calendar day.
        """
        if (
            not forecast_dates
            or not selected_date
            or selected_date not in forecast_dates
        ):
            return no_update

        forecast_start_date = parse_calendar_day(selected_date)
        forecast_end_date = parse_calendar_day(forecast_dates[selected_date])

        logging.info("forecast start date: %s", forecast_start_date)
        logging.info("forecast end date: %s", forecast_end_date)

        num_days = (forecast_end_date - forecast_start_date).days

        # Account for leadtime zero-indexing
        leadtime_min = 0
        leadtime_max = num_days - 1
        leadtimes = list(range(num_days))

        # # For dcc.Slider
        # marks = {
        #     idx : to_calendar_day(forecast_start_date + timedelta(days=idx)) for idx in leadtimes
        # }

        # # For dash mantine slider
        # Dynamically calculate step size based on window width
        desired_marks = max(2, window_width // 100)
        step = max(1, math.ceil(len(leadtimes) / desired_marks))

        marks = [
            {
                "value": idx,
                "label": format_slider_label(
                    forecast_start_date + timedelta(days=idx)
                ),
            }
            for idx in leadtimes[::step]
        ]

        current_label = to_calendar_day(
            forecast_start_date + timedelta(days=leadtime)
        )
        current_leadtime = f"Selected Leadtime: {current_label}"

        slider_style["display"] = "inline-block"
        return slider_style, current_leadtime, leadtime_min, leadtime_max, marks

    @app.callback(
        Output("cog-results-layer", "children"),
        Output("rescale-store", "data"),
        Input("colormap-dropdown", "value"),
        Input("forecast-init-date-picker", "value"),
        Input("variable-dropdown", "value"),
        Input("fix-colorbar-range", "data"),
        Input("fixed-min", "value"),
        Input("fixed-max", "value"),
        Input("collections-dropdown", "value"),
        Input("leadtime-slider", "value"),
        State("rescale-store", "data"),
        prevent_initial_call=True,
    )
    def update_cog_layer(
        colormap: str,
        forecast_start_date: str,
        band_index: int,
        fix_range,
        fixed_min,
        fixed_max,
        collection_ids: list,
        leadtime: int,
        rescale_store,
    ):
        """
        Update map COG layers from the cached forecast Item.

        Auto mode prefers band STATISTICS_* on the Item; TiTiler statistics are
        only a fallback. Colour map changes reuse rescale-store. fixed-min/max
        are Inputs so fixed mode updates tiles, but they are not Outputs here
        (avoids a feedback loop). A separate callback copies rescale-store into
        the min/max inputs for display in auto mode.
        """
        if not forecast_start_date or band_index is None:
            return no_update, no_update

        triggered = callback_context.triggered_id
        is_fixed = "fixed" in (fix_range or [])

        # Ignore write-back from syncing auto rescale into the min/max inputs.
        if triggered in ("fixed-min", "fixed-max") and not is_fixed:
            return no_update, no_update

        stac = _get_stac_client()
        forecast_reference_time_str = date_picker_to_reference_time(forecast_start_date)
        leadtime = 0 if leadtime is None else leadtime

        # Colour map only: rebuild tile URLs from the stored range.
        if (
            triggered == "colormap-dropdown"
            and not is_fixed
            and isinstance(rescale_store, dict)
            and "min" in rescale_store
            and "max" in rescale_store
        ):
            min_val = rescale_store["min"]
            max_val = rescale_store["max"]
            tile_layers = _build_tile_layers(
                stac,
                collection_ids,
                forecast_reference_time_str,
                leadtime,
                band_index,
                colormap,
                min_val,
                max_val,
            )
            if not tile_layers:
                return no_update, no_update
            return tile_layers, no_update

        min_vals: list[float] = []
        max_vals: list[float] = []
        # Collect hrefs first so we can resolve one shared display range, then build layers.
        layer_specs: list[tuple[str, Asset, str]] = []

        for collection_id in collection_ids or []:
            try:
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

                # Determine rescale range
                if is_fixed:
                    min_val = fixed_min if fixed_min is not None else 0
                    max_val = fixed_max if fixed_max is not None else 1
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
            return no_update, no_update

        # Use first min/max, or optionally min(min_vals)/max(max_vals) for all layers
        min_val = min(min_vals)
        max_val = max(max_vals)

        tile_layers = _build_tile_layers(
            stac,
            [spec[0] for spec in layer_specs],
            forecast_reference_time_str,
            leadtime,
            band_index,
            colormap,
            min_val,
            max_val,
        )
        if not tile_layers:
            return no_update, no_update

        new_store = {"min": min_val, "max": max_val}
        return tile_layers, new_store

    @app.callback(
        Output("fixed-min", "value"),
        Output("fixed-max", "value"),
        Input("rescale-store", "data"),
        State("fix-colorbar-range", "data"),
        prevent_initial_call=True,
    )
    def sync_minmax_inputs_from_rescale(rescale_store, fix_range):
        """Show auto-computed min/max in the inputs without feeding update_cog_layer."""
        if "fixed" in (fix_range or []):
            return no_update, no_update
        if not isinstance(rescale_store, dict):
            return no_update, no_update
        if "min" not in rescale_store or "max" not in rescale_store:
            return no_update, no_update
        return rescale_store["min"], rescale_store["max"]

    @app.callback(
        Output("cbar", "colorscale"),
        Output("cbar", "min"),
        Output("cbar", "max"),
        Input("cbar", "colorscale"),
        Input("colormap-dropdown", "value"),
        Input("fixed-min", "value"),
        Input("fixed-max", "value"),
        prevent_initial_call=True,
    )
    def show_cbar(colorscale, colormap, min_val, max_val):
        colorscale = (
            convert_colormap_to_colorscale(colormap) if colormap else colorscale
        )
        if not (
            isinstance(min_val, (int, float)) and isinstance(max_val, (int, float))
        ):
            min_val, max_val = 0, 1
        return colorscale, min_val, max_val

    @app.callback(
        Output("controls", "style"),
        Input("controls-btn", "n_clicks"),
        State("controls", "style"),
        prevent_initial_call=True,
    )
    def toggle_main_controller(n_clicks, current_style):
        """
        Callback to toggle main controls div visibility
        """
        if not current_style:
            current_style = {}

        current_display = current_style.get("display", "inline-block")
        new_display = "none" if current_display == "inline-block" else "inline-block"
        new_style = current_style.copy()
        new_style["display"] = new_display

        return new_style

    @app.callback(
        Output("fix-colorbar-button", "style"),
        Output("fix-colorbar-range", "data"),
        Output("fixed-min", "disabled"),
        Output("fixed-max", "disabled"),
        Input("fix-colorbar-button", "n_clicks"),
        prevent_initial_call=False,
    )
    def toggle_fix_colorbar_button(n_clicks: int):
        """
        Toggles 'fix colorbar' button state.

        When button is clicked, this function alternates between two states:
        - Fixed mode: Updates button style to active, sets colourbar range to manual min/max range.
        - Unfixed mode: Reverts button styling, clears colorbar range data, and enables automatic min/max from dataset.

        Args:
            n_clicks: No. of times 'fix-colorbar-button' has been clicked.
                Used to determine whether the state is fixed or unfixed.

        Returns:
            dict: CSS style for the 'fix-colorbar-button', with themed background/foreground colors based on state.
            list: Colorbar range data, set to ['fixed'] when in fixed mode, and empty list otherwise.
            bool: Disabled state for the 'fixed-min' input (True if not fixed, False if fixed).
            bool: Disabled state for the 'fixed-max' input (same as 'fixed-min').

        Notes:
            - The callback is triggered on every click due to `prevent_initial_call=False`.
            - When not fixed, users can manually adjust min/max values; when fixed, adjustments are disabled.
            - Button styling alternates between a primary theme color and gray for visual feedback.
            - In auto mode, min/max are filled from rescale-store (Item STATISTICS_* or TiTiler fallback).
        """
        is_fixed = n_clicks % 2 == 1
        # Colour for enabled state
        theme_colour = "#3B71CA"
        style = {
            "backgroundColor": theme_colour if is_fixed else "#f0f0f0",
            "border": "none",
            "padding": "10px",
            "borderRadius": "5px",
            "cursor": "pointer",
            "width": "100%",
            "marginBottom": "10px",
            "fontWeight": "bold",
            "color": "white" if is_fixed else "#333",
        }
        disabled_inputs = False if is_fixed else True

        return style, (["fixed"] if is_fixed else []), disabled_inputs, disabled_inputs
