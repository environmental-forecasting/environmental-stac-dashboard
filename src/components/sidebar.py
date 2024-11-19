import dash_bootstrap_components as dbc
from dash import html

sidebar_layout = html.Div(
    [
        html.H2("", className="display-4"),
        html.Hr(),
        html.P("Options", className="lead"),
        dbc.Nav(
            [
                # dbc.NavLink("Home", href="/", active="exact"),
                # dbc.NavLink("Page 1", href="/page-1", active="exact"),
                # dbc.NavLink("Page 2", href="/page-2", active="exact"),
            ],
            vertical=True,
            pills=True,
        ),
    ],
    className="sidebar",
)
