import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from layouts import index
from callbacks import map_callbacks

stylesheets = [
    "https://cdn.web.bas.ac.uk/bas-style-kit/0.7.3/css/bas-style-kit.min.css",
    dbc.themes.BOOTSTRAP,
    dmc.styles.ALL,
]

app = dash.Dash(__name__, external_stylesheets=[*stylesheets])
app.title = "IceNet Visualiser"

# Register the callbacks
map_callbacks.register_callbacks(app)

app.layout = index.layout
server = app.server


if __name__ == "__main__":
    app.run_server(debug=True, host="0.0.0.0", port=8001)
