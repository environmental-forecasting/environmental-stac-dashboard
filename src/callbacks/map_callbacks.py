import logging
import math
import os
from urllib.parse import urlparse, urlunparse

import dash
import dash_leaflet as dl
import pandas as pd
from config import STAC_FASTAPI_URL, TITILER_URL
from datetime import datetime, timedelta
from dash import ALL, MATCH, Input, Output, State, no_update
from pystac.utils import datetime_to_str, str_to_datetime
from stac.process import (
    STAC,
)

from .utils import convert_colormap_to_colorscale, get_cog_band_statistics


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
    return f"{TITILER_URL}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?url={cog_path}"
    # To return tiles back in EPSG:6931
    # Useful when Leaflet reprojection code is working.
    # return f"{TITILER_URL}/cog/tiles/EPSG6931/{{z}}/{{x}}/{{y}}?url={cog_path}"


# Callback function that will update the output container based on input
def register_callbacks(app: dash.Dash):
    """
    Registers Dash callbacks for updating COG layers and their opacities on the map.

    Args:
        The Dash app instance.
    """

    stac = STAC(STAC_FASTAPI_URL)

    # Get first `collection_id` for testing
    collection_id = stac.get_catalog_collection_ids(resolve=True)[0].id

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
            Output("forecast-dates-store", "data"),
            Output("forecast-init-date-picker", "minDate"),
            Output("forecast-init-date-picker", "maxDate"),
            Output("forecast-init-date-picker", "defaultDate"),
            Output("forecast-init-date-picker", "disabledDates"),
        ],
        [Input("page-load-trigger", "data")],
    )
    def update_forecast_start_dates(
        _,
    ) -> list[list[str], str | None, str | None, str | None, pd.DatetimeIndex | None]:
        """
        This function retrieves and processes IceNet forecast start dates from the STAC Catalog.
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
        try:
            forecast_init_dates = stac.get_collection_forecast_init_dates(collection_id)
        except Exception as e:
            logging.error(f"Failed to retrieve forecast dates: {e}")
            return [None, None, None, None, None]

        if forecast_init_dates:
            forecast_start_dates = sorted(forecast_init_dates)
            forecast_dates_dict = {
                d.strftime("%Y-%m-%d"): (
                    d
                    + timedelta(
                        days=stac.get_item_leadtime(
                            collection_id, forecast_reference_time=datetime_to_str(d)
                        )
                    )
                )
                .date()
                .isoformat()
                for d in forecast_start_dates
            }

            # Define start and end `forecast_init_dates` for available IceNet forecasts
            logging.debug("Forecast start dates available:", forecast_start_dates)

            # Note to self: Dates should be in format '%Y-%m-%dT%H:%M:%SZ'
            min_date = forecast_start_dates[0].date().isoformat()
            max_date = forecast_start_dates[-1].date().isoformat()
            initial_visible_month = max_date

            logging.debug("min_date/max_date", min_date, max_date)

            # Create list of days we don't have forecasts for, so, we can disable them in date picker.
            date_range = pd.date_range(min_date, max_date)
            available_dates = {d.date() for d in forecast_start_dates}
            disabled_dates = [d.date().isoformat() for d in date_range if d.date() not in available_dates]

            logging.debug(
                f"Creating list of dates starting from {min_date} to {max_date}"
            )
            logging.debug("Disabled days:", disabled_dates)
        else:
            min_date = None
            max_date = None
            initial_visible_month = None
            disabled_dates = None
            logging.debug(
                "No forecast dates loaded, issue connecting to/loading STAC Catalog?"
            )

        return [
            forecast_dates_dict,
            min_date,
            max_date,
            initial_visible_month,
            disabled_dates,
        ]


    @app.callback(
        Output("variable-dropdown", "options"),
        Input("forecast-init-date-picker", "value"),
        Input("leadtime-slider", "value"),
        prevent_initial_call=True,
    )
    def update_available_variables(selected_date, leadtime: int):
        # forecast_start_date = datetime.strptime(selected_date, "%Y-%m-%d")
        # Convert to ISO 8601 format which is what the "forecast:reference_time" property is stored as
        forecast_reference_time_str = datetime.strptime(selected_date, "%Y-%m-%d").isoformat() + "Z"
        available_vars: dict[int] = stac.get_asset_bands(
            collection_id, forecast_reference_time_str, forecast_reference_time_str
        )
        # return available_vars.keys() if available_vars else None

        if not available_vars:
            return None

        return [{"label": var_name, "value": band_index} for var_name, band_index in available_vars.items()]

        # Assuming available_vars is a list of dicts like: [{'label': 'Temperature', 'band_index': 1}, ...]
        # return [{"label": var["label"], "value": var["band_index"]} for var in available_vars]


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
        if not selected_date or selected_date not in forecast_dates:
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
        Output("band-min-max", "data"),
        Input("colormap-dropdown", "value"),
        Input("forecast-init-date-picker", "value"),
        Input("variable-dropdown", "value"),
        Input("leadtime-slider", "value"),
        prevent_initial_call=True,
    )
    def update_cog_layer(colormap: str, forecast_start_date: str, band_index: int, leadtime: int = 0):
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
            return no_update

        # Convert to ISO 8601 format expected
        forecast_reference_time_str = datetime.strptime(forecast_start_date, "%Y-%m-%d").isoformat() + "Z"

        tile_layers = []

        # Get COG assets for this date
        cogs = stac.get_item_cogs(collection_id, forecast_reference_time_str)
        cog_assets = list(cogs.values())

        if leadtime >= len(cog_assets):
            logging.warning(f"Leadtime {leadtime} out of range for {collection_id}")
            return no_update

        cog_asset = cog_assets[leadtime]
        cog_href = cog_asset.href

        # Get min/max to rescale the 0-255 image to data range
        band_stats = get_cog_band_statistics(TITILER_URL, cog_url=cog_href, band_index=band_index)
        min_val = band_stats.get("min", 0)
        max_val = band_stats.get("max", 1)

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

        return tile_layers, {"min": min_val, "max": max_val}

    @app.callback(
        Output("cbar", "colorscale"),
        Output("cbar", "min"),
        Output("cbar", "max"),
        Input("cbar", "colorscale"),
        Input("colormap-dropdown", "value"),
        Input("band-min-max", "data"),
        prevent_initial_call=True,
    )
    def show_cbar(colorscale, colormap, band_min_max: dict):
        colorscale = convert_colormap_to_colorscale(colormap) if colormap else colorscale
        if band_min_max:
            min_val = band_min_max["min"]
            max_val = band_min_max["max"]
        else:
            min_val, max_val = 0, 1

        return colorscale, min_val, max_val

    @app.callback(
        Output({"type": "cog-collections", "index": ALL}, "opacity"),
        Input("opacity-slider", "value"),
        State({"type": "cog-collections", "index": ALL}, "opacity"),
    )
    def update_cog_layer_opacity(opacity: float, current_opacity: list[float]):
        """Update the opacity of all COG collections layers.

        This function updates the opacity of all 'cog-collections' layers based on the
        value provided by the 'opacity-slider'.

        Args:
            opacity: The new opacity value, range [0, 1].
            current_opacity: A list of the current opacity values for all layers.

        Returns:
            A list containing the updated opacity value for each layer.
        """
        logging.debug(f"Opacity changed to {opacity}")

        return [opacity] * len(current_opacity)
