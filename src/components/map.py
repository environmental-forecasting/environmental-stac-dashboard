import dash_leaflet as dl
import dash_mantine_components as dmc
from dash import dcc, html
from map.state import initial_map_state
from rio_tiler.colormap import ColorMaps

# Default settings
DEFAULT_CENTER = [0, 0]
DEFAULT_ZOOM = 2
AVAILABLE_COLORMAPS = ColorMaps().list()
DEFAULT_COLORMAP = "blues_r"

# Blues_r for colourbar which uses different input to titiler's approach to colour:
blues_r = [
    "#f7fbff",
    "#deebf7",
    "#c6dbef",
    "#9ecae1",
    "#6baed6",
    "#4292c6",
    "#2171b5",
    "#08519c",
    "#08306b",
]
blues_r.reverse()

# Shared HTML colourbar (visible for OpenLayers; Leaflet keeps dl.Colorbar too).
_forecast_cbar = html.Div(
    id="forecast-cbar",
    className="forecast-cbar",
    children=[
        html.Div(id="forecast-cbar-max", className="forecast-cbar__label", children="1"),
        html.Div(
            id="forecast-cbar-ramp",
            className="forecast-cbar__ramp",
            style={
                "background": f"linear-gradient(to top, {', '.join(blues_r)})",
            },
        ),
        html.Div(id="forecast-cbar-min", className="forecast-cbar__label", children="0"),
    ],
)

# Leaflet map (hidden while OpenLayers is the default engine).
_leaflet_map = dl.Map(
    [
        dl.TileLayer(
            id="map-base-layer",
            attribution=("© OpenStreetMap contributors"),
            zIndex=0,
        ),
        dl.LayersControl([], id="cog-results-layer"),
        dl.Colorbar(
            id="cbar",
            width=30,
            height=200,
            style={
                "opacity": "1.0",
                "backgroundColor": "rgba(255, 255, 255, 0.8)",
                "padding": "10px",
                "border-radius": "10px",
            },
            position="topleft",
            tooltip=True,
            colorscale=blues_r,
        ),
        dl.ScaleControl(position="bottomright"),
        dl.FullScreenControl(position="bottomleft"),
        # Settings control moved to a shared HTML button (see controls-btn below)
        # so it remains available when the Leaflet host is hidden.
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
    # style={'width': 'inherit', 'height': 'inherit'},
    className="forecast-map-root",
    style={"width": "inherit", "height": "inherit", "position": "relative"},
    children=[
        html.Div(
            className="forecast-map-hosts",
            children=[
                html.Div(
                    id="forecast-map-ol",
                    className="forecast-map-host",
                ),
                html.Div(
                    id="forecast-map-leaflet",
                    className="forecast-map-host forecast-map-host--hidden",
                    children=[_leaflet_map],
                ),
            ],
        ),
        html.Button(
            "⚙",
            id="controls-btn",
            className="forecast-map-settings-btn",
            title="controls",
            n_clicks=0,
            type="button",
        ),
        html.Div(
            dcc.RadioItems(
                id="map-view-mode",
                options=[
                    {"label": "Global", "value": "global_3857"},
                ],
                value="global_3857",
                inline=True,
                className="forecast-map-view-mode",
            ),
            className="forecast-map-view-mode-wrap",
        ),
        _forecast_cbar,
        # Controls for map manipulation
        html.Div(
            [
                html.Label("Select Collection:"),
                dcc.Dropdown(
                    id="collections-dropdown",
                    options=[],
                    multi=True,
                    placeholder="Select one or more collections",
                ),
                html.Label("Select Forecast Start:"),
                dmc.DatePickerInput(
                    id="forecast-init-date-picker",
                    value=None,
                    clearable=True,
                    placeholder="Select",
                    popoverProps={"zIndex": 10000},
                ),
                html.Label("Select Variable:"),
                dcc.Dropdown(
                    id="variable-dropdown",
                    # options=[{"label": var, "value": var} for var in VARIABLES],
                    # value=VARIABLES[0],
                    value=1,
                    clearable=False,
                ),
                html.Label("Select Colormap:"),
                dcc.Dropdown(
                    id="colormap-dropdown",
                    options=[
                        {"label": col, "value": col} for col in AVAILABLE_COLORMAPS
                    ],
                    value=DEFAULT_COLORMAP,
                    clearable=False,
                ),
                html.Label("Colorbar Control:"),
                html.Div([
                    html.Div([
                        dcc.Input(
                            id="fixed-min",
                            type="number",
                            placeholder="min",
                            debounce=True,
                            style={
                                "width": "100px",
                                "borderRadius": "5px",
                                "padding": "5px",
                                "border": "1px solid #ccc",
                            },
                        ),
                        dcc.Input(
                            id="fixed-max",
                            type="number",
                            placeholder="max",
                            debounce=True,
                            style={
                                "width": "100px",
                                "borderRadius": "5px",
                                "padding": "5px",
                                "border": "1px solid #ccc",
                            },
                        ),
                    ], style={
                        "display": "flex",
                        "gap": "10px",
                        "marginBottom": "10px",
                        "justifyContent": "space-between"
                    }),
                    html.Button(
                        "Fix colorbar range",
                        id="fix-colorbar-button",
                        n_clicks=0,
                        style={
                            "backgroundColor": "#f0f0f0",  # Colour for default (disabled) state
                            "border": "1px solid #ccc",
                            "padding": "8px 12px",
                            "borderRadius": "5px",
                            "cursor": "pointer",
                            "width": "100%",
                            "fontWeight": "500",
                            "fontSize": "14px",
                            "color": "#333",
                        },
                    ),
                ], style={}),
            ],
            style={
                "position": "absolute",
                "top": "20%",
                "right": "20px",
                "background": "rgba(255, 255, 255, 0.8)",
                "padding": "10px",
                "borderRadius": "10px",
                "boxShadow": "0 6px 8px rgba(0, 0, 0, 0.1)",
                "width": "250px",
                "display": "inline-block",
                "zIndex": 1000,  # Ensure controls are on top of the map
            },
            id="controls"
        ),
        dcc.Store(id="forecast-dates-store", data=None),
        dcc.Store(id="fix-colorbar-range", data=None),
        dcc.Store(id="rescale-store", data=None),
        dcc.Store(id="map-state", data=initial_map_state()),
        dcc.Store(id="map-bridge-tick", data=0),
    ],
)
