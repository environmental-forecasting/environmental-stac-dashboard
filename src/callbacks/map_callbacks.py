import logging
import requests

from dash import Input, Output

TITILER_URL = "http://localhost:8000"
COG_FILENAME = "sample.tif"


# Callback function that will update the output container based on input
def register_callbacks(app):
    @app.callback(Output("cog-map-layer", "url"), Input("colormap-dropdown", "value"))
    def update_cog_layer(colormap):
        hemisphere = "north"
        forecast_date = "2024-11-12"
        leadtime = 0
        logging.debug(f"Colormap changed to {colormap}")
        # Standard COG endpoint
        # cog_tile_url = f"{TITILER_URL}/cog/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}?url={COG_FILENAME}&colormap_name={colormap}&rescale=0,1"
        # STAC + TileJSON endpoint
        request_url = f"{TITILER_URL}/tiles/{hemisphere}/{forecast_date}/{leadtime}/tilejson.json"
        tilejson = requests.get(request_url).json()
        cog_tile_url = tilejson["tiles"][0] + f"&colormap_name={colormap}&rescale=0,1"
        print(colormap, cog_tile_url)

        return cog_tile_url

    @app.callback(Output("cog-map-layer", "opacity"), Input("opacity-slider", "value"))
    def update_cog_layer_opacity(opacity):
        logging.debug(f"Opacity changed to {opacity}")

        return opacity
