import dash_bootstrap_components as dbc
from dash import dcc

def car_form():
    return dbc.Form([
        dbc.Label("ทะเบียนรถ"),
        dbc.Input(type="text", id="car-plate"),
        dbc.Label("ยี่ห้อ"),
        dbc.Input(type="text", id="car-brand"),
        dbc.Label("รุ่น"),
        dbc.Input(type="text", id="car-model"),
        dbc.Button("บันทึก", id="btn-save-car", color="primary")
    ])
