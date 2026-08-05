"""App header: brand, map view-mode pills, and BAS links."""

import dash_bootstrap_components as dbc
from dash import dcc, html

header_layout = html.Div(
    className="forecast-header",
    children=[
        html.A(
            "IceNet",
            href="https://icenet.ai",
            className="forecast-header__brand",
            target="_blank",
            rel="noopener noreferrer",
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
            className="forecast-header__view-mode",
            title="Switch map projection. Click the active option again to reset the view.",
        ),
        dbc.DropdownMenu(
            nav=False,
            align_end=True,
            label=html.Span(
                [
                    html.Span(
                        "Part of British Antarctic Survey",
                        className="forecast-header__bas-full",
                    ),
                    html.Span("BAS", className="forecast-header__bas-short"),
                ],
                className="forecast-header__bas-label",
            ),
            toggle_style={
                "border": 0,
                "padding": "0.25rem 0.5rem",
                "fontSize": "0.85rem",
                "color": "#c5cede",
                "background": "transparent",
            },
            class_name="forecast-header__bas",
            children=[
                dbc.DropdownMenuItem("British Antarctic Survey", header=True),
                dbc.DropdownMenuItem("BAS Home", href="https://www.bas.ac.uk/"),
                dbc.DropdownMenuItem(
                    "Discover BAS Data", href="https://data.bas.ac.uk/"
                ),
            ],
        ),
    ],
)
