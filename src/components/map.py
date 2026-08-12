"""Map hosts and shared map stores. View-mode pills live in the header."""

from dash import dcc, html
from dash_iconify import DashIconify
from map.state import initial_map_state

# Colourbar lives in the timeline (shared HTML ramp), not on the map face.
forecast_map = html.Div(
    className="forecast-map-root",
    children=[
        html.Div(
            [
                html.Span(className="forecast-busy__spinner", **{"aria-hidden": "true"}),
                html.Span(id="forecast-busy-label", children="Updating…"),
            ],
            id="forecast-busy",
            className="forecast-busy is-hidden",
            role="status",
            **{"aria-live": "polite"},
        ),
        html.Div(
            className="forecast-map-hosts",
            children=[
                html.Div(
                    id="forecast-map-ol",
                    className="forecast-map-host",
                ),
                html.Div(
                    id="forecast-map-globe",
                    className="forecast-map-host forecast-map-host--hidden",
                ),
            ],
        ),
        # Place and lat, lon search box. Suggestions are resolved in Python.
        html.Div(
            [
                html.Button(
                    DashIconify(icon="tabler:search", width=18, height=18),
                    id="map-search-show",
                    n_clicks=0,
                    type="button",
                    className="forecast-map-search__show",
                    title="Show search",
                    **{"aria-label": "Show search"},
                ),
                html.Div(
                    [
                        html.Div(
                            [
                                html.Button(
                                    DashIconify(
                                        icon="tabler:search", width=16, height=16
                                    ),
                                    id="map-search-hide",
                                    n_clicks=0,
                                    type="button",
                                    className="forecast-map-search__icon",
                                    title="Hide search",
                                    **{"aria-label": "Hide search"},
                                ),
                                dcc.Input(
                                    id="map-search-query",
                                    type="text",
                                    placeholder="Search or lat, lon",
                                    debounce=False,
                                    n_submit=0,
                                    className="forecast-map-search__input",
                                    autoComplete="off",
                                ),
                                html.Div(
                                    [
                                        html.Button(
                                            DashIconify(
                                                icon="tabler:polygon",
                                                width=16,
                                                height=16,
                                            ),
                                            id="map-region-upload",
                                            n_clicks=0,
                                            type="button",
                                            className="forecast-map-search__region",
                                            title="Upload GeoJSON region",
                                            **{
                                                "aria-label": "Upload GeoJSON region"
                                            },
                                        ),
                                        html.Button(
                                            id="map-search-clear",
                                            n_clicks=0,
                                            type="button",
                                            className="forecast-map-search__clear",
                                            title="Clear",
                                            **{"aria-label": "Clear search"},
                                        ),
                                    ],
                                    className="forecast-map-search__actions",
                                ),
                            ],
                            id="map-search-field",
                            className="forecast-map-search__field",
                        ),
                        html.Div(
                            id="map-search-suggestions",
                            className="forecast-map-search__suggestions",
                            role="listbox",
                            # Sentinel so the pattern-matching click callback
                            # validates before the first search response.
                            children=[
                                html.Button(
                                    id={"type": "map-search-hit", "index": -1},
                                    n_clicks=0,
                                    type="button",
                                    className="forecast-map-search__hit",
                                    style={"display": "none"},
                                    tabIndex=-1,
                                )
                            ],
                        ),
                        html.Div(
                            id="map-search-status",
                            className="forecast-map-search__status",
                        ),
                        dcc.Store(id="map-search-debounced", data=None),
                        dcc.Store(id="map-search-hits", data=[]),
                        dcc.Store(id="map-search-committed", data=None),
                        dcc.Store(id="map-search-active", data=-1),
                    ],
                    id="map-search",
                    className="forecast-map-search",
                ),
            ],
            id="map-search-shell",
            className="forecast-map-search-shell",
        ),
        # Polar / custom EPSG: one-shot North up or continuous Keep N up.
        html.Div(
            [
                html.Button(
                    [
                        html.Span("N", className="forecast-map-north-up__glyph"),
                        html.Span("North up", className="forecast-map-north-up__label"),
                    ],
                    id="map-north-up-btn",
                    n_clicks=0,
                    type="button",
                    className="forecast-map-north-up__btn",
                    title=(
                        "Click the map to put north up at that point. "
                        "Press Esc to restore default orientation."
                    ),
                ),
                html.Button(
                    [
                        html.Span("L", className="forecast-map-north-up__glyph"),
                        html.Span("Keep N up", className="forecast-map-north-up__label"),
                    ],
                    id="map-north-up-lock-btn",
                    n_clicks=0,
                    type="button",
                    className="forecast-map-north-up__btn",
                    title=(
                        "Keep geographic north screen-up while panning and zooming. "
                        "Turn off to restore default orientation."
                    ),
                ),
            ],
            id="map-north-up-wrap",
            className="forecast-map-north-up is-hidden",
        ),
        dcc.Store(id="forecast-dates-store", data=None),
        dcc.Store(
            id="display-style",
            data={
                "colormap": "blues_r",
                "vmin": 0.0,
                "vmax": 1.0,
                "domain_min": 0.0,
                "domain_max": 1.0,
                "locked": False,
                "source": "fallback",
            },
        ),
        dcc.Store(id="map-state", data=initial_map_state()),
        dcc.Store(id="map-view-presets", data={}),
        dcc.Store(id="map-bridge-tick", data=0),
        dcc.Store(id="map-goto", data=None),
        # Lightweight region meta only (never the full GeoJSON).
        dcc.Store(id="map-region-meta", data=None),
    ],
)
