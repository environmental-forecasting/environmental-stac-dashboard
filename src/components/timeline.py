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
                        html.Div(
                            id="forecast-cbar",
                            className="forecast-cbar forecast-cbar--inline",
                            children=[
                                html.Button(
                                    "Auto",
                                    id="colorbar-range-reset",
                                    type="button",
                                    title="Reset colour range from data",
                                    n_clicks=0,
                                    disabled=True,
                                    className="forecast-cbar__auto",
                                ),
                                dcc.Input(
                                    id="fixed-min",
                                    type="text",
                                    inputMode="decimal",
                                    placeholder="min",
                                    debounce=True,
                                    className="forecast-cbar__value",
                                ),
                                html.Div(
                                    dmc.Popover(
                                        id="colorbar-range-popover",
                                        opened=False,
                                        position="top-end",
                                        withArrow=True,
                                        shadow="md",
                                        offset=8,
                                        zIndex=12000,
                                        withinPortal=True,
                                        closeOnClickOutside=True,
                                        closeOnEscape=True,
                                        children=[
                                            dmc.PopoverTarget(
                                                html.Button(
                                                    id="forecast-cbar-ramp",
                                                    type="button",
                                                    title="Adjust colour range",
                                                    n_clicks=0,
                                                    className="forecast-cbar__ramp",
                                                    style={
                                                        "background": (
                                                            "linear-gradient(to right, "
                                                            f"{', '.join(_blues_r)})"
                                                        ),
                                                    },
                                                ),
                                                boxWrapperProps={
                                                    "w": "100%",
                                                    "style": {
                                                        "flex": "1 1 auto",
                                                        "minWidth": 0,
                                                    },
                                                },
                                            ),
                                            dmc.PopoverDropdown(
                                                [
                                                    html.Div(
                                                        "Colour range",
                                                        className="forecast-cbar-slider__title",
                                                    ),
                                                    html.Div(
                                                        id="colorbar-range-slider-wrap",
                                                        className="forecast-cbar-slider-wrap",
                                                        children=[
                                                            dmc.RangeSlider(
                                                                id="colorbar-range-slider",
                                                                value=[0.0, 1.0],
                                                                min=0.0,
                                                                max=1.0,
                                                                step=0.01,
                                                                minRange=0.01,
                                                                precision=2,
                                                                size="md",
                                                                thumbSize=16,
                                                                labelAlwaysOn=True,
                                                                className="forecast-cbar-slider",
                                                            ),
                                                        ],
                                                    ),
                                                ],
                                                className="forecast-cbar-slider__dropdown",
                                            ),
                                        ],
                                    ),
                                    className="forecast-cbar__ramp-wrap",
                                ),
                                dcc.Input(
                                    id="fixed-max",
                                    type="text",
                                    inputMode="decimal",
                                    placeholder="max",
                                    debounce=True,
                                    className="forecast-cbar__value",
                                ),
                            ],
                        ),
                    ],
                    className="forecast-cbar-block",
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
        dcc.Store(id="leadtime-step-unit", data="day"),
        dcc.Store(id="leadtime-bounds", data={"min": 0, "max": 0}),
        dcc.Store(id="leadtime-keys-bound", data=False),
        dcc.Store(id="map-style-refresh", data=None),
    ],
    id="time-slider-div",
    className="forecast-timeline forecast-chrome forecast-timeline--idle",
)
