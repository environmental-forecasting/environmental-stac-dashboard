import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from components import footer, header, map, sidebar
from dash import _dash_renderer, dcc, html
from dash_extensions import EventListener
from dash_iconify import DashIconify

_dash_renderer._set_react_version("18.2.0")
event = {"event": "click", "props": ["srcElement.className", "srcElement.innerText"]}

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
            dcc.Store(id="window-width"),
            dcc.Interval(id="interval", interval=10000, n_intervals=0), # Check if width needs updating every 10s.
            html.Div(id="output"),
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
                                    dmc.Paper(
                                        shadow="md",
                                        radius="md",
                                        withBorder=True,
                                        p="md",
                                        style={
                                            "position": "absolute",
                                            "bottom": "15px",
                                            "left": "50%",
                                            "transform": "translateX(-50%)",
                                            "width": "90%",
                                            "zIndex": 9999,
                                            "display": "none",  # Shown via callback
                                            "backgroundColor": "rgba(255, 255, 255, 0.9)",
                                        },
                                        id="time-slider-div",
                                        children=[
                                            dmc.Slider(
                                                id="leadtime-slider",
                                                min=0, # Stub
                                                max=1, # Stub
                                                step=1,
                                                value=0,
                                                # marks=[
                                                #     {"value": i, "label": f"{i}h"}
                                                #     for i in range(0, 24, 3)
                                                # ],
                                                # thumbChildren=DashIconify(icon="hugeicons:circle-arrow-down-double", width=25),
                                                thumbChildren=DashIconify(icon="ic:round-keyboard-double-arrow-down", width=25),
                                                thumbSize=25,
                                                styles={"thumb": {"borderWidth": 0, "padding": 0, "margin": 0}},
                                                size="lg",
                                                color="black",
                                                showLabelOnHover=True,
                                                labelAlwaysOn=False,
                                                persistence=True,
                                                persistence_type="session",
                                            ),
                                            dmc.Text(
                                                id="selected-time",
                                                ta="center",
                                                variant="gradient",
                                                gradient={"from": "red", "to": "yellow", "deg": 45},
                                                size="lg",
                                                mt="xl",
                                            ),
                                        ],
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
