import datetime as dt
from dash import html

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
                                        html.A(
                                            "British Antarctic Survey",
                                            href="https://www.bas.ac.uk/",
                                        ),
                                        " (BAS) is part of ",
                                        html.A(
                                            "UK Research and Innovation",
                                            href="https://www.ukri.org/",
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
                                        html.Li(html.A("Cookies", href="/cookies")),
                                        html.Li(html.A("Copyright", href="/copyright")),
                                        html.Li(html.A("Privacy", href="/privacy")),
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
