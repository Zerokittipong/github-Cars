# fleet/app.py
import dash
from dash import html, dcc



app = dash.Dash(
    __name__,
    use_pages=True,
    suppress_callback_exceptions=True,   # << สำคัญ
)

app.layout = html.Div([
    html.H1("Fleet Management"),
    html.Div([
        dcc.Link("Dashboard", href="/"), " | ",
        dcc.Link("Cars", href="/cars"), " | ",
        dcc.Link("Usage", href="/usage"), " | ",
        dcc.Link("Users", href="/users"), " | ",
        dcc.Link("Maintenance", href="/maintenance"),
    ]),
    html.Hr(),
    dash.page_container
])

if __name__ == "__main__":
    app.run(debug=True)
