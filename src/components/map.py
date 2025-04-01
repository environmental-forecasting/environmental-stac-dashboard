import datetime as dt
import logging
import sys

import dash_leaflet as dl
import dash_mantine_components as dmc
import pandas as pd
import pystac
import requests
from config import CATALOG_PATH, TITILER_URL
from dash import dcc, html
from rio_tiler.colormap import ColorMaps
from stac.process import get_all_forecast_start_dates

# Default settings
DEFAULT_CENTER = [0, 0]
DEFAULT_ZOOM = 2

def get_colormaps():
    AVAILABLE_COLORMAPS = ColorMaps().list()
    try:
        # Get from Titiler extended API if available
        url = f"{TITILER_URL}/utils/colormaps"
        response = requests.get(url)
        if response.ok:
            AVAILABLE_COLORMAPS = sorted(response.json())
    except requests.exceptions.RequestException:
        print("No response...")
    return AVAILABLE_COLORMAPS

forecast_start_dates = sorted(get_all_forecast_start_dates(CATALOG_PATH, hemisphere="north"))
items = []

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


variables = ["SIC Mean", "SIC Stddev"]
AVAILABLE_COLORMAPS = get_colormaps()

leaflet_map = html.Div(
    # style={'width': 'inherit', 'height': 'inherit'},
    style={"width": "inherit", "height": "inherit", "position": "relative"},
    children=[
        dl.Map(
            [
                dl.LayersControl(
                    [
                        dl.BaseLayer(
                            dl.TileLayer(attribution=("© OpenStreetMap contributors"), zIndex=0),
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
                html.Label("Select Forecast Start Date:"),
                # dmc.DatePickerInput(w=200, numberOfColumns=1),
                dcc.DatePickerSingle(
                    id="forecast-init-date-picker",
                    min_date_allowed=min_date_allowed,
                    max_date_allowed=max_date_allowed,
                    initial_visible_month=initial_visible_month,
                    display_format='YYYY-MM-DD',
                    disabled_days=disabled_days,
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
    ],
)
