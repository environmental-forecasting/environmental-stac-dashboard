"""In-app Cookies, Copyright, and Privacy modals."""

from __future__ import annotations

import datetime as dt

import dash_bootstrap_components as dbc
from dash import html

_YEAR = dt.date.today().year

LEGAL_TOPICS = ("cookies", "copyright", "privacy")


def _section(
    title: str,
    paragraphs: list,
    bullets: list | None = None,
):
    children = [html.H2(title, className="legal-modal__heading")]
    for text in paragraphs:
        children.append(html.P(text))
    if bullets:
        children.append(html.Ul([html.Li(item) for item in bullets]))
    return html.Div(children, className="legal-modal__section")


def _external_ref(label: str, href: str) -> html.A:
    return html.A(
        label,
        href=href,
        target="_blank",
        rel="noopener noreferrer",
    )


COOKIES_BODY = html.Div(
    [
        _section(
            "How this site uses storage",
            [
                "environmental-forecasting-dashboard does not use advertising or tracking cookies. "
                "It keeps a small amount of data in your browser so the map "
                "controls remember your last choices.",
            ],
        ),
        _section(
            "Local storage",
            [
                "Your browser may store a user-prefs entry for this site. "
                "That record can include recently selected collections, forecast "
                "start date, variable, colour map, map view mode, basemap, and "
                "locked colour-range settings.",
            ],
            [
                "It is used only to restore those controls on your next visit.",
                "It stays on your device and is not sent to BAS as a profile.",
                "Use “Reset defaults” in Forecast controls to clear it, or clear "
                "site data in your browser settings.",
            ],
        ),
        _section(
            "Session and map traffic",
            [
                "Like most web apps, your browser also keeps short-lived session "
                "state needed to run the page (for example Dash/React runtime "
                "state). Map tiles, forecast catalogue queries, and optional "
                "place-search requests are ordinary network calls to the "
                "services that back this deployment; they are not analytical "
                "cookies.",
            ],
        ),
        _section(
            "Third-party map and search services",
            [
                "Basemap tiles and place search may be provided by third parties "
                "(for example OpenStreetMap-style tile hosts or Nominatim). Those "
                "services receive standard request metadata such as IP address "
                "and may set their own cookies under their policies.",
            ],
        ),
    ],
    className="legal-modal__body",
)

COPYRIGHT_BODY = html.Div(
    [
        _section(
            "Software",
            [
                f"© {_YEAR} British Antarctic Survey. environmental-forecasting-dashboard source "
                "code is released under the MIT License unless a file states "
                "otherwise. You may use, copy, modify, merge, publish, "
                "distribute, sublicense, and/or sell copies of the Software, "
                "subject to that licence.",
            ],
        ),
        _section(
            "Forecast and catalogue data",
            [
                "Any forecasts shown in this interface are provided purely for "
                "research purposes. They must not be relied on for operational "
                "decision-making, safety-critical use, navigation, or any other "
                "purpose where inaccurate or incomplete information could cause "
                "loss, damage, injury, or other harm.",
                [
                    "Unless a specific dataset states otherwise, forecast "
                    "products made available through this service are released "
                    "under the ",
                    _external_ref(
                        "Open Government Licence v3.0",
                        "https://www.nationalarchives.gov.uk/doc/"
                        "open-government-licence/version/3/",
                    ),
                    ", which is compatible with ",
                    _external_ref(
                        "CC BY 4.0",
                        "https://creativecommons.org/licenses/by/4.0/",
                    ),
                    ". You should retain required attribution when reusing "
                    "the data.",
                ],
                "To the fullest extent permitted by law, British Antarctic "
                "Survey, UK Research and Innovation, and the authors and "
                "contributors of this software and the forecast products "
                "disclaim all warranties and accept no liability for any loss, "
                "damage, or expense arising from use of, or reliance on, the "
                "forecasts, catalogue metadata, or this viewer, whether in "
                "contract, tort (including negligence), or otherwise.",
            ],
        ),
        _section(
            "Maps and imagery",
            [
                "Basemap tiles and place names come from third-party providers "
                "and are used under their attribution and licence requirements "
                "(shown with the map where applicable).",
            ],
        ),
    ],
    className="legal-modal__body",
)

PRIVACY_BODY = html.Div(
    [
        _section(
            "Who we are",
            [
                "environmental-forecasting-dashboard is operated in connection with the British "
                "Antarctic Survey (BAS), which is part of UK Research and "
                "Innovation (UKRI).",
            ],
        ),
        _section(
            "What this site processes",
            [
                "This application is a forecast map viewer. It does not ask you "
                "to create an account or submit a name, email address, or other "
                "contact details through these controls.",
            ],
            [
                "Control preferences can be stored in your browser (see Cookies).",
                "Map and catalogue use generates normal web-server and "
                "application logs (for example timestamps, IP address, and "
                "requested URLs) needed to run and secure the service.",
                "If you use place search, your search text is sent to the "
                "configured geocoding service so matching places can be returned.",
            ],
        ),
        _section(
            "Purpose and legal basis",
            [
                "We process this technical information to provide the viewer, "
                "keep it secure and reliable, and remember optional interface "
                "settings you choose. We do not sell personal data or use it for "
                "advertising.",
            ],
        ),
        _section(
            "Retention and your choices",
            [
                "Browser preferences remain until you clear them or use Reset "
                "defaults. Server logs are kept only as long as needed for "
                "operations and security. You can stop place search by not using "
                "that control.",
            ],
        ),
        _section(
            "Contact",
            [
                "For questions about this viewer’s privacy information, contact "
                "BAS through the usual organisational channels published on the "
                "BAS website. This notice describes environmental-forecasting-dashboard only; "
                "other BAS sites and services have their own notices.",
            ],
        ),
    ],
    className="legal-modal__body",
)

_TITLES = {
    "cookies": "Cookies",
    "copyright": "Copyright",
    "privacy": "Privacy",
}
_BODIES = {
    "cookies": COOKIES_BODY,
    "copyright": COPYRIGHT_BODY,
    "privacy": PRIVACY_BODY,
}


def _modal(topic: str) -> dbc.Modal:
    return dbc.Modal(
        [
            dbc.ModalHeader(
                dbc.ModalTitle(_TITLES[topic]),
                close_button=True,
            ),
            dbc.ModalBody(_BODIES[topic]),
            dbc.ModalFooter(
                dbc.Button(
                    "Close",
                    id=f"legal-close-{topic}",
                    className="legal-modal__close",
                    n_clicks=0,
                )
            ),
        ],
        id=f"legal-modal-{topic}",
        is_open=False,
        size="lg",
        scrollable=True,
        className="legal-modal",
        backdrop=True,
        keyboard=True,
    )


def legal_open_control(topic: str, *, source: str, label: str | None = None):
    """
    Button styled as a text link that opens an in-app legal modal.

    ``source`` distinguishes header vs footer triggers (unique Dash ids).
    """
    if topic not in LEGAL_TOPICS:
        raise ValueError(f"Unknown legal topic: {topic}")
    return html.Button(
        label or _TITLES[topic],
        id=f"legal-open-{source}-{topic}",
        type="button",
        n_clicks=0,
        className="legal-open-link",
    )


legal_modals = html.Div(
    [_modal(topic) for topic in LEGAL_TOPICS],
    className="legal-modals",
)
