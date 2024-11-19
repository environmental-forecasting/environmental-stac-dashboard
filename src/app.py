import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from dash import _dash_renderer
from layouts import index

stylesheets = [
    "https://cdn.web.bas.ac.uk/bas-style-kit/0.7.3/css/bas-style-kit.min.css",
    dbc.themes.BOOTSTRAP,
    dmc.styles.DATES,
    dmc.styles.CODE_HIGHLIGHT,
    dmc.styles.CHARTS,
    dmc.styles.CAROUSEL,
    dmc.styles.NOTIFICATIONS,
    dmc.styles.NPROGRESS,
]

app = dash.Dash(__name__, external_stylesheets=[*stylesheets])
app.title = "IceNet Visualiser"

app.layout = index.layout

if __name__ == "__main__":
    app.run_server(debug=True, host="0.0.0.0", port=8001)
