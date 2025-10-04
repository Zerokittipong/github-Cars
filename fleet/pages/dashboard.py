# fleet/pages/dashboard.py
import pandas as pd
import dash
from dash import html, dcc, Input, Output, State, callback
import plotly.express as px
from sqlalchemy import text
from datetime import datetime
from fleet.db import engine as db_engine

dash.register_page(__name__, path="/", name="Dashboard")

# ---------- Helpers ----------
def _ensure_types(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["accept_date"] = pd.to_datetime(df["accept_date"], errors="coerce")
    df["grand_total"] = pd.to_numeric(df["grand_total"], errors="coerce").fillna(0.0)
    return df.dropna(subset=["accept_date"])

def _read_orders():
    """อ่านใบงานซ่อมที่มีวันตรวจรับ"""
    with db_engine.begin() as conn:
        rows = conn.execute(
            text("SELECT accept_date, grand_total, car_id FROM maintenance_orders "
                 "WHERE accept_date IS NOT NULL")
        ).mappings().all()
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["accept_date", "grand_total", "car_id"])
    df["accept_date"] = pd.to_datetime(df["accept_date"])
    df["grand_total"] = pd.to_numeric(df["grand_total"], errors="coerce").fillna(0.0)
    return df

def _cars_lookup():
    with db_engine.begin() as conn:
        rows = conn.execute(text("SELECT id, plate FROM cars")).mappings().all()
    df = pd.DataFrame(rows)
    return {} if df.empty else dict(zip(df["id"], df["plate"]))

def _fiscal_year(dt: pd.Timestamp) -> int:
    """ปีงบประมาณ (เริ่ม ก.ย.)  ก.ย.–ธ.ค. = ปีเดียวกับ dt / ม.ค.–ส.ค. = dt.year-1"""
    return dt.year if dt.month >= 9 else (dt.year - 1)

def _fiscal_year_list(df_orders: pd.DataFrame):
    if df_orders.empty:
        this_fy = _fiscal_year(pd.Timestamp.today())
        return [this_fy]
    fys = sorted(df_orders["accept_date"].map(_fiscal_year).unique())
    return fys

def _fig_monthly(df_orders: pd.DataFrame, fy: int):
    """กราฟเส้น: ยอดซ่อมรวมรายเดือน (12 เดือน เริ่ม ก.ย.) ของปีงบประมาณที่เลือก"""
    months_th = ["ก.ย.","ต.ค.","พ.ย.","ธ.ค.","ม.ค.","ก.พ.","มี.ค.","เม.ย.","พ.ค.","มิ.ย.","ก.ค.","ส.ค."]

    if df_orders.empty:
        plot_df = pd.DataFrame({"month": months_th, "total": [0.0]*12})
    else:
        start = pd.Timestamp(fy, 9, 1)
        end   = pd.Timestamp(fy + 1, 9, 1)
        df = df_orders[(df_orders["accept_date"] >= start) & (df_orders["accept_date"] < end)].copy()
        if df.empty:
            plot_df = pd.DataFrame({"month": months_th, "total": [0.0]*12})
        else:
            # index เดือนแบบงบประมาณ (ก.ย.=0 ... ส.ค.=11)
            df["f_idx"] = (df["accept_date"].dt.month - 9) % 12
            grp = df.groupby("f_idx")["grand_total"].sum()
            totals = [float(grp.get(i, 0.0)) for i in range(12)]
            plot_df = pd.DataFrame({"month": months_th, "total": totals})

    fig = px.line(plot_df, x="month", y="total", markers=True,
                  title=f"ยอดค่าซ่อมรวมรายเดือน (ปีงบประมาณ {fy}/{(fy+1)%100:02d})")
    fig.update_layout(yaxis_title="บาท", xaxis_title="เดือน (เริ่ม ก.ย.)")
    fig.update_yaxes(tickformat=",")
    return fig

def _fig_by_car(df_orders: pd.DataFrame, months_window: int):
    """กราฟเส้น: ยอดซ่อมรวมรายคัน ในรอบ N เดือนล่าสุด (ยึด accept_date)"""
    car_map = _cars_lookup()
    if df_orders.empty:
        plot_df = pd.DataFrame({"plate": [], "total": []})
    else:
        end = pd.Timestamp.today().normalize() + pd.Timedelta(days=1)   # exclusive
        start = end - pd.DateOffset(months=months_window)
        df = df_orders[(df_orders["accept_date"] >= start) & (df_orders["accept_date"] < end)].copy()
        if df.empty:
            plot_df = pd.DataFrame({"plate": [], "total": []})
        else:
            grp = df.groupby("car_id")["grand_total"].sum().sort_values(ascending=False)
            plate = [car_map.get(i, f"ID {i}") for i in grp.index]
            plot_df = pd.DataFrame({"plate": plate, "total": grp.values})

    title = f"ยอดค่าซ่อมรวมรายคัน ในรอบ {months_window} เดือนล่าสุด"
    fig = px.line(plot_df, x="plate", y="total", markers=True, title=title)
    fig.update_layout(yaxis_title="บาท", xaxis_title="ทะเบียนรถ")
    fig.update_yaxes(tickformat=",")
    return fig

# ---------- Layout ----------
_orders_df = _read_orders()
_fy_list = _fiscal_year_list(_orders_df)
_default_fy = _fy_list[-1] if _fy_list else _fiscal_year(pd.Timestamp.today())

layout = html.Div(
    [
        html.H1("Dashboard"),

        # ตัวเลือก
        html.Div(
            [
                html.Div(
                    [
                        html.Label("ปีงบประมาณ (เริ่ม ก.ย.)"),
                        dcc.Dropdown(
                            id="dd-fy",
                            options=[{"label": f"{y}/{(y+1)%100:02d}", "value": y} for y in _fy_list],
                            value=_default_fy,
                            clearable=False,
                            style={"width":"220px"}
                        ),
                    ],
                    style={"display":"inline-block","marginRight":"20px"}
                ),
                html.Div(
                    [
                        html.Label("ช่วงเวลา (เดือนล่าสุด)"),
                        dcc.Dropdown(
                            id="dd-window",
                            options=[
                                {"label":"3 เดือน","value":3},
                                {"label":"6 เดือน","value":6},
                                {"label":"9 เดือน","value":9},
                                {"label":"12 เดือน","value":12},
                            ],
                            value=3, clearable=False, style={"width":"150px"}
                        ),
                    ],
                    style={"display":"inline-block"}
                ),
            ],
            style={"marginBottom":"14px"}
        ),

        dcc.Graph(id="fig-monthly"),
        dcc.Graph(id="fig-bycar"),
        dcc.Store(id="orders-cache", data=_orders_df.to_dict("records")),
    ]
)

# ---------- Callbacks ----------
@callback(
    Output("fig-monthly","figure"),
    Output("fig-bycar","figure"),
    Input("dd-fy","value"),
    Input("dd-window","value"),
    State("orders-cache","data"),
)
def update_figs(fy, months_window, cache):
    df_orders = _ensure_types(pd.DataFrame(cache or []))
    fy = int(fy) if fy is not None else _fiscal_year(pd.Timestamp.today())
    months_window = int(months_window or 3)
    # กราฟที่ 1: ยอดค่าซ่อมรายเดือน (ปีงบประมาณ; เดือนแรกคือ ก.ย.)
    fig1 = _fig_monthly(df_orders, fy)
    # กราฟที่ 2: ยอดค่าซ่อมรวมรายคันในรอบ N เดือนล่าสุด
    fig2 = _fig_by_car(df_orders, months_window)
    return fig1, fig2
