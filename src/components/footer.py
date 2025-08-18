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
                    style={
                        "display": "flex",
                        "flexWrap": "wrap",
                        "justifyContent": "space-between",
                        "alignItems": "center",
                        "padding": "1rem",
                    },
                    children=[
                        html.Div(
                            className="bsk-footer-governance",
                            style={
                                "flex": "1 1 300px",  # grow/shrink, basis width
                                "minWidth": "200px",
                            },
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
                                "flex": "0 1 300px",
                                "minWidth": "200px",
                                "textAlign": "right",
                                "marginTop": "0.5rem",
                            },
                            children=[
                                html.Ul(
                                    className="bsk-list-inline",
                                    style={
                                        "listStyleType": "none",
                                        "padding": 0,
                                        "margin": 0,
                                        "display": "flex",
                                        "justifyContent": "flex-end",
                                        "gap": "1rem",
                                    },
                                    children=[
                                        html.Li(html.A("Cookies", href="/cookies")),
                                        html.Li(html.A("Copyright", href="/copyright")),
                                        html.Li(html.A("Privacy", href="/privacy")),
                                    ],
                                ),
                                html.Div(f"{dt.date.today().year} British Antarctic Survey", style={"marginTop": "0.5rem"}),
                            ],
                        ),
                    ],
                ),
            ],
            style={"paddingBottom": "2rem"},
        )
    ],
)
