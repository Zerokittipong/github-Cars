import dash
from dash import html
dash.register_page(__name__, path="/maintenance", name="Maintenance")
def layout():
    return html.Div([html.H2("Maintenance (smoke test)"), html.P(__file__)])
