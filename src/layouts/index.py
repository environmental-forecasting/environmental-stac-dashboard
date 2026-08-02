import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from components import controls, footer, header, map, timeline
from dash import _dash_renderer, dcc, html
from dash_iconify import DashIconify

_dash_renderer._set_react_version("18.2.0")

layout = dmc.MantineProvider(
    dbc.Container(
        className="g-0 app-shell",
        fluid=True,
        children=[
            dcc.Store(id="window-width"),
            dcc.Store(id="page-load-trigger", data=True),
            dcc.Store(id="controls-open", data=True),
            html.Div(header.header_layout, className="app-shell__header"),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                map.leaflet_map,
                                className="forecast-map-column__map",
                            ),
                            timeline.timeline_bar,
                        ],
                        className="forecast-map-column",
                    ),
                    html.Button(
                        DashIconify(
                            id="controls-seam-icon",
                            icon="tabler:chevron-right",
                            width=16,
                            height=16,
                        ),
                        id="controls-seam",
                        type="button",
                        title="Show or hide forecast controls",
                        n_clicks=0,
                        className="forecast-controls-seam forecast-chrome",
                    ),
                    html.Div(
                        controls.controls_panel,
                        id="controls-column",
                        className="forecast-controls-column",
                    ),
                ],
                className="app-shell__main",
            ),
            html.Div(footer.footer_layout, className="app-shell__footer"),
        ],
    )
)
