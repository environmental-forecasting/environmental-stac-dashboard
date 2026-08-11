"""Right-hand forecast controls column (layout sibling of the map)."""

import dash_mantine_components as dmc
from dash import dcc, html
from map.basemap import DEFAULT_BASEMAP_ID, list_basemap_options
from rio_tiler.colormap import ColorMaps

AVAILABLE_COLORMAPS = ColorMaps().list()
DEFAULT_COLORMAP = "blues_r"


def forecast_init_disabled_dates(allowed_days) -> dict:
    """
    Restrict the picker to these forecast start days.

    Send the available days, not every gap between the first and last init.
    A sparse archive over years stays small that way.
    """
    if not isinstance(allowed_days, dict):
        allowed_days = {day: True for day in allowed_days}
    return {
        "function": "disableUnlessForecastInit",
        "options": {"allowed": allowed_days},
    }


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
            disabledDates=forecast_init_disabled_dates(()),
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
        html.Label("Basemap"),
        dcc.Dropdown(
            id="basemap-style",
            options=list_basemap_options(),
            value=DEFAULT_BASEMAP_ID,
            clearable=False,
            className="forecast-controls__dropdown",
        ),
        html.Button(
            "Reset defaults",
            id="user-prefs-reset",
            n_clicks=0,
            type="button",
            title="Clear saved defaults and restore factory settings",
            disabled=True,
            className="forecast-controls__action forecast-controls__reset",
        ),
    ],
    id="controls",
    className="forecast-controls-panel forecast-chrome",
)
