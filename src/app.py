import dash
import dash_bootstrap_components as dbc
import dash_mantine_components as dmc
from layouts import index
from callbacks import map_callbacks

BAS_STYLE_KIT_VERSION = "0.7.3"
TABLER_ICONS_VERSION = "3.34.1"
OPENLAYERS_VERSION = "10.10.0"
PROJ4_VERSION = "2.21.0"
CESIUM_VERSION = "1.143.0"
CESIUM_BASE_URL = (
    f"https://cdn.jsdelivr.net/npm/cesium@{CESIUM_VERSION}/Build/Cesium/"
)

stylesheets = [
    f"https://cdn.web.bas.ac.uk/bas-style-kit/{BAS_STYLE_KIT_VERSION}/css/bas-style-kit.min.css",
    f"https://cdnjs.cloudflare.com/ajax/libs/tabler-icons/{TABLER_ICONS_VERSION}/tabler-icons.min.css",
    dbc.themes.BOOTSTRAP,
    dmc.styles.ALL,
    f"https://cdn.jsdelivr.net/npm/ol@{OPENLAYERS_VERSION}/ol.css",
    f"{CESIUM_BASE_URL}Widgets/widgets.css",
]

external_scripts = [
    f"https://cdn.jsdelivr.net/npm/proj4@{PROJ4_VERSION}/dist/proj4.js",
    f"https://cdn.jsdelivr.net/npm/ol@{OPENLAYERS_VERSION}/dist/ol.js",
    f"{CESIUM_BASE_URL}Cesium.js",
]

app = dash.Dash(
    __name__,
    external_stylesheets=[*stylesheets],
    external_scripts=external_scripts,
)
app.title = "IceNet Visualiser"

# Cesium workers and assets need this before Cesium.js runs.
app.index_string = f"""<!DOCTYPE html>
<html>
    <head>
        {{%metas%}}
        <title>{{%title%}}</title>
        {{%favicon%}}
        {{%css%}}
        <script>window.CESIUM_BASE_URL = "{CESIUM_BASE_URL}";</script>
    </head>
    <body>
        {{%app_entry%}}
        <footer>
            {{%config%}}
            {{%scripts%}}
            {{%renderer%}}
        </footer>
    </body>
</html>
"""

# Register the callbacks
map_callbacks.register_callbacks(app)

app.layout = index.layout
server = app.server


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8005)
