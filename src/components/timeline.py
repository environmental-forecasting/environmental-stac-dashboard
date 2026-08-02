"""Fixed-height forecast timeline below the map."""

import dash_mantine_components as dmc
from dash import dcc, html
from dash_iconify import DashIconify

# Shared HTML colourbar (horizontal in the timeline).
_blues_r = [
    "#f7fbff",
    "#deebf7",
    "#c6dbef",
    "#9ecae1",
    "#6baed6",
    "#4292c6",
    "#2171b5",
    "#08519c",
    "#08306b",
]
_blues_r = list(reversed(_blues_r))


def _icon_button(button_id: str, icon: str, title: str) -> html.Button:
    return html.Button(
        DashIconify(icon=icon, width=18, height=18),
        id=button_id,
        type="button",
        title=title,
        n_clicks=0,
        className="forecast-timeline__btn",
    )


timeline_bar = html.Div(
    [
        html.Div(
            [
                html.Div(
                    [
                        html.Div(
                            id="forecast-cbar",
                            className="forecast-cbar forecast-cbar--inline",
                            children=[
                                html.Span(
                                    id="forecast-cbar-min",
                                    className="forecast-cbar__label",
                                    children="0",
                                ),
                                html.Div(
                                    id="forecast-cbar-ramp",
                                    className="forecast-cbar__ramp",
                                    style={
                                        "background": (
                                            "linear-gradient(to right, "
                                            f"{', '.join(_blues_r)})"
                                        ),
                                    },
                                ),
                                html.Span(
                                    id="forecast-cbar-max",
                                    className="forecast-cbar__label",
                                    children="1",
                                ),
                            ],
                        ),
                        html.Div(
                            [
                                html.Div(
                                    id="selected-time",
                                    className="forecast-timeline__valid",
                                    children="Select a forecast start",
                                ),
                                html.Div(
                                    id="leadtime-step-subtitle",
                                    className="forecast-timeline__subtitle",
                                    children="",
                                ),
                            ],
                            className="forecast-timeline__labels",
                        ),
                    ],
                    className="forecast-timeline__left",
                ),
                html.Div(
                    [
                        _icon_button(
                            "leadtime-first",
                            "tabler:player-skip-back",
                            "First leadtime",
                        ),
                        _icon_button(
                            "leadtime-prev",
                            "tabler:player-track-prev",
                            "Previous leadtime",
                        ),
                        html.Button(
                            DashIconify(
                                id="leadtime-play-icon",
                                icon="tabler:player-play",
                                width=20,
                                height=20,
                            ),
                            id="leadtime-play",
                            type="button",
                            title="Play or pause",
                            n_clicks=0,
                            className="forecast-timeline__btn forecast-timeline__btn--play",
                        ),
                        _icon_button(
                            "leadtime-next",
                            "tabler:player-track-next",
                            "Next leadtime",
                        ),
                        _icon_button(
                            "leadtime-last",
                            "tabler:player-skip-forward",
                            "Last leadtime",
                        ),
                    ],
                    className="forecast-timeline__transport",
                ),
                html.Div(
                    [
                        html.Span("Speed", className="forecast-timeline__speed-label"),
                        dcc.RadioItems(
                            id="leadtime-pace",
                            options=[
                                {"label": "Slow", "value": 1500},
                                {"label": "Normal", "value": 750},
                                {"label": "Fast", "value": 350},
                            ],
                            value=750,
                            inline=True,
                            # Same pill highlight as the header TMS / view-mode selector.
                            className="forecast-map-view-mode",
                        ),
                        dcc.Input(
                            id="leadtime-pace-custom",
                            type="number",
                            min=100,
                            max=5000,
                            step=50,
                            placeholder="ms",
                            debounce=True,
                            className="forecast-timeline__speed-custom",
                        ),
                    ],
                    className="forecast-timeline__right",
                ),
            ],
            className="forecast-timeline__row",
        ),
        dmc.Slider(
            id="leadtime-slider",
            min=0,
            max=1,
            step=1,
            value=0,
            thumbSize=18,
            size="sm",
            color="blue",
            showLabelOnHover=True,
            labelAlwaysOn=False,
            className="forecast-timeline__scrubber",
        ),
        dcc.Interval(
            id="leadtime-play-interval",
            interval=750,
            n_intervals=0,
            disabled=True,
        ),
        dcc.Store(id="leadtime-playing", data=False),
        dcc.Store(id="leadtime-pace-ms", data=750),
        dcc.Store(id="leadtime-step-unit", data="day"),
        dcc.Store(id="leadtime-bounds", data={"min": 0, "max": 0}),
        dcc.Store(id="leadtime-keys-bound", data=False),
    ],
    id="time-slider-div",
    className="forecast-timeline forecast-chrome forecast-timeline--idle",
)
