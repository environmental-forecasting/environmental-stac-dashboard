"""Map hosts and shared map stores. View-mode pills live in the header."""

import dash_leaflet as dl
from dash import dcc, html
from map.state import initial_map_state

# Default settings
DEFAULT_CENTER = [0, 0]
DEFAULT_ZOOM = 2

# Leaflet host (hidden unless the Leaflet view mode is selected).
# Colourbar lives in the timeline (shared HTML ramp), not on the map face.
_leaflet_map = dl.Map(
    [
        dl.TileLayer(
            id="map-base-layer",
            attribution=("© OpenStreetMap contributors"),
            zIndex=0,
        ),
        dl.LayersControl([], id="cog-results-layer"),
        dl.ScaleControl(position="bottomright"),
        dl.FullScreenControl(position="bottomleft"),
    ],
    crs="EPSG3857",
    attributionControl=True,
    style={"width": "inherit", "height": "inherit"},
    center=DEFAULT_CENTER,
    zoom=DEFAULT_ZOOM,
    zoomDelta=0.1,
    zoomSnap=0.1,
    id="map",
)

leaflet_map = html.Div(
    className="forecast-map-root",
    children=[
        html.Div(
            className="forecast-map-hosts",
            children=[
                html.Div(
                    id="forecast-map-ol",
                    className="forecast-map-host",
                ),
                html.Div(
                    id="forecast-map-globe",
                    className="forecast-map-host forecast-map-host--hidden",
                ),
                html.Div(
                    id="forecast-map-leaflet",
                    className="forecast-map-host forecast-map-host--hidden",
                    children=[_leaflet_map],
                ),
            ],
        ),
        dcc.Store(id="forecast-dates-store", data=None),
        dcc.Store(id="fix-colorbar-range", data=None),
        dcc.Store(id="rescale-store", data=None),
        dcc.Store(id="map-state", data=initial_map_state()),
        dcc.Store(id="map-bridge-tick", data=0),
    ],
)
