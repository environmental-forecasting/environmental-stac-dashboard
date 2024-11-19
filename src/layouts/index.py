from components import footer, header, sidebar
from dash import html

layout = html.Div(
    [
        header.header_layout,
        sidebar.sidebar_layout,
        footer.footer_layout,
    ]
)
