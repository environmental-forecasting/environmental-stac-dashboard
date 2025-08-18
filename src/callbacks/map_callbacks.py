import logging
import math
import os
from urllib.parse import urlparse, urlunparse

import dash
import dash_leaflet as dl
import pandas as pd
from config import CATALOG_PATH, DATA_URL, TITILER_URL
from datetime import datetime, timedelta
from dash import ALL, MATCH, Input, Output, State, no_update
from stac.process import (
    STAC,
    get_all_forecast_dates,
    get_all_forecast_start_dates,
    get_cog_path,
    get_collections,
    get_leadtime,
)

from .utils import convert_colormap_to_colorscale


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
    cog_path = normalise_url_path(f"{DATA_URL}/{cog_path}")
    return f"{TITILER_URL}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?url={cog_path}"


# Callback function that will update the output container based on input
def register_callbacks(app: dash.Dash):
    """
    Registers Dash callbacks for updating COG layers and their opacities on the map.

    Args:
        The Dash app instance.
    """

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
        forecast_dates = get_all_forecast_dates(CATALOG_PATH, collection_id="north")

        if forecast_dates:
            forecast_start_dates_str = forecast_dates.keys()
            forecast_start_dates = [datetime.strptime(date_str, "%Y-%m-%d") for date_str in forecast_start_dates_str]
            forecast_start_dates = sorted(forecast_start_dates)

            # Define start and end `forecast_init_dates` for available IceNet forecasts
            logging.debug("Forecast start dates available:", forecast_start_dates)

            # Note to self: Dates should be in format 'YYYY-MM-DD'
            min_date_allowed = forecast_start_dates[0]
            max_date_allowed = forecast_start_dates[-1]
            initial_visible_month = max_date_allowed

            logging.debug("min_date_allowed", min_date_allowed)
            logging.debug("max_date_allowed", max_date_allowed)

            # Create list of days we don't have forecasts for, so, we can disable them in date picker.
            date_range = pd.date_range(min_date_allowed, max_date_allowed, freq="D")
            forecast_start_date_set = set(d.date() for d in forecast_start_dates)
            disabled_days = [d.date() for d in date_range if d.date() not in forecast_start_date_set]
            logging.debug(
                f"Creating list of dates starting from {min_date_allowed} to {max_date_allowed}"
            )
            logging.debug("Disabled days:", disabled_days)
        else:
            min_date_allowed = None
            max_date_allowed = None
            initial_visible_month = None
            disabled_days = None
            logging.debug(
                "No forecast dates loaded, issue connecting to/loading STAC Catalog?"
            )

        return [
            forecast_dates,
            min_date_allowed,
            max_date_allowed,
            initial_visible_month,
            disabled_days,
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
    def update_leadtime_slider(window_width: str, selected_date, leadtime: int, forecast_dates: dict, slider_style):
        if not selected_date or selected_date not in forecast_dates:
            return no_update

        forecast_start_date_str = selected_date
        forecast_end_date_str = forecast_dates[selected_date]
        forecast_start_date = datetime.strptime(forecast_start_date_str, "%Y-%m-%d")
        forecast_end_date = datetime.strptime(forecast_end_date_str, "%Y-%m-%d")

        num_days = (forecast_end_date - forecast_start_date).days
        leadtime_min = 0
        leadtime_max = num_days
        leadtimes = list(range(num_days + 1))
        marks = {
            idx : (forecast_start_date + timedelta(days=idx)).strftime("%Y-%m-%d") for idx in leadtimes
        }

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
        Input("colormap-dropdown", "value"),
        Input("forecast-init-date-picker", "value"),
        Input("leadtime-slider", "value"),
        prevent_initial_call=True,
    )
    def update_cog_layer(colormap: str, forecast_start_date: str, leadtime: int = 0):
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
        collections = get_collections(CATALOG_PATH)
        tile_layers = []
        for i, collection_id in enumerate(collections):
            logging.debug("collections", collections)
            logging.debug(f"Colormap changed to {colormap}")

            if not forecast_start_date:
                return no_update  # No tiles to display

            selected_item = get_cog_path(
                CATALOG_PATH, collection_id, forecast_start_date, leadtime
            )
            if selected_item:
                logging.debug(
                    "This is the selected_item:",
                    selected_item,
                    "in collection:",
                    collection_id,
                )

                # Get the tile URL from Titiler
                tile_url = (
                    get_tile_url(selected_item)
                    + f"&colormap_name={colormap}&rescale=0,1"
                )
                tile_url = normalise_url_path(tile_url)
                logging.debug("tile_url:", tile_url)

                collection_layer = dl.Overlay(
                    dl.TileLayer(
                        id={"type": "cog-collections", "index": i},
                        url=tile_url,
                        zIndex=100,
                        opacity=1,
                    ),
                    name=collection_id,
                    checked=True,
                )

                tile_layers.append(collection_layer)

        return tile_layers

    @app.callback(
        Output("cbar", "colorscale"),
        Input("cbar", "colorscale"),
        Input("colormap-dropdown", "value"),
        prevent_initial_call=True,
    )
    def show_cbar(colorscale, colormap):
        if colormap:
            colorscale = convert_colormap_to_colorscale(colormap)
            return colorscale
        else:
            return colorscale

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
