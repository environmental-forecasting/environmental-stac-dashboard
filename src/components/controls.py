"""Right-hand forecast controls column (layout sibling of the map)."""

import dash_mantine_components as dmc
from dash import dcc, html
from rio_tiler.colormap import ColorMaps

AVAILABLE_COLORMAPS = ColorMaps().list()
DEFAULT_COLORMAP = "blues_r"

controls_panel = html.Div(
    [
        html.Div(
            [
                html.Span("Forecast controls", className="forecast-controls__title"),
            ],
            className="forecast-controls__header",
        ),
        html.Label("Collection"),
        dcc.Dropdown(
            id="collections-dropdown",
            options=[],
            multi=True,
            placeholder="Select one or more collections",
            className="forecast-controls__dropdown",
        ),
        html.Label("Forecast start"),
        dmc.DatePickerInput(
            id="forecast-init-date-picker",
            value=None,
            clearable=True,
            placeholder="Select",
            size="sm",
            w="100%",
            popoverProps={"zIndex": 10000},
            className="forecast-controls__datepicker",
        ),
        html.Label("Variable"),
        dcc.Dropdown(
            id="variable-dropdown",
            value=None,
            clearable=False,
            placeholder="Select a variable",
            className="forecast-controls__dropdown",
        ),
        html.Label("Colormap"),
        dcc.Dropdown(
            id="colormap-dropdown",
            options=[{"label": col, "value": col} for col in AVAILABLE_COLORMAPS],
            value=DEFAULT_COLORMAP,
            clearable=False,
            className="forecast-controls__dropdown",
        ),
        html.Label("Colourbar range"),
        html.Div(
            [
                html.Div(
                    [
                        dcc.Input(
                            id="fixed-min",
                            type="number",
                            placeholder="min",
                            debounce=True,
                            className="forecast-controls__number",
                        ),
                        dcc.Input(
                            id="fixed-max",
                            type="number",
                            placeholder="max",
                            debounce=True,
                            className="forecast-controls__number",
                        ),
                    ],
                    className="forecast-controls__minmax",
                ),
                html.Button(
                    "Fix colourbar range",
                    id="fix-colorbar-button",
                    n_clicks=0,
                    type="button",
                    className="forecast-controls__action",
                ),
            ],
        ),
    ],
    id="controls",
    className="forecast-controls-panel forecast-chrome",
)
