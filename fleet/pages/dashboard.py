# fleet/pages/dashboard.py
import numpy as np
import pandas as pd
import dash
from dash import html, dcc, Input, Output, State, callback
import plotly.express as px
from sqlalchemy import text
from zoneinfo import ZoneInfo

from fleet.db import engine as db_engine

dash.register_page(__name__, path="/", name="Dashboard")

# ---------- Time helpers ----------
TZ = ZoneInfo("Asia/Bangkok")

FISCAL_START_MONTH = 10
MONTHS_TH = ["ต.ค.","พ.ย.","ธ.ค.","ม.ค.","ก.พ.","มี.ค.","เม.ย.","พ.ค.","มิ.ย.","ก.ค.","ส.ค.","ก.ย."]

def today_local() -> pd.Timestamp:
    """เวลาวันนี้แบบ 00:00 และตัด timezone ให้เป็น naive เพื่อเทียบกับคอลัมน์ใน DB ได้ตรงกัน"""
    return pd.Timestamp.now(tz=TZ).normalize().tz_localize(None)

def _month_bounds(ts: pd.Timestamp | None = None):
    """ขอบเขตเดือนของ ts (start รวม, end ไม่รวม)"""
    ts = ts or today_local()
    start = pd.Timestamp(ts.year, ts.month, 1)
    end = start + pd.offsets.MonthBegin(1)
    return start, end

def _fiscal_year(ts: pd.Timestamp) -> int:
    return ts.year if ts.month >= FISCAL_START_MONTH else ts.year - 1

