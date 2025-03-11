import datetime as dt
import dash_leaflet as dl
import requests
from dash import dcc, html
import dash_mantine_components as dmc

# Default settings
DEFAULT_CENTER = [0, 0]
DEFAULT_ZOOM = 2
TITILER_URL = "http://localhost:8000"


def get_colormaps():
    AVAILABLE_COLORMAPS = ["blues_r", "cividis", "inferno", "magma", "plasma", "viridis"]
    try:
        url = f"{TITILER_URL}/utils/colormaps"
        response = requests.get(url)
        if response.ok:
            AVAILABLE_COLORMAPS = sorted(response.json())
    except requests.exceptions.RequestException:
        print("No response...")
    return AVAILABLE_COLORMAPS

def get_forecast_start_dates():
    try:
        url = f"{TITILER_URL}/manifest/forecast_start_dates"
        response  = requests.get(url)
        AVAILABLE_START_DATES  = sorted(response.json())
    except requests.exceptions.RequestException:
        print("No response...")
        AVAILABLE_START_DATES   = ["2024-11-12"]
    return AVAILABLE_START_DATES

def get_forecast_file(file_list, date, leadtime=0):
    try:
        url  = f"{TITILER_URL}/manifest/forecast_files"
        response   = requests.get(url)
        AVAILABLE_FILES    = sorted(response.json())
    except requests.exceptions.RequestException:
        print("No response...")

# Load the STAC catalog
import pystac
# catalog = pystac.Catalog.from_file("data/stac/catalog.json")
catalog = pystac.Catalog.from_file("http://localhost:8002/data/stac/catalog.json")
items = list(catalog.get_all_items())

variables = ["SIC Mean", "SIC Std Dev"]
AVAILABLE_COLORMAPS = get_colormaps()
AVAILABLE_START_DATES = get_forecast_start_dates()

leaflet_map = html.Div(
    # style={'width': 'inherit', 'height': 'inherit'},
    style={"width": "inherit", "height": "inherit", "position": "relative"},
    children=[
        dl.Map(
            [
                dl.LayersControl(
                    [
                        dl.BaseLayer(
                            dl.TileLayer(zIndex=0),
                            name="OpenStreetMap",
                            checked=True,
                        ),
                        dl.BaseLayer(
                            dl.TileLayer(
                                url="https://watercolormaps.collection.cooperhewitt.org/tile/watercolor/{z}/{x}/{y}.jpg",
                                minZoom=0,
                                maxZoom=20,
                                attribution=(
                                    "Map tiles by Stamen Design, under CC BY 3.0. Data by OpenStreetMap, under CC BY SA."
                                ),
                                zIndex=0,
                            ),
                            name="Stamen Watercolour",
                            checked=False,
                        ),
                        dl.BaseLayer(
                            dl.TileLayer(
                                url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                                minZoom=0,
                                maxZoom=20,
                                attribution=(
                                    r"Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community"
                                ),
                                zIndex=0,
                            ),
                            name="ESRI: World Imagery",
                            checked=False,
                        ),
                        dl.Overlay(
                            dl.TileLayer(id="cog-map-layer", zIndex=1, opacity=1.0,),
                            name="Results Layer",
                            checked=True,
                        ),
                    ]
                ),
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
                dcc.Dropdown(
                    id="stac-item-dropdown",
                    options=[{"label": item.id, "value": item.id} for item in items],
                    placeholder="Select a STAC Item"
                ),
                html.Label("Select Date:"),
                # dmc.DatePickerInput(w=200, numberOfColumns=1),
                dcc.DatePickerSingle(
                    id="forecast-init-date-picker",
                    min_date_allowed=dt.date(2020, 1, 1),
                    max_date_allowed=dt.datetime.today().date() - dt.timedelta(days=6),
                    initial_visible_month=dt.datetime.today().date(),
                    display_format='YYYY-MM-DD',
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
    ],
)
