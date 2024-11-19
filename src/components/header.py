import dash_bootstrap_components as dbc

header_layout = dbc.NavbarSimple(
    brand="IceNet",
    brand_href="https://icenet.ai",
    color="black",
    dark=True,
    class_name="p-0",
    children=[
        dbc.DropdownMenu(
            nav=False,
            in_navbar=True,
            align_end=True,
            label="Part of British Antarctic Survey",
            toggle_style={
                "border": 0,
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
