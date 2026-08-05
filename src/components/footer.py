import datetime as dt

from components.legal import legal_open_control
from dash import html

_BAS_HOME = "https://www.bas.ac.uk/"
_UKRI_HOME = "https://www.ukri.org/"


def _external_link(label: str, href: str) -> html.A:
    return html.A(
        label,
        href=href,
        target="_blank",
        rel="noopener noreferrer",
    )


footer_layout = html.Footer(
    className="site-footer site-footer--compact",
    children=[
        html.Div(
            className="bsk-footer bsk-footer-default m-0",
            children=[
                html.Div(
                    className="container site-footer__inner",
                    children=[
                        html.Div(
                            className="bsk-footer-governance",
                            children=[
                                html.Span(
                                    [
                                        "The ",
                                        _external_link(
                                            "British Antarctic Survey", _BAS_HOME
                                        ),
                                        " (BAS) is part of ",
                                        _external_link(
                                            "UK Research and Innovation", _UKRI_HOME
                                        ),
                                        " (UKRI)",
                                    ],
                                    className="site-footer__credit",
                                ),
                            ],
                        ),
                        html.Div(
                            className="bsk-footer-policy-links",
                            children=[
                                html.Ul(
                                    className="bsk-list-inline site-footer__links",
                                    children=[
                                        html.Li(
                                            legal_open_control(
                                                "cookies", source="footer"
                                            )
                                        ),
                                        html.Li(
                                            legal_open_control(
                                                "copyright", source="footer"
                                            )
                                        ),
                                        html.Li(
                                            legal_open_control(
                                                "privacy", source="footer"
                                            )
                                        ),
                                        html.Li(
                                            f"{dt.date.today().year} BAS",
                                            className="site-footer__year",
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        )
    ],
)
