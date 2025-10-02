# fleet/pages/users.py
import dash
from dash import html, dcc, dash_table, Input, Output, State, callback, ctx
import pandas as pd
from fleet.db import SessionLocal
from fleet.models import User

dash.register_page(__name__, path="/users", name="Users")

def load_users_df() -> pd.DataFrame:
    with SessionLocal() as s:
        rows = s.query(User).order_by(User.id.asc()).all()
        data = [{"id": r.id, "full_name": r.full_name} for r in rows]
    return pd.DataFrame(data)

def insert_user(full_name: str) -> str:
    full_name = (full_name or "").strip()
    if not full_name:
        return "❌ กรุณากรอกชื่อผู้ใช้งาน"
    with SessionLocal() as s:
        existed = s.query(User).filter(User.full_name == full_name).first()
        if existed:
            return f"⚠️ '{full_name}' มีอยู่แล้ว (id={existed.id})"
        s.add(User(full_name=full_name))
        s.commit()
    return f"✅ เพิ่มผู้ใช้งาน '{full_name}' สำเร็จ"

def layout():
    df = load_users_df()
    return html.Div([
        html.H2("Users"),
        html.Div([
            html.Label("ชื่อผู้ใช้งาน *"),
            dcc.Input(id="user-fullname", type="text", placeholder="เช่น สมชาย ใจดี", style={"width": "260px"}),
            html.Button("➕ เพิ่มผู้ใช้งาน", id="btn-add-user", style={"marginLeft": "8px"}),
            html.Span(id="user-msg", style={"marginLeft": "12px"})
        ], style={"marginBottom": "10px"}),
        dash_table.DataTable(
            id="users-table",
            data=(df.to_dict("records") if not df.empty else []),
            columns=[{"name": c, "id": c} for c in (df.columns if not df.empty else ["id","full_name"])],
            page_size=10, sort_action="native", filter_action="native",
            style_table={"overflowX": "auto"},
        ),
    ])

@callback(
    Output("users-table", "data"),
    Output("user-msg", "children"),
    Output("user-fullname", "value"),
    Input("btn-add-user", "n_clicks"),
    State("user-fullname", "value"),
    prevent_initial_call=True
)
def add_user(n, full_name):
    if not n or ctx.triggered_id != "btn-add-user":
        raise dash.exceptions.PreventUpdate
    msg = insert_user(full_name)
    df = load_users_df()
    data = df.to_dict("records") if not df.empty else []
    if msg.startswith("✅"):
        return data, msg, ""
    return data, msg, dash.no_update
    
@callback(
    Output("usg-msg", "children", allow_duplicate=True),
    Output("usage-table", "data", allow_duplicate=True),
    Output("usg-car", "options", allow_duplicate=True),
    Output("return-section", "style"),
    Output("return-usage-id", "data"),
    Output("ret-date", "date"),
    Output("ret-hh", "value"),
    Output("ret-mm", "value"),
    Input("btn-return-confirm", "n_clicks"),
    State("return-usage-id", "data"),
    State("ret-date", "date"),
    State("ret-hh", "value"),
    State("ret-mm", "value"),
    State("usg-open-only", "value"),
    prevent_initial_call=True
)
def on_confirm_return(n, usage_id, date_str, hh, mm, open_only_values):
    if not n:
        raise dash.exceptions.PreventUpdate
    if not usage_id or not date_str or hh is None or mm is None:
        return ("❌ โปรดระบุวัน/เวลาให้ครบ", dash.no_update, dash.no_update,
                {"display": "block"}, dash.no_update, dash.no_update, dash.no_update, dash.no_update)

    end_iso = to_iso_from_date_hh_mm(date_str, hh, mm)
    msg = return_car_at(usage_id, end_iso)

    # รีโหลดตาราง + รายการรภว่าง
    df_full = load_usage_df()
    df = df_full if "open" not in (open_only_values or []) else df_full[df_full["status"] == "in_use"]
    options = load_car_options(only_available=True)

    # เคลียร์และซ่อนฟอร์ม
    return (msg,
            (df.to_dict("records") if not df.empty else []),
            options,
            {"display": "none"}, None, None, None, None)
