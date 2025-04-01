import logging
import requests
from stac.process import get_cog_path, get_collections, get_leadtime
from dash import Input, Output, no_update
from config import CATALOG_PATH, DATA_URL, TITILER_URL

COG_FILENAME = "sample.tif"


# Function to generate tile URL for a STAC Item
def get_tile_url(cog_path):
    cog_path = f"{DATA_URL}/{cog_path}"
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
    @app.callback(Output("cog-map-layer", "url"), Input("colormap-dropdown", "value"), Input("forecast-init-date-picker", "date"), Input("leadtime-slider", "value"))
    def update_cog_layer(colormap, forecast_start_date, leadtime=0):
        hemisphere = "north"
        # forecast_date = "2024-11-12"
        # leadtime = 0
        logging.debug(f"Colormap changed to {colormap}")

        print(f"Selected item {forecast_start_date}")
        if not forecast_start_date:
            return no_update  # No tiles to display

        # # Find the selected item
        # selected_item = next((item for item in items if item.id == selected_item_id), None)
        # if not selected_item:
        #     return no_update
        # print(selected_item)
        # selected_item = get_leadtime(CATALOG_PATH, hemisphere, forecast_start_date, leadtime)
        selected_item = get_cog_path(CATALOG_PATH, hemisphere, forecast_start_date, leadtime)
        print("This is the selected_item:", selected_item)

        # Get the tile URL from Titiler
        tile_url = get_tile_url(selected_item) + f"&colormap_name={colormap}&rescale=0,1"
        print("tile_url:", tile_url)
        return tile_url



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

    @app.callback(Output("cog-map-layer", "opacity"), Input("opacity-slider", "value"))
    def update_cog_layer_opacity(opacity):
        logging.debug(f"Opacity changed to {opacity}")

        return opacity
