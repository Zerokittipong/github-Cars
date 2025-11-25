# fleet/app.py
import dash
from dash import html, dcc
from .db import init_db
from .version import __version__


init_db()

app = dash.Dash(__name__,use_pages=True, suppress_callback_exceptions=True, title=f"ระบบยานพาหนะ v{__version__}",)

app.layout = html.Div([
    html.H1(["ระบบบริหารยานพาหนะ สำนักสำรวจและประเมินศักยภาพน้ำบาดาล", 
             html.Small(f"v{__version__}", style={"fontWeight":"normal","fontSize":"60%"}),
    ]),
    html.Div([
        dcc.Link("Dashboard", href="/"), " | ",
        dcc.Link("Cars", href="/cars"), " | ",
        dcc.Link("Usage", href="/usage"), " | ",
        dcc.Link("Users", href="/users"), " | ",
        dcc.Link("Maintenance", href="/maintenance")," | ",
        dcc.Link("Carlendar", href="/carlendar")

    ]),
    html.Hr(),
    dash.page_container,
    html.Footer(f"Build {__version__}", style={"marginTop":"2rem","color":"#777"})
])

if __name__ == "__main__":

    app.run(host ="0.0.0.0", port = 9000, debug=True)