def _fy_bounds(fy: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    """รับปีงบประมาณ (เช่น 2025) แล้วคืนช่วงวันที่ [1 ต.ค. ปีนั้น, 1 ต.ค. ปีถัดไป)"""
    start = pd.Timestamp(fy, FISCAL_START_MONTH, 1)
    end   = pd.Timestamp(fy + 1, FISCAL_START_MONTH, 1)
    return start, end

# ---------- Type guards ----------
def _ensure_dt_num(df: pd.DataFrame, date_col: str, num_col: str) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df[num_col]  = pd.to_numeric(df[num_col], errors="coerce").fillna(0.0)
    return df.dropna(subset=[date_col])

def _ensure_usage_types(df: pd.DataFrame) -> pd.DataFrame:
    """แปลงชนิดคอลัมน์ usage ให้ถูกต้อง/สม่ำเสมอ"""
    if df.empty:
        return df
    df = df.copy()

    # แปลงคอลัมน์เวลาที่ต้องใช้ แล้วตัด timezone ออกให้เป็น naive เสมอ
    for c in ["start_time", "planned_end_time", "returned_at"]:
        s = pd.to_datetime(df.get(c), errors="coerce")
        if pd.api.types.is_datetime64tz_dtype(s):
            s = s.dt.tz_localize(None)
        df[c] = s

    # ให้ is_maintenance เป็น 0/1 เสมอ
    df["is_maintenance"] = (
        pd.to_numeric(df.get("is_maintenance", 0), errors="coerce")
          .fillna(0).astype(int)
    )
    return df

# ---------- Readers ----------
def read_orders() -> pd.DataFrame:
    with db_engine.begin() as conn:
        rs = conn.execute(text("""
            SELECT accept_date, grand_total, car_id
            FROM maintenance_orders
            WHERE accept_date IS NOT NULL
        """)).mappings().all()
    df = pd.DataFrame(rs)
    if df.empty:
        return df
    return _ensure_dt_num(df, "accept_date", "grand_total")

def read_usage() -> pd.DataFrame:
    with db_engine.begin() as conn:
        rs = conn.execute(text("""
            SELECT car_id, start_time, returned_at, is_maintenance, planned_end_time
            FROM usage_logs
        """)).mappings().all()
    return _ensure_usage_types(pd.DataFrame(rs))

def read_cars_status_display() -> pd.DataFrame:
    sql = text("""
    WITH m AS (
        SELECT car_id, COUNT(*) cnt
        FROM usage_logs
        WHERE returned_at IS NULL AND is_maintenance = 1
        GROUP BY car_id
    ),
    a AS (
        SELECT car_id, COUNT(*) cnt
        FROM usage_logs
        WHERE returned_at IS NULL AND IFNULL(is_maintenance,0) = 0
        GROUP BY car_id
    )
    SELECT c.id, c.plate,
           COALESCE(
             CASE
               WHEN m.cnt > 0 THEN 'maintenance'
               WHEN a.cnt > 0 THEN 'in_use'
               ELSE c.status
             END,
             c.status, 'available'
           ) AS status_display,
           COALESCE(c.car_condition,'ปกติ') AS car_condition
    FROM cars c
    LEFT JOIN m ON m.car_id = c.id
    LEFT JOIN a ON a.car_id = c.id
    WHERE COALESCE(c.car_condition,'ปกติ') = 'ปกติ'
    """)
    with db_engine.begin() as conn:
        rs = conn.execute(sql).mappings().all()
    return pd.DataFrame(rs)

def cars_lookup() -> dict[int, str]:
    with db_engine.begin() as conn:
        rs = conn.execute(text("SELECT id, plate FROM cars")).mappings().all()
    df = pd.DataFrame(rs)
    return {} if df.empty else dict(zip(df["id"], df["plate"]))


def _fiscal_year_list(df_orders: pd.DataFrame) -> list[int]:
    if df_orders.empty:
        return [_fiscal_year(today_local())]
    return sorted(df_orders["accept_date"].map(_fiscal_year).unique())

#กราฟ “ยอดซ่อมรายเดือน” ให้เรียงเดือนเริ่ม ต.ค.
def _fig_monthly(df_orders: pd.DataFrame, fy: int):
    months_th = MONTHS_TH  # เริ่ม ต.ค.

    if df_orders.empty:
        plot_df = pd.DataFrame({"month": months_th, "total": [0.0]*12})
    else:
        start = pd.Timestamp(fy, FISCAL_START_MONTH, 1)          # ต.ค. ของปีงบฯ
        end   = pd.Timestamp(fy + 1, FISCAL_START_MONTH, 1)      # ต.ค. ปีถัดไป
        df = df_orders[(df_orders["accept_date"] >= start) & (df_orders["accept_date"] < end)].copy()
        if df.empty:
            plot_df = pd.DataFrame({"month": months_th, "total": [0.0]*12})
        else:
            # map เดือนจริง → index ปีงบฯ (ต.ค.=0 ... ก.ย.=11)
            df["f_idx"] = (df["accept_date"].dt.month - FISCAL_START_MONTH) % 12
            grp = df.groupby("f_idx")["grand_total"].sum()
            totals = [float(grp.get(i, 0.0)) for i in range(12)]
            plot_df = pd.DataFrame({"month": months_th, "total": totals})

    fig = px.line(plot_df, x="month", y="total", markers=True,
                  title=f"ยอดค่าบำรุ่งรักษารวมรายเดือน (ปีงบประมาณ {fy}/{(fy+1)%100:02d})")
    fig.update_layout(yaxis_title="บาท", xaxis_title="เดือน (เริ่ม ต.ค.)")
    fig.update_yaxes(tickformat=",")
    return fig

def _fig_by_car(df_orders: pd.DataFrame, fy: int, months_window: int):
    """กราฟเส้น: ยอดซ่อมรวมรายคัน ในช่วง N เดือนนับจาก ต.ค. ของปีงบประมาณ fy"""
    car_map = cars_lookup()

    # ช่วงเวลาจาก 1 ต.ค. ของปีงบฯ fy ไปอีก N เดือน
    start = pd.Timestamp(fy, 10, 1)  # ต.ค.
    end   = start + pd.DateOffset(months=months_window)

    if df_orders.empty:
        plot_df = pd.DataFrame({"plate": [], "total": []})
    else:
        df = df_orders[(df_orders["accept_date"] >= start) &
                       (df_orders["accept_date"] <  end)].copy()
        if df.empty:
            plot_df = pd.DataFrame({"plate": [], "total": []})
        else:
            grp = df.groupby("car_id")["grand_total"].sum().sort_values(ascending=False)
            plot_df = pd.DataFrame({
                "plate": [car_map.get(i, f"ID {i}") for i in grp.index],
                "total": grp.values
            })

    title = f"ยอดค่าบำรุงรักษารวมรายคัน (นับจาก ต.ค. {fy} ถึง {months_window} เดือน)"
    fig = px.line(plot_df, x="plate", y="total", markers=True, title=title)
    fig.update_layout(yaxis_title="บาท", xaxis_title="ทะเบียนรถ")
    fig.update_yaxes(tickformat=",")
    return fig

def _ensure_types(obj) -> pd.DataFrame:
    """รองรับโค้ดเดิมที่เรียก _ensure_types; แปลง cache -> DataFrame แล้วบังคับ dtype"""
    df = pd.DataFrame(obj or [])
    return _ensure_dt_num(df, "accept_date", "grand_total")
# ---------- Preload / caches ----------
_orders_df = read_orders()
_usage_df  = read_usage()
_cars_df   = read_cars_status_display()

_fy_list    = _fiscal_year_list(_orders_df)
_default_fy = _fy_list[-1] if _fy_list else _fiscal_year(today_local())

# ---------- Layout ----------
layout = html.Div([
    html.H1("Dashboard"),

    # ตัวเลือก
    html.Div([
        html.Div([
            html.Label("ปีงบประมาณ (เริ่ม ต.ค.)"),
            dcc.Dropdown(
                id="dd-fy",
                options=[{"label": f"{y}/{(y+1)%100:02d}", "value": y} for y in _fy_list],
                value=_default_fy, clearable=False, style={"width": "220px"},
            ),
        ], style={"display": "inline-block", "marginRight": "20px"}),

        html.Div([
            html.Label("ช่วงเวลา (เดือนล่าสุด)"),
            dcc.Dropdown(
                id="dd-window",
                options=[{"label": f"{m} เดือน", "value": m} for m in (3, 6, 9, 12)],
                value=3, clearable=False, style={"width": "150px"},
            ),
        ], style={"display": "inline-block"}),
    ], style={"marginBottom": "14px"}),

    # Donut + KPI
    html.Div([
        dcc.Graph(id="fig-donut", style={"width": "38%", "display": "inline-block"}),
        html.Div([
            html.Div(id="kpi-today", className="kpi"),
            html.Div(id="kpi-month", className="kpi"),
            html.Div(id="kpi-fy", className="kpi"),
        ], style={"width": "60%", "display": "inline-block",
                  "verticalAlign": "top", "padding": "8px 12px"}),
    ], style={"marginBottom": "14px"}),

    # Top 5
    html.Div([
        dcc.Graph(id="fig-top-borrow", style={"width": "48%", "display": "inline-block"}),
        dcc.Graph(id="fig-top-repair", style={"width": "48%", "display": "inline-block"}),
    ], style={"marginBottom": "14px"}),

    # กราฟเดิม
    dcc.Graph(id="fig-monthly"),
    dcc.Graph(id="fig-bycar"),

    # caches (id ต้องไม่ซ้ำ)
    dcc.Store(id="orders-cache", data=_orders_df.to_dict("records")),
    dcc.Store(id="usage-cache",  data=_usage_df.to_dict("records")),
    dcc.Store(id="cars-cache",   data=_cars_df.to_dict("records")),
])

#เวลาตาม Time zone
def current_fiscal_year():
    return _fiscal_year(today_local())

#ป้องกันส่งข้อมูลว่างเปล่ามาพอต
def _empty_bar(title, x_col="plate", y_col="count"):
    df = pd.DataFrame({x_col: [], y_col: []})
    fig = px.bar(df, x=x_col, y=y_col, title=title)
    fig.update_yaxes(tickformat=",")
    return fig

def _empty_donut():
    df = pd.DataFrame({"label_th":["พร้อมใช้งาน","ใช้งานอยู่","เข้าซ่อม"], "count":[0,0,0]})
    return px.pie(df, values="count", names="label_th", hole=0.5,
                  title="สถานะรถ (รวม 0 คัน)")

def _fallback_outputs():
    fig_donut = _empty_donut()
    fig_top_borrow = _empty_bar("Top 5 รถที่ใช้งานบ่อยสุด (ปีงบฯ)")
    fig_top_repair = _empty_bar("Top 5 รถที่เข้าซ่อมมากสุด (ปีงบฯ)")
    kpi_today = html.H3("ใช้งานวันนี้: 0 ครั้ง")
    kpi_month = html.H3("ใช้งานเดือนนี้: 0 ครั้ง")
    kpi_fy    = html.H3("ใช้งานปีงบฯ: 0 ครั้ง")
    return fig_donut, kpi_today, kpi_month, kpi_fy, fig_top_borrow, fig_top_repair

# ---------- Callbacks ----------
@callback(
    Output("fig-monthly","figure"),
    Output("fig-bycar","figure"),
    Input("dd-fy","value"),
    Input("dd-window","value"),
    State("orders-cache","data"),
)
def update_figs(fy, months_window, cache):
    df_orders = read_orders()     # ← ใช้ alias ที่เพิ่งเพิ่ม
    fy = int(fy) if fy is not None else current_fiscal_year()
    months_window = int(months_window or 3)

    fig1 = _fig_monthly(df_orders, fy)
    fig2 = _fig_by_car(df_orders, fy, months_window)  # อย่าลืมส่ง fy เข้าไปด้วย
    return fig1, fig2

@callback(
    Output("fig-donut","figure"),
    Output("kpi-today","children"),
    Output("kpi-month","children"),
    Output("kpi-fy","children"),
    Output("fig-top-borrow","figure"),
    Output("fig-top-repair","figure"),
    Input("dd-fy","value"),
)
def update_dashboard(fy):
    try:
        fy = int(fy) if fy is not None else _fiscal_year(today_local())
        fy_start, fy_end = _fy_bounds(fy)
        today = today_local()
        m_start, m_end = _month_bounds(today)

        # -------- อ่านข้อมูลสด --------
        cars   = read_cars_status_display()
        usage  = read_usage()
        orders = read_orders()

        # ----- Donut -----
        categories = pd.Index(["available","in_use","maintenance"], name="status_display")
        if cars.empty:
            fig_donut = _empty_donut()
        else:
            donut_df = (cars.groupby("status_display")["id"]
                           .count().reindex(categories, fill_value=0)
                           .reset_index(name="count"))
            label_map = {"available":"พร้อมใช้งาน","in_use":"ใช้งานอยู่","maintenance":"เข้าซ่อม"}
            donut_df["label_th"] = donut_df["status_display"].map(label_map)
            fig_donut = px.pie(donut_df, values="count", names="label_th", hole=0.5,
                               title=f"สถานะรถ (รวม {int(donut_df['count'].sum())} คัน)")

        # ----- KPIs -----
        usage = _ensure_usage_types(usage)
        if usage.empty:
            k_today = k_month = k_fy = 0
            u_fy = pd.DataFrame()
        else:
            u = usage[usage["is_maintenance"] == 0]
            u_today = u[u["start_time"].dt.date == today.date()]
            u_month = u[(u["start_time"] >= m_start) & (u["start_time"] < m_end)]
            u_fy    = u[(u["start_time"] >= fy_start) & (u["start_time"] < fy_end)]
            k_today = len(u_today); k_month = len(u_month); k_fy = len(u_fy)
        kpi_today = html.H3(f"ใช้งานวันนี้: {k_today:,} ครั้ง")
        kpi_month = html.H3(f"ใช้งานเดือนนี้: {k_month:,} ครั้ง")
        kpi_fy    = html.H3(f"ใช้งานปีงบฯ {fy}/{(fy+1)%100:02d}: {k_fy:,} ครั้ง")

        # ----- Top 5 ใช้งานบ่อย -----
        if u_fy.empty:
            fig_top_borrow = _empty_bar("Top 5 รถที่ใช้งานบ่อยสุด (ปีงบฯ)")
        else:
            top_b = (u_fy.groupby("car_id")["start_time"]
                       .count().sort_values(ascending=False).head(5))
            cmap = cars_lookup()
            df_b = pd.DataFrame({"plate":[cmap.get(i, f"ID {i}") for i in top_b.index],
                                 "count":top_b.values})
            fig_top_borrow = px.bar(df_b, x="plate", y="count",
                                    title="Top 5 รถที่ใช้งานบ่อยสุด (ปีงบฯ)")
            fig_top_borrow.update_yaxes(tickformat=",")

        # ----- Top 5 ซ่อมบ่อย -----
        if orders.empty:
            fig_top_repair = _empty_bar("Top 5 รถที่เข้าซ่อมมากสุด (ปีงบฯ)")
        else:
            o_fy = orders[(orders["accept_date"] >= fy_start) & (orders["accept_date"] < fy_end)]
            if o_fy.empty:
                fig_top_repair = _empty_bar("Top 5 รถที่เข้าซ่อมมากสุด (ปีงบฯ)")
            else:
                top_r = (o_fy.groupby("car_id")["accept_date"]
                           .count().sort_values(ascending=False).head(5))
                cmap = cars_lookup()
                df_r = pd.DataFrame({"plate":[cmap.get(i, f"ID {i}") for i in top_r.index],
                                     "count":top_r.values})
                fig_top_repair = px.bar(df_r, x="plate", y="count",
                                        title="Top 5 รถที่เข้าซ่อมมากสุด (ปีงบฯ)")
                fig_top_repair.update_yaxes(tickformat=",")

        return fig_donut, kpi_today, kpi_month, kpi_fy, fig_top_borrow, fig_top_repair

    except Exception as e:
        # log error แล้วคืน fallback เพื่อไม่ให้ Dash เจอ None
        print("update_dashboard error:", e)
        return _fallback_outputs()
