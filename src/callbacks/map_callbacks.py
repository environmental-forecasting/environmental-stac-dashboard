import logging

import dash_leaflet as dl
import requests
from config import CATALOG_PATH, DATA_URL, TITILER_URL
from dash import ALL, MATCH, Input, Output, State, no_update
from stac.process import get_cog_path, get_collections, get_leadtime

COG_FILENAME = "sample.tif"

import os
from urllib.parse import urlparse, urlunparse

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

    # Rebuild and return the normalized URL
    return urlunparse(parts._replace(path=normalised_path))


# Function to generate tile URL for a STAC Item
def get_tile_url(cog_path):
    cog_path = normalise_url_path(f"{DATA_URL}/{cog_path}")
    return f"{TITILER_URL}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?url={cog_path}"

# Function to generate tile URL for a STAC Item
# def get_tile_url(stac_item):
#     print("stac_item:", stac_item)
#     stac_item_url = stac_item.get_self_href()
#     print("stac_item_url:", stac_item_url)
#     # return f"{TITILER_URL}/stac/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?url={stac_item_url}&assets=cog"
#     # stac_item_url = "http://localhost:8002/data/stac/north/forecast-2024-11-12/leadtime-0/leadtime-0.json"
#     return f"{TITILER_URL}/stac/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?url={stac_item_url}&assets=geotiff"

# # Load the STAC catalog
# import pystac
# catalog = pystac.Catalog.from_file("http://localhost:8002/data/stac/catalog.json")
# items = list(catalog.get_all_items())

# Callback function that will update the output container based on input
def register_callbacks(app):

    @app.callback(Output("cog-results-layer", "children"), Input("colormap-dropdown", "value"), Input("forecast-init-date-picker", "date"), Input("leadtime-slider", "value"), prevent_initial_call=True)
    def update_cog_layer(colormap, forecast_start_date, leadtime=0):
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



        # # Standard COG endpoint
        # cog_tile_url = f"{TITILER_URL}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?url={COG_FILENAME}&colormap_name={colormap}&rescale=0,1"

        # STAC + TileJSON endpoint
        # request_url = f"{TITILER_URL}/tiles/{hemisphere}/{forecast_date}/{leadtime}/tilejson.json"
        # tilejson = requests.get(request_url).json()
        # cog_tile_url = tilejson["tiles"][0] + f"&colormap_name={colormap}&rescale=0,1"

        # request_url = f"{TITILER_URL}/stac/forecast-{forecast_date}/tilejson.json"
        # tilejson = requests.get(request_url).json()
        # print(tilejson)
        # cog_tile_url = tilejson["tiles"][0] + f"&colormap_name={colormap}&rescale=0,1"
        # print(colormap, cog_tile_url)

        # return cog_tile_url

        # # request_url = f"{TITILER_URL}/stac/forecast-{forecast_date}/tilejson.json"
        # request_url = f"{TITILER_URL}/stac/WebMercatorQuad/tilejson.json"
        # # request_url = f"{TITILER_URL}/stac/tiles/forecast-{forecast_date}/tilejson.json"
        # return request_url

    @app.callback(Output({'type': 'cog-collections', 'index': ALL}, 'opacity'), Input("opacity-slider", "value"), State({'type': 'cog-collections', 'index': ALL}, 'opacity'))
    def update_cog_layer_opacity(opacity, current_opacity):
        logging.debug(f"Opacity changed to {opacity}")

        return [opacity]*len(current_opacity)
