"""Callbacks for the map place-search box and its suggestion list."""

import time

import dash
from dash import ALL, Input, Output, State, callback_context, html, no_update
from dash.exceptions import PreventUpdate
from map.geocode import parse_lon_lat, place_search

_COORD_ZOOM = 14


def _search_hit_sentinel():
    """Hidden button so the patterned click callback always has a target."""
    return html.Button(
        id={"type": "map-search-hit", "index": -1},
        n_clicks=0,
        type="button",
        className="forecast-map-search__hit",
        style={"display": "none"},
        tabIndex=-1,
    )


def _label_parts(label: str) -> tuple[str, str]:
    """Split a display label into a title and a quieter location line."""
    text = (label or "").strip()
    if not text:
        return "", ""
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if len(parts) <= 1:
        return text, ""
    return parts[0], ", ".join(parts[1:])


def _suggestion_children(hits: list[dict], *, active_index: int = 0) -> list:
    """Build clickable suggestion rows for the search panel."""
    children = [_search_hit_sentinel()]
    for index, hit in enumerate(hits):
        classes = "forecast-map-search__hit"
        if index == active_index:
            classes += " is-active"
        title, meta = _label_parts(hit.get("label") or "")
        row = [
            html.Span(
                title or hit.get("label") or "",
                className="forecast-map-search__hit-title",
            )
        ]
        if meta:
            row.append(html.Span(meta, className="forecast-map-search__hit-meta"))
        children.append(
            html.Button(
                row,
                id={"type": "map-search-hit", "index": index},
                n_clicks=0,
                type="button",
                className=classes,
                title=hit.get("label") or title,
            )
        )
    return children


def _coord_hit(lon: float, lat: float) -> dict:
    """Build a suggestion for a typed coordinate pair."""
    return {
        "label": f"{lat:.4f}, {lon:.4f}",
        "lon": lon,
        "lat": lat,
        "zoom": _COORD_ZOOM,
        "source": "coords",
    }


def _closed_panel(status):
    """Outputs for an empty, closed suggestion panel."""
    return [_search_hit_sentinel()], [], status, "forecast-map-search"


def _map_search_suggest(debounced, committed, view_mode):
    """Build as-you-type suggestions from the debounced query."""
    q = ((debounced or {}).get("q") if isinstance(debounced, dict) else None) or ""
    q = q.strip()
    committed_q = (
        (committed or {}).get("q") if isinstance(committed, dict) else None
    ) or ""
    # Ignore the fill that follows a pick so the list does not reopen.
    # Leave status alone: the flyTo clientside owns the coverage warning.
    if q and q == committed_q.strip():
        return [_search_hit_sentinel()], [], no_update, "forecast-map-search"
    if len(q) < 2:
        return _closed_panel("")

    parsed = parse_lon_lat(q)
    if parsed is not None:
        lon, lat = parsed
        hits = [_coord_hit(lon, lat)]
        return (
            _suggestion_children(hits, active_index=0),
            hits,
            "",
            "forecast-map-search has-results",
        )

    finder = place_search()
    hits = finder.search(q, mode=view_mode)
    if not hits:
        return _closed_panel("No results")
    return (
        _suggestion_children(hits, active_index=0),
        hits,
        finder.attribution_for_hits(hits),
        "forecast-map-search has-results",
    )


def _map_search_commit(lon, lat, zoom, label, *, bbox=None, geojson=None):
    """Build a map-goto payload and close the suggestion panel."""
    text = (label or f"{lat:.4f}, {lon:.4f}").strip()
    goto = {"lon": lon, "lat": lat, "zoom": zoom, "ts": time.time()}
    if bbox:
        goto["bbox"] = bbox
    if geojson:
        goto["geojson"] = geojson
    return (
        goto,
        [_search_hit_sentinel()],
        [],
        no_update,
        "forecast-map-search",
        text,
        {"q": text, "ts": time.time()},
    )


