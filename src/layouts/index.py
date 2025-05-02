from components import footer, header, sidebar, map
from dash import dcc, html, _dash_renderer
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc

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
                    dbc.Col(sidebar.sidebar_layout, width=2),
                    dbc.Col(
                        html.Div(
                            map.leaflet_map,
                            style={
                                "height": "100%",  # Let the map fill the parent container
                                "flex": "1",  # Make sure the map takes available space in the column
                            },
                        ),
                        width=10,
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
