"""Map hosts and shared map stores. View-mode pills live in the header."""

import dash_leaflet as dl
from dash import dcc, html
from dash_iconify import DashIconify
from map.state import initial_map_state

# Default settings
DEFAULT_CENTER = [0, 0]
DEFAULT_ZOOM = 2

# Leaflet host (hidden unless the Leaflet view mode is selected).
# Colourbar lives in the timeline (shared HTML ramp), not on the map face.
# Search highlight: polygons use ``style``; points use Leaflet's default marker.
_leaflet_map = dl.Map(
    [
        dl.TileLayer(
            id="map-base-layer",
            attribution=("© OpenStreetMap contributors"),
            zIndex=0,
        ),
        dl.LayersControl([], id="cog-results-layer"),
        dl.GeoJSON(
            id="map-search-highlight",
            data=None,
            zoomToBounds=False,
            style={
                "color": "#5b8def",
                "weight": 2.5,
                "opacity": 0.95,
                "fillColor": "#5b8def",
                "fillOpacity": 0.16,
            },
        ),
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
            [
                html.Span(className="forecast-busy__spinner", **{"aria-hidden": "true"}),
                html.Span(id="forecast-busy-label", children="Updating…"),
            ],
            id="forecast-busy",
            className="forecast-busy is-hidden",
            role="status",
            **{"aria-live": "polite"},
        ),
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
        # Place and lat, lon search box. Suggestions are resolved in Python.
        html.Div(
            [
                html.Button(
                    DashIconify(icon="tabler:search", width=18, height=18),
                    id="map-search-show",
                    n_clicks=0,
                    type="button",
                    className="forecast-map-search__show",
                    title="Show search",
                    **{"aria-label": "Show search"},
                ),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Button(
                                    DashIconify(
                                        icon="tabler:search", width=16, height=16
                                    ),
                                    id="map-search-hide",
                                    n_clicks=0,
                                    type="button",
                                    className="forecast-map-search__icon",
                                    title="Hide search",
                                    **{"aria-label": "Hide search"},
                                ),
                                dcc.Input(
                                    id="map-search-query",
                                    type="text",
                                    placeholder="Search or lat, lon",
                                    debounce=False,
                                    n_submit=0,
                                    className="forecast-map-search__input",
                                    autoComplete="off",
                                ),
                                html.Div(
                                    [
                                        html.Button(
                                            id="map-search-clear",
                                            n_clicks=0,
                                            type="button",
                                            className="forecast-map-search__clear",
                                            title="Clear",
                                            **{"aria-label": "Clear search"},
                                        ),
                                    ],
                                    className="forecast-map-search__actions",
                                ),
                            ],
                            id="map-search-field",
                            className="forecast-map-search__field",
                        ),
                        html.Div(
                            id="map-search-suggestions",
                            className="forecast-map-search__suggestions",
                            role="listbox",
                            # Sentinel so the pattern-matching click callback
                            # validates before the first search response.
                            children=[
                                html.Button(
                                    id={"type": "map-search-hit", "index": -1},
                                    n_clicks=0,
                                    type="button",
                                    className="forecast-map-search__hit",
                                    style={"display": "none"},
                                    tabIndex=-1,
                                )
                            ],
                        ),
                        html.Div(
                            id="map-search-status",
                            className="forecast-map-search__status",
                        ),
                        dcc.Store(id="map-search-debounced", data=None),
                        dcc.Store(id="map-search-hits", data=[]),
                        dcc.Store(id="map-search-committed", data=None),
                    ],
                    id="map-search",
                    className="forecast-map-search",
                ),
            ],
            id="map-search-shell",
            className="forecast-map-search-shell",
        ),
        dcc.Store(id="forecast-dates-store", data=None),
        dcc.Store(
            id="display-style",
            data={
                "colormap": "blues_r",
                "vmin": 0.0,
                "vmax": 1.0,
                "domain_min": 0.0,
                "domain_max": 1.0,
                "locked": False,
                "source": "fallback",
            },
        ),
        dcc.Store(id="map-state", data=initial_map_state()),
        dcc.Store(id="map-view-presets", data={}),
        dcc.Store(id="map-bridge-tick", data=0),
        dcc.Store(id="map-goto", data=None),
    ],
)
