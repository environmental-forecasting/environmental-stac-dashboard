import datetime as dt

from dash import html

footer_layout = html.Footer(
    className="site-footer",
    children=[
        html.Div(
            className="bsk-footer bsk-footer-default m-0",
            children=[
                html.Div(
                    className="bsk-container",
                    children=[
                        html.Div(
                            className="bsk-footer-governance",
                            style={"display": "inline-block"},
                            children=[
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
                                html.Div(
                                    className="bsk-footer-ogl",
                                    children=[
                                        html.Div(
                                            className="bsk-ogl-symbol",
                                            children=[
                                                html.A(
                                                    href="http://www.nationalarchives.gov.uk/doc/open-government-licence",
                                                    children=[
                                                        html.Span(
                                                            className="bsk-ogl-symbol",
                                                            children=[
                                                                "Open Government Licence"
                                                            ],
                                                        )
                                                    ],
                                                ),
                                            ],
                                        ),
                                        "All content is available under the ",
                                        html.A(
                                            "Open Government Licence",
                                            href="http://www.nationalarchives.gov.uk/doc/open-government-licence",
                                        ),
                                        ", v3.0 except where otherwise stated",
                                    ],
                                ),
                            ],
                        ),
                        html.Div(
                            className="bsk-footer-policy-links",
                            style={
                                "float": "right",
                                "clear": "right",
                                "display": "inline-block",
                            },
                            children=[
                                html.Ul(
                                    className="bsk-list-inline",
                                    children=[
                                        html.Li(
                                            [
                                                html.A(
                                                    "Cookies",
                                                    href="/cookies",
                                                )
                                            ],
                                            className="d-inline-block me-2",
                                        ),
                                        html.Li(
                                            [html.A("Copyright", href="/copyright")],
                                            className="d-inline-block me-2",
                                        ),
                                        html.Li(
                                            [html.A("Privacy", href="/privacy")],
                                            className="d-inline-block",
                                        ),
                                    ],
                                ),
                                f"{dt.date.today().year} British Antarctic Survey",
                            ],
                        ),
                    ],
                ),
            ],
            style={"padding-bottom": "2rem"},
        )
    ],
)
