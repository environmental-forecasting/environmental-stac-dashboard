import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from components import footer, header, map, sidebar
from dash import _dash_renderer, dcc, html

_dash_renderer._set_react_version("18.2.0")

layout = dmc.MantineProvider(
    dbc.Container(
        className="g-0",
        fluid=True,
        style={
            "height": "100vh",  # Ensure the row takes up full viewport height
            "display": "flex",  # Use flexbox for the row layout
            "flexDirection": "column",  # Stack children vertically
        },
        children=[
            dcc.Store(id="page-load-trigger", data=True),
            dbc.Row(dbc.Col(header.header_layout, width=12)),
            dbc.Row(
                [
                    # dbc.Col(sidebar.sidebar_layout, width=0),
                    dbc.Col(
                        [
                            html.Div(
                                [
                                    # Main map
                                    map.leaflet_map,
                                    # Floating time slider overlay
                                    html.Div(
                                        [
                                            dcc.Slider(
                                                id="leadtime-slider",
                                                min=0, # Stub
                                                max=1, # Stub
                                                step=1,
                                                value=0,
                                                # marks={i: f"{i}" for i in range(0, 93, 5)},
                                                # tooltip={"placement": "bottom", "always_visible": False},
                                                updatemode="drag",
                                            ),
                                            html.Div(
                                                id="custom-tooltip",
                                                style={
                                                    "textAlign": "center",
                                                    "marginTop": "5px",
                                                    "color": "black",
                                                    "fontWeight": "bold",
                                                    "fontSize": "16px",
                                                },
                                            ),
                                            html.Div(
                                                id="selected-time",
                                                style={
                                                    "textAlign": "center",
                                                    "marginTop": "10px",
                                                    "color": "white",
                                                },
                                            ),
                                        ],
                                        style={
                                            "position": "absolute",
                                            "display": "none",
                                            "bottom": "15px",
                                            "left": "50%",
                                            "transform": "translateX(-50%)",
                                            "width": "90%",
                                            "backgroundColor": "rgba(255, 255, 255, 0.8)",
                                            "padding": "60px 15px 0px",
                                            "borderRadius": "10px",
                                            "zIndex": 9999,
                                        },
                                        id="time-slider-div",
                                    ),
                                ],
                                style={
                                    "position": "relative",
                                    "height": "100%",  # Let the map fill the parent container
                                    "flex": "1",  # Make sure the map takes available space in the column
                                },
                            ),
                        ],
                        width=12,
                    ),
                ],
                className="g-0",
                style={
                    "height": "100vh",  # Ensure the row takes up full viewport height
                    "display": "flex",  # Use flexbox for the row layout
                    "flexDirection": "row",  # Stack children horizontally
                },
            ),

            dbc.Row(dbc.Col(footer.footer_layout, width=12)),
        ],
    )
)