def _map_search_choose(hit_clicks, n_submit, hits, query, view_mode):
    """Handle a suggestion click or Enter: emit map-goto for the clientside fly."""
    triggered = callback_context.triggered_id

    if triggered == "map-search-query":
        q = (query or "").strip()
        if not q:
            raise PreventUpdate
        parsed = parse_lon_lat(q)
        if parsed is not None:
            lon, lat = parsed
            return _map_search_commit(lon, lat, _COORD_ZOOM, _coord_hit(lon, lat)["label"])
        if hits:
            chosen = hits[0]
            return _map_search_commit(
                chosen["lon"],
                chosen["lat"],
                chosen.get("zoom", _COORD_ZOOM),
                chosen.get("label"),
                bbox=chosen.get("bbox"),
                geojson=chosen.get("geojson"),
            )
        looked = place_search().search(q, mode=view_mode, limit=1)
        if not looked:
            raise PreventUpdate
        hit = looked[0]
        return _map_search_commit(
            hit["lon"],
            hit["lat"],
            hit.get("zoom", _COORD_ZOOM),
            hit.get("label"),
            bbox=hit.get("bbox"),
            geojson=hit.get("geojson"),
        )

    if not isinstance(triggered, dict) or triggered.get("type") != "map-search-hit":
        raise PreventUpdate
    if not any(hit_clicks or []):
        raise PreventUpdate
    index = triggered.get("index")
    if (
        not isinstance(hits, list)
        or not isinstance(index, int)
        or index < 0
        or index >= len(hits)
    ):
        raise PreventUpdate
    hit = hits[index]
    return _map_search_commit(
        hit["lon"],
        hit["lat"],
        hit.get("zoom", _COORD_ZOOM),
        hit.get("label"),
        bbox=hit.get("bbox"),
        geojson=hit.get("geojson"),
    )


def _map_search_clear(n_clicks):
    """Reset the search box and clear any place highlight."""
    if not n_clicks:
        raise PreventUpdate
    return (
        "",
        None,
        [],
        [_search_hit_sentinel()],
        "",
        "forecast-map-search__status",
        "forecast-map-search",
        None,
        None,
    )


