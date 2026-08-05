"""Callbacks that open and close the in-app legal modals."""

from dash import Input, Output, State, callback_context, no_update

from components.legal import LEGAL_TOPICS


def register_callbacks(app):
    for topic in LEGAL_TOPICS:
        _register_topic(app, topic)


def _register_topic(app, topic: str) -> None:
    modal_id = f"legal-modal-{topic}"
    close_id = f"legal-close-{topic}"
    header_id = f"legal-open-header-{topic}"
    footer_id = f"legal-open-footer-{topic}"

    @app.callback(
        Output(modal_id, "is_open"),
        Input(header_id, "n_clicks"),
        Input(footer_id, "n_clicks"),
        Input(close_id, "n_clicks"),
        State(modal_id, "is_open"),
        prevent_initial_call=True,
    )
    def _toggle_legal_modal(header_clicks, footer_clicks, close_clicks, is_open):
        triggered = callback_context.triggered_id
        if triggered in (header_id, footer_id):
            return True
        if triggered == close_id:
            return False
        return no_update if is_open is None else is_open
