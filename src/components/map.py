import dash_leaflet as dl
from dash import dcc, html
from rio_tiler.colormap import ColorMaps

# Default settings
DEFAULT_CENTER = [0, 0]
DEFAULT_ZOOM = 2

def get_colormaps() -> list[str]:
    """
    Returns the list of available colormaps.

    Returns:
        A list of available colormap names.
    """
    AVAILABLE_COLORMAPS = ColorMaps().list()
    return AVAILABLE_COLORMAPS

variables = ["SIC Mean"]
AVAILABLE_COLORMAPS = get_colormaps()

leaflet_map = html.Div(
    # style={'width': 'inherit', 'height': 'inherit'},
    style={"width": "inherit", "height": "inherit", "position": "relative"},
    children=[
        dl.Map(
            [
                dl.TileLayer(id="map-base-layer", attribution=("© OpenStreetMap contributors"), zIndex=0),
                dl.LayersControl([], id="cog-results-layer"),
                # dl.Colorbar(
                #     id="cbar",
                #     width=150,
                #     height=20,
                #     style={"margin-left": "40px"},
                #     position="bottomleft",
                # ),
                dl.ScaleControl(position="bottomright"),
                dl.FullScreenControl(),
            ],
            crs="EPSG3857",
            attributionControl=True,
            style={"width": "inherit", "height": "inherit"},
            center=DEFAULT_CENTER,
            zoom=DEFAULT_ZOOM,
            id="map",
        ),
        # Controls for map manipulation
        html.Div(
            [
                html.Label("Select Forecast Start:"),
                # dmc.DatePickerInput(w=200, numberOfColumns=1),
                dcc.DatePickerSingle(
                    id="forecast-init-date-picker",
                    # min_date_allowed=min_date_allowed,
                    # max_date_allowed=max_date_allowed,
                    # initial_visible_month=initial_visible_month,
                    display_format="YYYY-MM-DD",
                    # disabled_days=disabled_days,
                    # start_date_placeholder_text='MMM Do, YY'
                ),
                html.Label("Select Variable:"),
                dcc.Dropdown(
                    id="variable-dropdown",
                    options=[{"label": var, "value": var} for var in variables],
                    value=variables[0],
                    clearable=False,
                ),
                html.Label("Select Colormap:"),
                dcc.Dropdown(
                    id="colormap-dropdown",
                    options=[{"label": col, "value": col} for col in AVAILABLE_COLORMAPS],
                    value="blues_r",
                    clearable=False,
                ),
                html.Label("Opacity Control:"),
                dcc.Slider(
                    id="opacity-slider",
                    min=0.0,
                    max=1.0,
                    # step=0.1,
                    value=1.0,
                    updatemode="drag",
                    persistence="True",
                    persistence_type="memory",
                    # marks={0: '0', 0.2: '0.2', 0.4: '0.4', 0.6: '0.6', 0.8: '0.8', 1: '1'},
                ),
                html.Label("Leadtime:"),
                dcc.Slider(
                    id="leadtime-slider",
                    min=0,
                    max=92,
                    step=1,
                    value=0,
                    updatemode="drag",
                    persistence="True",
                    persistence_type="memory",
                    marks=None,
                    tooltip={"placement": "bottom", "always_visible": True},
                ),
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
                "zIndex": 1000,  # Ensure controls are on top of the map
            },
        ),
        dcc.Store(id='forecast-start-dates-store', data=None),
    ],
)