def register_callbacks(app: dash.Dash):
    """Register the place-search callbacks on ``app``."""
    # Wait for a pause in typing, then resolve suggestions in Python.
    app.clientside_callback(
        """
        function(query, committed) {
            if (window.__mapSearchDebounce) {
                clearTimeout(window.__mapSearchDebounce);
                window.__mapSearchDebounce = null;
            }
            var q = query || "";
            var picked = committed && committed.q != null ? String(committed.q) : "";
            // Ignore the fill after a pick so an outside-coverage warning stays.
            if (picked && q === picked) {
                return window.dash_clientside.no_update;
            }
            var trimmed = q.trim();
            var looksLikeCoords =
                /^-?\\d+(\\.\\d+)?\\s*,\\s*-?\\d+(\\.\\d+)?$/.test(trimmed);
            if (trimmed.length >= 2 && !looksLikeCoords) {
                window.dash_clientside.set_props("map-search-status", {
                    children: "Searching...",
                    className: "forecast-map-search__status",
                });
            }
            window.__mapSearchDebounce = setTimeout(function () {
                window.__mapSearchDebounce = null;
                window.dash_clientside.set_props("map-search-debounced", {
                    data: {q: q, ts: Date.now()},
                });
            }, 320);
            return window.dash_clientside.no_update;
        }
        """,
        Output("map-bridge-tick", "data", allow_duplicate=True),
        Input("map-search-query", "value"),
        State("map-search-committed", "data"),
        prevent_initial_call=True,
    )

    app.callback(
        Output("map-search-suggestions", "children"),
        Output("map-search-hits", "data"),
        Output("map-search-status", "children"),
        Output("map-search", "className"),
        Input("map-search-debounced", "data"),
        State("map-search-committed", "data"),
        State("map-view-mode", "value"),
        prevent_initial_call=True,
    )(_map_search_suggest)

    app.callback(
        Output("map-goto", "data"),
        Output("map-search-suggestions", "children", allow_duplicate=True),
        Output("map-search-hits", "data", allow_duplicate=True),
        Output("map-search-status", "children", allow_duplicate=True),
        Output("map-search", "className", allow_duplicate=True),
        Output("map-search-query", "value"),
        Output("map-search-committed", "data"),
        Input({"type": "map-search-hit", "index": ALL}, "n_clicks"),
        Input("map-search-query", "n_submit"),
        State("map-search-hits", "data"),
        State("map-search-query", "value"),
        State("map-view-mode", "value"),
        prevent_initial_call=True,
    )(_map_search_choose)

    app.callback(
        Output("map-search-query", "value", allow_duplicate=True),
        Output("map-search-committed", "data", allow_duplicate=True),
        Output("map-search-hits", "data", allow_duplicate=True),
        Output("map-search-suggestions", "children", allow_duplicate=True),
        Output("map-search-status", "children", allow_duplicate=True),
        Output("map-search-status", "className", allow_duplicate=True),
        Output("map-search", "className", allow_duplicate=True),
        Output("map-search-debounced", "data", allow_duplicate=True),
        Output("map-search-highlight", "data", allow_duplicate=True),
        Input("map-search-clear", "n_clicks"),
        prevent_initial_call=True,
    )(_map_search_clear)

    app.clientside_callback(
        """
        function(n) {
            if (!n) {
                return window.dash_clientside.no_update;
            }
            if (window.ForecastMap && typeof window.ForecastMap.clearPlace === "function") {
                window.ForecastMap.clearPlace();
            }
            window.setTimeout(function () {
                var input = document.getElementById("map-search-query");
                if (input) {
                    input.focus();
                }
            }, 0);
            return window.dash_clientside.no_update;
        }
        """,
        Output("map-bridge-tick", "data", allow_duplicate=True),
        Input("map-search-clear", "n_clicks"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(hideClicks, showClicks) {
            var triggered = window.dash_clientside.callback_context.triggered_id;
            if (triggered === "map-search-hide") {
                return "forecast-map-search-shell is-collapsed";
            }
            if (triggered === "map-search-show") {
                window.setTimeout(function () {
                    var input = document.getElementById("map-search-query");
                    if (input) {
                        input.focus();
                    }
                }, 0);
                return "forecast-map-search-shell";
            }
            return window.dash_clientside.no_update;
        }
        """,
        Output("map-search-shell", "className"),
        Input("map-search-hide", "n_clicks"),
        Input("map-search-show", "n_clicks"),
        prevent_initial_call=True,
    )

    app.clientside_callback(
        """
        function(value) {
            return (value || "").trim()
                ? "forecast-map-search__field has-query"
                : "forecast-map-search__field";
        }
        """,
        Output("map-search-field", "className"),
        Input("map-search-query", "value"),
    )

    # Fly the active map host and draw the outline highlight.
    app.clientside_callback(
        """
        function(goto) {
            var nu = window.dash_clientside.no_update;
            // tick, status text, status class, leaflet viewport, highlight geojson
            if (!goto || goto.lon == null || goto.lat == null) {
                return [nu, nu, nu, nu, nu];
            }
            var result = {ok: true};
            if (window.ForecastMap && typeof window.ForecastMap.flyTo === "function") {
                result = window.ForecastMap.flyTo(goto) || {ok: true};
            }
            if (result && result.ok === false) {
                return [
                    nu,
                    result.message || "Outside this map's coverage",
                    "forecast-map-search__status is-warning",
                    nu,
                    nu,
                ];
            }
            var leaf = result && result.leaflet;
            if (leaf) {
                return [
                    nu,
                    "",
                    "forecast-map-search__status",
                    leaf.viewport != null ? leaf.viewport : nu,
                    leaf.data != null ? leaf.data : null,
                ];
            }
            return [nu, "", "forecast-map-search__status", nu, nu];
        }
        """,
        Output("map-bridge-tick", "data", allow_duplicate=True),
        Output("map-search-status", "children", allow_duplicate=True),
        Output("map-search-status", "className", allow_duplicate=True),
        Output("map", "viewport"),
        Output("map-search-highlight", "data"),
        Input("map-goto", "data"),
        prevent_initial_call=True,
    )
