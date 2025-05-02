import logging
import dash
import dash_leaflet as dl
import pandas as pd
from config import CATALOG_PATH, DATA_URL, TITILER_URL
from dash import ALL, MATCH, Input, Output, State, no_update
from stac.process import get_all_forecast_start_dates, get_cog_path, get_collections, get_leadtime

import os
from urllib.parse import urlparse, urlunparse

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

    @app.callback(
        [Output("forecast-start-dates-store", "data"),
        Output("forecast-init-date-picker", "min_date_allowed"),
        Output("forecast-init-date-picker", "max_date_allowed"),
        Output("forecast-init-date-picker", "initial_visible_month"),
        Output("forecast-init-date-picker", "disabled_days")],
        [Input("page-load-trigger", "data")],
    )
    def update_forecast_start_dates(_) -> list[list[str], str|None, str|None, str|None, pd.DatetimeIndex|None]:
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
        forecast_start_dates = sorted(get_all_forecast_start_dates(CATALOG_PATH, collection_id="north"))

        if forecast_start_dates:
            # Define start and end dates for available IceNet forecasts
            logging.debug("Forecast start dates available:", forecast_start_dates)
            # Note to self: Dates should be in format 'YYYY-MM-DD'
            min_date_allowed=forecast_start_dates[0]
            max_date_allowed=forecast_start_dates[-1]
            initial_visible_month=max_date_allowed

            logging.debug("min_date_allowed", min_date_allowed)
            logging.debug("max_date_allowed", max_date_allowed)

            # Create list of days we don't have forecasts for, so, we can disable them in date picker.
            date_range = pd.date_range(min_date_allowed, max_date_allowed, freq="D")
            disabled_days = date_range[~date_range.isin(forecast_start_dates)]
            logging.debug(f"Creating list of dates starting from {min_date_allowed} to {max_date_allowed}")
            logging.debug("Disabled days:", disabled_days)
        else:
            min_date_allowed = None
            max_date_allowed = None
            initial_visible_month = None
            disabled_days = None
            logging.debug("No forecast dates loaded, issue connecting to/loading STAC Catalog?")

        return [
            forecast_start_dates,
            min_date_allowed,
            max_date_allowed,
            initial_visible_month,
            disabled_days
        ]

    @app.callback(
        Output("cog-results-layer", "children"),
        Input("colormap-dropdown", "value"),
        Input("forecast-init-date-picker", "date"),
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

            print(f"Selected item {forecast_start_date}")
            if not forecast_start_date:
                return no_update  # No tiles to display

            selected_item = get_cog_path(CATALOG_PATH, collection_id, forecast_start_date, leadtime)
            if selected_item:
                logging.debug("This is the selected_item:", selected_item, "in collection:", collection_id)

                # Get the tile URL from Titiler
                tile_url = get_tile_url(selected_item) + f"&colormap_name={colormap}&rescale=0,1"
                tile_url = normalise_url_path(tile_url)
                logging.debug("tile_url:", tile_url)

                collection_layer = dl.Overlay(
                    dl.TileLayer(
                        id={
                            'type': 'cog-collections',
                            'index': i
                        },
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


    @app.callback(Output({'type': 'cog-collections', 'index': ALL}, 'opacity'), Input("opacity-slider", "value"), State({'type': 'cog-collections', 'index': ALL}, 'opacity'))
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

        return [opacity]*len(current_opacity)
