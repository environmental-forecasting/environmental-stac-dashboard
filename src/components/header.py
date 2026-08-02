import dash_bootstrap_components as dbc

header_layout = dbc.NavbarSimple(
    brand="IceNet",
    brand_href="https://icenet.ai",
    color="dark",
    dark=True,
    class_name="app-header p-0 py-1",
    children=[
        dbc.DropdownMenu(
            nav=False,
            in_navbar=True,
            align_end=True,
            label="Part of British Antarctic Survey",
            toggle_style={
                "border": 0,
                "padding": "0.25rem 0.5rem",
                "fontSize": "0.85rem",
            },
            children=[
                dbc.DropdownMenuItem("British Antarctic Survey", header=True),
                dbc.DropdownMenuItem("BAS Home", href="https://www.bas.ac.uk/"),
                dbc.DropdownMenuItem(
                    "Discover BAS Data", href="https://data.bas.ac.uk/"
                ),
            ],
        ),
    ],
)
