import logging
import math
import os
from urllib.parse import urlparse, urlunparse

import dash
import dash_leaflet as dl
import pandas as pd
from config import STAC_FASTAPI_URL, TILER_URL
from datetime import datetime, timedelta
from dash import ALL, MATCH, Input, Output, State, no_update
from pystac.utils import datetime_to_str, str_to_datetime
from stac.process import (
    STAC,
)

from .utils import convert_colormap_to_colorscale, get_cog_band_statistics, round_2dp


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
        cog_path: The path to the Cloud Optimized GeoTIFF file relative to `DATA_URL`.

    Returns:
        The URL using the specified tiler and format, with placeholders for z, x, y.

    Raises:
        None
    """
    return f"{TILER_URL}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?url={cog_path}"
    # To return tiles back in EPSG:6931
    # Useful when Leaflet reprojection code is working.
    # return f"{TILER_URL}/cog/tiles/EPSG6931/{{z}}/{{x}}/{{y}}?url={cog_path}"


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
        Input("interval", "n_intervals")
    )

    @app.callback(
        [
            Output("collections-dropdown", "options"),
        ],
        [Input("page-load-trigger", "data")],
        prevent_initial_callback=True,
    )
    def update_collections(_):
        stac = STAC(STAC_FASTAPI_URL)
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
        prevent_initial_callback=True,
    )
    def update_forecast_start_dates(
        _, collection_ids: list
    ) -> list[list[str], str | None, str | None, str | None, pd.DatetimeIndex | None]:
        """
        This function retrieves and processes forecast start dates from the STAC Catalog.
        It returns a list containing sorted forecast start dates, min/max allowed dates,
        initial visible month, and disabled days for the date picker.

        Returns:
            A list containing:
                - Sorted forecast start dates
                - Minimum allowed date
                - Maximum allowed date
                - Initial visible month
                - Disabled days for the date picker
        """
        if not collection_ids:
            return [None, None, None, None, None, None]

        stac = STAC(STAC_FASTAPI_URL)
        all_forecast_dates = set()
        forecast_dates_dict = {}

        for collection_id in collection_ids:
            try:
                forecast_init_dates = stac.get_collection_forecast_init_dates(collection_id)

                if not forecast_init_dates:
                    continue

                for d in forecast_init_dates:
                    all_forecast_dates.add(d)
                    # Use the latest leadtime per date from all collections
                    try:
                        leadtime = stac.get_item_leadtime(
                            collection_id, forecast_reference_time=datetime_to_str(d)
                        )
                        leadtime_end = (d + timedelta(days=leadtime)).date().isoformat()
                        forecast_dates_dict[d.strftime("%Y-%m-%d")] = leadtime_end
                    except Exception as lt_err:
                        logging.warning(f"Leadtime error for {collection_id} on {d}: {lt_err}")

            except Exception as e:
                logging.error(f"Failed to retrieve forecast dates for {collection_id}: {e}")


        if not all_forecast_dates:
            logging.debug("No forecast dates loaded from any selected collection.")
            return [None, None, None, None, None, None]

        sorted_dates = sorted(all_forecast_dates)
        # Note to self: Dates should be in format '%Y-%m-%dT%H:%M:%SZ'
        min_date = sorted_dates[0].date().isoformat()
        max_date = sorted_dates[-1].date().isoformat()
        initial_visible_month = max_date

        logging.debug(f"Available forecast start dates from {min_date} to {max_date}")
        logging.debug(
            f"Creating list of dates starting from {min_date} to {max_date}"
        )

        # Calculate disabled dates
        date_range = pd.date_range(min_date, max_date)
        available_dates = {d.date() for d in sorted_dates}
        disabled_dates = [d.date().isoformat() for d in date_range if d.date() not in available_dates]
        logging.debug("Disabled days:", disabled_dates)

        return [
            forecast_dates_dict,
            min_date,
            max_date,
            initial_visible_month,
            disabled_dates,
            no_update
        ]


    @app.callback(
        Output("variable-dropdown", "options"),
        Input("forecast-init-date-picker", "value"),
        Input("leadtime-slider", "value"),
        Input("collections-dropdown", "value"),
        prevent_initial_call=True,
    )
    def update_available_variables(selected_date, leadtime: int, collection_ids: list):
        """
        Updates the variable dropdown based on selected date, leadtime, and multiple collection IDs.
        Aggregates variable options from all selected collections.
        """
        if not selected_date or not collection_ids:
            return []

        stac = STAC(STAC_FASTAPI_URL)

        # Convert to ISO 8601 format which is what the "forecast:reference_time" property is stored as
        forecast_reference_time_str = datetime.strptime(selected_date, "%Y-%m-%d").isoformat() + "Z"

        combined_vars = {}

        for collection_id in collection_ids:
            try:
                available_vars = stac.get_asset_bands(
                    collection_id,
                    forecast_reference_time_str,
                    forecast_reference_time_str,
                )

                if available_vars:
                    for var_name, band_index in available_vars.items():
                        # Avoid collisions: only keep first occurrence
                        if var_name not in combined_vars:
                            combined_vars[var_name] = band_index

            except Exception as e:
                logging.warning(f"Error retrieving variables for {collection_id}: {e}")
                continue

        if not combined_vars:
            return []

        return [{"label": var_name, "value": band_index} for var_name, band_index in combined_vars.items()]


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
        selected_date: String format of 'YYYY-MM-DD'
        forecast_dates: Dict with keys in 'YYYY-MM-DD', and values in format of '%Y-%m-%dT%H-%M'
        """
        if not forecast_dates or not selected_date or selected_date not in forecast_dates:
            return no_update

        forecast_start_date = datetime.strptime(selected_date, "%Y-%m-%d")
        forecast_end_date = str_to_datetime(forecast_dates[selected_date])

        logging.info("forecast start date:", forecast_start_date)
        logging.info("forecast end date:", forecast_end_date)

        num_days = (forecast_end_date - forecast_start_date).days

        # Account for leadtime zero-indexing
        leadtime_min = 0
        leadtime_max = num_days - 1
        leadtimes = list(range(num_days))

        # # For dcc.Slider
        # marks = {
        #     idx : (forecast_start_date + timedelta(days=idx)).strftime("%Y-%m-%d") for idx in leadtimes
        # }

        # # For dash mantine slider
        # Dynamically calculate step size based on window width
        desired_marks = max(2, window_width // 100)
        step = max(1, math.ceil(len(leadtimes) / desired_marks))

        marks = [
            {
                "value": idx,
                "label": (forecast_start_date + timedelta(days=idx)).strftime("%d %b %y"),
            }
            for idx in leadtimes[::step]
        ]

        current_label = (forecast_start_date + timedelta(days=leadtime)).strftime("%Y-%m-%d")
        current_leadtime = f"Selected Leadtime: {current_label}"

        slider_style["display"] = "inline-block"
        return slider_style, current_leadtime, leadtime_min, leadtime_max, marks


    @app.callback(
        Output("cog-results-layer", "children"),
        Output("fixed-min", "value"),
        Output("fixed-max", "value"),
        Input("colormap-dropdown", "value"),
        Input("forecast-init-date-picker", "value"),
        Input("variable-dropdown", "value"),
        Input("fix-colorbar-range", "data"),
        Input("fixed-min", "value"),
        Input("fixed-max", "value"),
        Input("collections-dropdown", "value"),
        Input("leadtime-slider", "value"),
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
        leadtime: int = 0,
    ):
        """
        Updates the COG layers on the map based on selected colormap, date, and leadtime.

        Args:
            colormap: The selected colormap.
            forecast_start_date: The selected initial date for the forecast.
                If not provided, no tiles will be displayed.
            leadtime (optional): The lead time in days. Defaults to 0.

        Returns:
            list: A list of Overlay objects representing the COG layers with updated tile URLs and options.
        """

        if not forecast_start_date:
            return no_update, no_update, no_update

        stac = STAC(STAC_FASTAPI_URL)

        # Convert to ISO 8601 format expected
        forecast_reference_time_str = datetime.strptime(forecast_start_date, "%Y-%m-%d").isoformat() + "Z"
        tile_layers = []
        min_vals = []
        max_vals = []

        for idx, collection_id in enumerate(collection_ids):
            try:
                # Get COG assets for this collection and date
                cogs = stac.get_item_cogs(collection_id, forecast_reference_time_str)
                cog_assets = list(cogs.values())

                if leadtime >= len(cog_assets):
                    logging.warning(f"Leadtime {leadtime} out of range for {collection_id}")
                    continue

                cog_asset = cog_assets[leadtime]
                cog_href = cog_asset.href

                # Determine rescale range
                if "fixed" in (fix_range or []):
                    min_val = fixed_min if fixed_min is not None else 0
                    max_val = fixed_max if fixed_max is not None else 1
                else:
                    # Get min/max to rescale the 0-255 image to data range
                    band_stats = get_cog_band_statistics(TILER_URL, cog_url=cog_href, band_index=band_index)
                    min_val = band_stats.get("min", 0)
                    max_val = band_stats.get("max", 1)

                min_val, max_val = round_2dp(min_val), round_2dp(max_val)
                min_vals.append(min_val)
                max_vals.append(max_val)

                tile_url = get_tile_url(cog_href) + f"&colormap_name={colormap}&rescale={min_val},{max_val}&bidx={band_index}"

                print("tile_url:", tile_url)

                layer = dl.Overlay(
                    dl.TileLayer(
                        id={"type": "cog-collections", "index": 0},
                        url=tile_url,
                        zIndex=100,
                        opacity=1,
                    ),
                    name=collection_id,
                    checked=True,
                )
                tile_layers.append(layer)

            # Handle exception where this collection does not have the selected date
            except Exception as e:
                logging.error(f"Error processing collection {collection_id}: {e}")
                continue

        if not tile_layers:
            return no_update, no_update, no_update

        # Use first min/max, or optionally min(min_vals)/max(max_vals) for all layers
        return tile_layers, min(min_vals), max(max_vals)


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
        colorscale = convert_colormap_to_colorscale(colormap) if colormap else colorscale
        if not (isinstance(min_val, (int, float)) and isinstance(max_val, (int, float))):
            min_val, max_val = 0, 1
        return colorscale, min_val, max_val

    @app.callback(
        Output("controls", "style"),
        Input("controls-btn", "n_clicks"),
        State("controls", "style"),
        prevent_initial_call=True
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

