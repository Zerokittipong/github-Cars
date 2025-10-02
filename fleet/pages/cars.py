# fleet/pages/cars.py
import dash
from dash import html, dcc, dash_table, Input, Output, State, callback, ctx
import pandas as pd
from fleet.db import SessionLocal
from fleet.models import Car

dash.register_page(__name__, path="/cars", name="Cars")

# ---------- helpers ----------
def load_cars_df() -> pd.DataFrame:
    with SessionLocal() as s:
        rows = s.query(Car).order_by(Car.id.asc()).all()
        data = [{
            "id": r.id,
            "plate": r.plate,
            "brand": r.brand,
            "model": r.model,
            "year": r.year,
            "status": r.status,
        } for r in rows]
    return pd.DataFrame(data)

def insert_car(plate: str, brand: str, model: str | None, year: int | None, status: str = "available") -> str:
    plate = plate.strip()
    brand = (brand or "").strip()
    model = (model or "").strip()

    if not plate or not brand:
        return "❌ กรุณากรอก 'ทะเบียน' และ 'ยี่ห้อ'"

    with SessionLocal() as s:
        # กันทะเบียนซ้ำ
        existed = s.query(Car).filter(Car.plate == plate).first()
        if existed:
            return f"⚠️ ทะเบียน '{plate}' มีอยู่แล้ว (id={existed.id})"
        car = Car(plate=plate, brand=brand, model=model or None, year=year, status=status or "available")
        s.add(car)
        s.commit()
    return f"✅ เพิ่มรถทะเบียน {plate} สำเร็จ"

# ---------- layout ----------
def layout():
    df = load_cars_df()
    columns = [{"name": c, "id": c} for c in (df.columns if not df.empty else ["id","plate","brand","model","year","status"])]

    return html.Div([
        html.H2("Cars"),

        html.Div([
            html.Div([
                html.Label("ทะเบียน *"),
                dcc.Input(id="car-plate", type="text", placeholder="เช่น กข1234", style={"width": "100%"})
            ], style={"flex": 1, "minWidth": 180, "marginRight": 8}),
            html.Div([
                html.Label("ยี่ห้อ *"),
                dcc.Input(id="car-brand", type="text", placeholder="เช่น Toyota", style={"width": "100%"})
            ], style={"flex": 1, "minWidth": 180, "marginRight": 8}),
            html.Div([
                html.Label("รุ่น"),
                dcc.Input(id="car-model", type="text", placeholder="เช่น Vios", style={"width": "100%"})
            ], style={"flex": 1, "minWidth": 160, "marginRight": 8}),
            html.Div([
                html.Label("ปี"),
                dcc.Input(id="car-year", type="number", placeholder="เช่น 2019", style={"width": "100%"})
            ], style={"flex": 1, "minWidth": 120, "marginRight": 8}),
            html.Div([
                html.Label("สถานะ"),
                dcc.Dropdown(
                    id="car-status",
                    options=[{"label": x, "value": x} for x in ["available", "in_use", "maintenance"]],
                    value="available",
                    clearable=False
                )
            ], style={"flex": 1, "minWidth": 160}),
        ], style={"display": "flex", "flexWrap": "wrap", "gap": 6, "alignItems": "end"}),

        html.Div([
            html.Button("➕ เพิ่มรถ", id="btn-add-car"),
            html.Span(id="car-msg", style={"marginLeft": 12})
        ], style={"margin": "10px 0"}),

        dash_table.DataTable(
            id="cars-table",
            data=(df.to_dict("records") if not df.empty else []),
            columns=columns,
            page_size=10,
            sort_action="native",
            filter_action="native",
            style_table={"overflowX": "auto"},
        ),
    ])

# ---------- callbacks ----------
@callback(
    Output("cars-table", "data"),
    Output("car-msg", "children"),
    Output("car-plate", "value"),
    Output("car-brand", "value"),
    Output("car-model", "value"),
    Output("car-year", "value"),
    Output("car-status", "value"),
    Input("btn-add-car", "n_clicks"),
    State("car-plate", "value"),
    State("car-brand", "value"),
    State("car-model", "value"),
    State("car-year", "value"),
    State("car-status", "value"),
    prevent_initial_call=True,
)
def on_add(n, plate, brand, model, year, status):
    if not n or ctx.triggered_id != "btn-add-car":
        raise dash.exceptions.PreventUpdate

    # แปลง year เป็น int ถ้ามีค่า
    try:
        year_val = int(year) if year not in (None, "", []) else None
    except Exception:
        return dash.no_update, "❌ ค่า 'ปี' ไม่ถูกต้อง", dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update

    msg = insert_car(plate or "", brand or "", model or "", year_val, status or "available")

    # โหลดตารางใหม่
    df = load_cars_df()
    data = df.to_dict("records") if not df.empty else []

    # ถ้าสำเร็จ เคลียร์ฟอร์ม
    if msg.startswith("✅"):
        return data, msg, "", "", "", None, "available"
    else:
        return data, msg, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
