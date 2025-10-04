# fleet/pages/usage.py
import dash
from dash import html, dcc, dash_table, Input, Output, State, callback, ctx, no_update, exceptions
import pandas as pd
from datetime import datetime, timedelta
from sqlalchemy import text
from fleet.db import SessionLocal, engine
from fleet.models import UsageLog, Car, User


dash.register_page(__name__, path="/usage", name="Usage")

# ---------- helpers ----------
# ---------- schema guard: add returned_at if missing ----------
def ensure_returned_at_column():
    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(usage_logs)")).fetchall()]
        if "returned_at" not in cols:
            conn.execute(text("ALTER TABLE usage_logs ADD COLUMN returned_at DATETIME"))
            conn.commit()


#เพิ่มคอลัมน์ is_maintenance
def ensure_is_maintenance_column():
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(usage_logs)")).fetchall()]
        if "is_maintenance" not in cols:
            conn.execute(text("ALTER TABLE usage_logs ADD COLUMN is_maintenance INTEGER DEFAULT 0"))
            conn.commit()
            
def ensure_planned_end_column():
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(usage_logs)")).fetchall()]
        if "planned_end_time" not in cols:
            conn.execute(text("ALTER TABLE usage_logs ADD COLUMN planned_end_time DATETIME"))
            conn.commit()

            
def open_usage_options():
    df = load_usage_df()
    if df.empty:
        return []
    df = df[df["status"].isin(["in_use", "overdue","maintenance"])]
    opts = []
    for _, r in df.iterrows():
        label = f'#{r["id"]} | {r["plate"]} | {r["borrower"]} | เริ่ม {r["start_time"]}'
        opts.append({"label": label, "value": int(r["id"])})
    return opts

def load_car_options(only_available=True):
    with SessionLocal() as s:
        q = s.query(Car)
        if only_available:
            q = q.filter(Car.status == "available")
        cars = q.order_by(Car.plate.asc()).all()
        return [{"label": f"{c.plate} ({(c.brand or '')} {(c.model or '')})".strip(), "value": c.id} for c in cars]

def load_user_options():
    with SessionLocal() as s:
        users = s.query(User).order_by(User.full_name.asc()).all()
        return [{"label": u.full_name, "value": u.id} for u in users]

def to_iso_from_date_hh_mm(date_str: str | None, hh: str | None, mm: str | None) -> str | None:
    if not date_str or hh is None or mm is None:
        return None
    return f"{date_str}T{hh.zfill(2)}:{mm.zfill(2)}:00"

def _hh_options():
    return [{"label": f"{h:02d}", "value": f"{h:02d}"} for h in range(24)]

def _mm_options(step=5):
    return [{"label": f"{m:02d}", "value": f"{m:02d}"} for m in range(0, 60, step)]

def _filter_status(df: pd.DataFrame, status_value: str) -> pd.DataFrame:
    if df.empty or status_value == "all":
        return df
    return df[df["status"] == status_value].reset_index(drop=True)

def create_usage(
    car_id: int,
    borrower_id: int,
    start_iso: str,
    end_iso: str | None,                # planned end
    purpose: str | None,
    is_maint: bool = False
) -> str:

    if not car_id or not borrower_id or not start_iso:
        return "❌ โปรดเลือกทะเบียนรถ/ผู้เบิก และวันเวลาเริ่ม"

    # parse start
    try:
        start_dt = datetime.fromisoformat(start_iso)
    except Exception:
        return "❌ รูปแบบวันเวลาเริ่มไม่ถูกต้อง"

    # parse planned end (optional)
    planned_end_dt = None
    if end_iso:
        try:
            planned_end_dt = datetime.fromisoformat(end_iso)
        except Exception:
            return "❌ รูปแบบวันเวลากำหนดคืนไม่ถูกต้อง"
        if planned_end_dt < start_dt:
            return "❌ กำหนดวันคืนต้องไม่ก่อนเวลาเริ่ม"

    with SessionLocal() as s:
        car = s.get(Car, car_id)
        user = s.get(User, borrower_id)
        if not car or not user:
            return "❌ ไม่พบรถหรือผู้ใช้"

        # กันทับซ้อน
        if car.status in ("in_use", "maintenance"):
            return f"❌ รถ {car.plate} อยู่ในสถานะ {car.status} อยู่แล้ว"

        # สร้าง usage
        usg = UsageLog(
            car_id=car.id,
            borrower_id=user.id,
            start_time=start_dt,
            planned_end_time=planned_end_dt,     # <— ถ้ามีคอลัมน์นี้
            purpose=(purpose or "").strip() or None,
            is_maintenance=bool(is_maint),       # <— ถ้ามีคอลัมน์นี้
        )
        s.add(usg)

        # อัปเดตสถานะรถ
        car.status = "maintenance" if is_maint else "in_use"

        try:
            s.commit()
        except IntegrityError as e:
            s.rollback()
            return f"❌ บันทึกไม่สำเร็จ: {e.orig}"

        return f"✅ บันทึกการเบิก #{usg.id} สำเร็จ ({'maintenance' if is_maint else 'in_use'})"
#คืนรถ
def return_car_at(usage_id: int, end_iso: str | None) -> str:
    """
    ปิดรายการการใช้งาน (คืนรถ) พร้อมตั้ง end_time และเปลี่ยนสถานะรถเป็น available
    """
    # ถ้าไม่ระบุเวลา ให้ใช้เวลาปัจจุบัน
    if not end_iso:
        end_dt = datetime.now()
    else:
        try:
            end_dt = datetime.fromisoformat(end_iso)
        except Exception:
            return "❌ รูปแบบวันเวลา 'คืนรถ' ไม่ถูกต้อง"

    with SessionLocal() as s:  # type: Session
        usg = s.get(UsageLog, usage_id)
        if not usg:
            return f"❌ ไม่พบรายการการใช้ #{usage_id}"

        if usg.returned_at:
            return f"ℹ️ รายการ #{usage_id} คืนรถแล้วก่อนหน้า"

        # ป้องกันกรณีคืนก่อนเวลาเริ่ม
        if end_dt < usg.start_time:
            return "❌ เวลาคืนรถต้องไม่ก่อนเวลาเริ่มใช้"

        # ตั้งเวลาคืนจริง และสถานะรถกลับเป็น available
        usg.returned_at = end_dt

        car = s.get(Car, usg.car_id)
        if car:
            car.status = "available"

        s.commit()
        return f"✅ คืนรถเรียบร้อย (#{usage_id})"

def _compose_iso(date_str, hh, mm):
    if not date_str:
        return None
    hh = hh or "00"
    mm = mm or "00"
    return f"{date_str}T{hh}:{mm}:00"

def load_usage_df() -> pd.DataFrame:
    ensure_returned_at_column()
    ensure_is_maintenance_column()
    ensure_planned_end_column()
    with SessionLocal() as s:
        q = (
            s.query(
                UsageLog.id.label("id"),
                Car.plate.label("plate"),
                User.full_name.label("borrower"),
                UsageLog.start_time,
                #UsageLog.end_time,
                UsageLog.planned_end_time,
                UsageLog.returned_at,
                UsageLog.is_maintenance,
                UsageLog.purpose,
            )
            .join(Car, Car.id == UsageLog.car_id)
            .join(User, User.id == UsageLog.borrower_id)
            .order_by(UsageLog.id.desc())
        )
        df = pd.read_sql(q.statement, s.bind)
    df = df.rename(columns={"planned_end_time": "planned_return"})


    # สถานะ
    now = pd.Timestamp.now()
    def _status(r):
        if pd.notna(r["returned_at"]) and r["returned_at"] != "":
            return "returned"
        if r.get("is_maintenance"):
            return "maintenance"
        if pd.notna(r.get("planned_return")) and pd.Timestamp(r["planned_return"]) < now:
            return "overdue"
        return "in_use"
    df["status"] = df.apply(_status, axis=1)
 
# format datetime
    for col in ["start_time", "planned_return", "returned_at"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col]).dt.strftime("%Y-%m-%d %H:%M").fillna("")
            #df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
    return df
    
#ฟังก์ชั่นลบ  
def all_usage_options():
    df = load_usage_df()
    if df.empty:
        return []
    opts = []
    for _, r in df.iterrows():
        label = f'#{r["id"]} | {r["plate"]} | {r["borrower"]} | {r["status"]} | เริ่ม {r["start_time"]}'
        opts.append({"label": label, "value": int(r["id"])})
    return opts
def delete_usage(usage_id: int) -> str:
    with SessionLocal() as s:
        u = s.query(UsageLog).get(usage_id)
        if not u:
            return "❌ ไม่พบรายการที่จะลบ"
        # ถ้ายังไม่คืน ให้ปล่อยรถกลับ available
        if u.returned_at is None and u.car:
            u.car.status = "available"
        s.delete(u)
        s.commit()
    return "🗑️ ลบรายการแล้ว"


#ฟังก์ชันช่วยกรองช่วงวัน
def _as_dt(date_str: str | None, end_of_day=False):
    if not date_str:
        return None
    dt = datetime.fromisoformat(date_str)
    return dt.replace(hour=23, minute=59, second=59) if end_of_day else dt.replace(hour=0, minute=0, second=0)

def filter_by_range(df, range_start: str | None, range_end: str | None):
    """เก็บรายการที่ช่วง [start_time, planned_return] ซ้อนทับช่วงที่เลือก
       ถ้า planned_return ว่าง → ใช้ start_time เป็นปลายช่วงเดียวกัน"""
    if df.empty or (not range_start and not range_end):
        return df
    rs = _as_dt(range_start) or datetime.min
    re = _as_dt(range_end, end_of_day=True) or datetime.max

    st = pd.to_datetime(df["start_time"])
    pe = pd.to_datetime(df["planned_return"]).fillna(st)
    mask = (pe >= rs) & (st <= re)
    return df[mask].reset_index(drop=True)



# ---------- layout ----------
def layout():
    ensure_returned_at_column()
    ensure_is_maintenance_column()
    ensure_planned_end_column()
    full_df = load_usage_df()

    return html.Div([
        html.H2("Usage Logs"),

        # ตัวกรองสถานะ
        html.Div([
    html.Label("Status"),
    dcc.Dropdown(
        id="status-filter",
        options=[
            {"label": "ทั้งหมด", "value": "all"},
            {"label": "กำลังใช้งาน", "value": "in_use"},
            {"label": "เกินกำหนด", "value": "overdue"},
            {"label": "คืนแล้ว", "value": "returned"},
            {"label": "Maintenance", "value": "maintenance"},
        ],
        value="all",
        clearable=False,
        style={"width": 220}
    ),
    dcc.Checklist(
        id="usg-open-only",
        options=[{"label": "แสดงเฉพาะรายการที่ยังไม่คืน (in_use + overdue)", "value": "open"}],
        value=[],
        style={"marginLeft": "12px"}
    ),
    # ▼▼ เพิ่มช่วงวัน ▼▼
    html.Div([
        html.Label("ช่วงวัน:"),
        dcc.DatePickerRange(
            id="range-filter",
            display_format="YYYY-MM-DD",
            start_date=None, end_date=None
        ),
        html.Button("🔎 ค้นหา", id="btn-search", style={"marginLeft": "8px"}),
        html.Button("รีเซ็ตช่วงวัน", id="btn-reset-range", style={"marginLeft": "6px"})
    ], style={"marginLeft": "12px"})
], style={"display": "flex", "alignItems": "center", "gap": 6, "marginBottom": 8}),

    
# ฟอร์มสร้าง usage (มี end_time เป็นกำหนดวันคืน)
        html.Div([
            html.Div([html.Label("ทะเบียนรถ *"),
                      dcc.Dropdown(id="usg-car", options=load_car_options(True), placeholder="เลือกทะเบียนรถ")],
                     style={"flex": 2, "minWidth": 240, "marginRight": 8}),
            html.Div([html.Label("ผู้เบิก *"),
                      dcc.Dropdown(id="usg-user", options=load_user_options(), placeholder="เลือกผู้เบิก")],
                     style={"flex": 2, "minWidth": 220, "marginRight": 8}),
            html.Div([html.Label("วันเริ่ม *"),
                      dcc.DatePickerSingle(id="usg-start-date", display_format="YYYY-MM-DD")],
                     style={"flex": 1.3, "minWidth": 170, "marginRight": 8}),
            html.Div([html.Label("เวลาเริ่ม *"),
                      html.Div([
                          dcc.Dropdown(id="usg-start-hh", options=_hh_options(), placeholder="HH",
                                       style={"width": "90px", "display": "inline-block", "marginRight": "4px"}),
                          dcc.Dropdown(id="usg-start-mm", options=_mm_options(5), placeholder="MM",
                                       style={"width": "90px", "display": "inline-block"}),
                      ])], style={"flex": 1.5, "minWidth": 200, "marginRight": 8}),
            html.Div([html.Label("กำหนดวันคืน"),
                      dcc.DatePickerSingle(id="usg-end-date", display_format="YYYY-MM-DD")],
                     style={"flex": 1.3, "minWidth": 170, "marginRight": 8}),
            html.Div([html.Label("กำหนดเวลา"),
                      html.Div([
                          dcc.Dropdown(id="usg-end-hh", options=_hh_options(), placeholder="HH",
                                       style={"width": "90px", "display": "inline-block", "marginRight": "4px"}),
                          dcc.Dropdown(id="usg-end-mm", options=_mm_options(5), placeholder="MM",
                                       style={"width": "90px", "display": "inline-block"}),
                      ])], style={"flex": 1.5, "minWidth": 200, "marginRight": 8}),
            html.Div([html.Label("วัตถุประสงค์"),
                      dcc.Input(id="usg-purpose", type="text", placeholder="เช่น ออกภาคสนามติดตามงาน เชียงใหม่ ลำพูน ",
                                style={"width": "100%"})],
                     style={"flex": 3, "minWidth": 260}),
        ], style={"display": "flex", "flexWrap": "wrap", "gap": 6, "alignItems": "end"}),
            html.Div([
                html.Label(""),
                dcc.Checklist(
                    id="usg-maint",
                    options=[{"label": "Maintenance (นำรถเข้าซ่อม)", "value": "1"}],
                    #value=[],
                    style={"marginTop": "6px"}
                )
            ], style={"flex": 2, "minWidth": 240}),
        html.Div([
            html.Button("➕ บันทึกการเบิก", id="btn-create"),
            html.Button("🔄 โหลดทะเบียนรถว่าง", id="btn-reload-cars", style={"marginLeft": "8px"}),
            html.Button("🗑️ ลบรายการ", id="btn-delete", style={"marginLeft": 8, "color": "#B00020"}),

            html.Span(" | ", style={"margin": "0 8px"}),

            dcc.Dropdown(id="del-usage", options=[], placeholder="เลือกรายการเพื่อ 'ลบ'",
                 style={"width": 420, "display": "inline-block"}),

            dcc.Dropdown(id="ret-usage", options=open_usage_options(),
                 placeholder="เลือกรายการที่ยังไม่คืน", style={"width": 420, "display": "inline-block"}),

            dcc.DatePickerSingle(id="ret-date", display_format="YYYY-MM-DD",
                         style={"marginLeft": "6px", "display": "inline-block"}),

            dcc.Dropdown(id="ret-hh", options=_hh_options(), placeholder="HH",
                 style={"width": "80px", "display": "inline-block", "marginLeft": "6px"}),

            dcc.Dropdown(id="ret-mm", options=_mm_options(5), placeholder="MM",
                 style={"width": "80px", "display": "inline-block", "marginLeft": "4px"}),

            html.Button("✅ คืนรถ", id="btn-return", style={"marginLeft": "8px"}),

            html.Span(id="usg-msg", style={"marginLeft": "12px"})
        ], style={"margin": "10px 0"}),


        dash_table.DataTable(
            id="usage-table",
            data=(full_df.to_dict("records") if not full_df.empty else []),
            columns=[{"name": "ID", "id": "id"},
                     {"name": "ทะเบียน", "id": "plate"},
                     {"name": "ผู้เบิก", "id": "borrower"},
                     {"name": "เริ่มใช้", "id": "start_time"},
                     {"name": "กำหนดวันคืน", "id": "planned_return"},
                     {"name": "คืนจริง", "id": "returned_at"},
                     {"name": "วัตถุประสงค์", "id": "purpose"},
                     {"name": "สถานะ", "id": "status"}],
            page_size=10, sort_action="native", filter_action="native",
            style_table={"overflowX": "auto"},
            #export_format="xlsx",            # หรือ "csv" ก็ได้
            #export_headers="display",
            #export_merge_headers=True,
            style_cell_conditional=[
        {"if": {"column_id": "id"}, "width": "64px", "minWidth": "56px", "maxWidth": "80px", "textAlign": "center"},
    ],
            style_data_conditional=[
                # เหลือง: กำลังใช้งาน
                {"if": {"filter_query": "{status} = 'in_use'", "column_id": "status"},
                 "backgroundColor": "#FFF3CD", "color": "#856404"},
                # แดง: เกินกำหนด
                {"if": {"filter_query": "{status} = 'overdue'", "column_id": "status"},
                 "backgroundColor": "#F8D7DA", "color": "#842029"},
                # เขียว: คืนแล้ว
                {"if": {"filter_query": "{status} = 'returned'", "column_id": "status"},
                 "backgroundColor": "#D1E7DD", "color": "#0F5132"},
                {"if": {"filter_query": "{status} = 'maintenance'", "column_id": "status"},
                 "backgroundColor": "#E0E7FF", "color": "#1E3A8A"},  # ฟ้าอมม่วง
            ],
        ),
    ])

#---------- callbacks ----------
@callback(
    Output("usg-msg", "children", allow_duplicate=True),
    Output("usage-table", "data", allow_duplicate=True),
    Output("usg-car", "options", allow_duplicate=True),
    Output("ret-usage", "options", allow_duplicate=True),
    Output("del-usage", "options", allow_duplicate=True),
    Output("del-usage", "value", allow_duplicate=True),
    Input("btn-delete", "n_clicks"),
    State("del-usage", "value"),
    State("status-filter", "value"),
    State("usg-open-only", "value"),
    State("range-filter", "start_date"),
    State("range-filter", "end_date"),
    prevent_initial_call=True
)
def on_delete(n, usage_id, status_value, open_only_values, range_start, range_end):
    if not n or not usage_id:
        raise dash.exceptions.PreventUpdate

    msg = delete_usage(usage_id)

    # รีโหลดตาราง + options ที่เกี่ยวข้อง
    df_full = load_usage_df()
    if "open" in (open_only_values or []):
        df_full = df_full[df_full["status"].isin(["in_use", "overdue", "maintenance"])]
    if status_value and status_value != "all":
        df_full = df_full[df_full["status"] == status_value]
    df_full = filter_by_range(df_full, range_start, range_end)

    return (msg,
            df_full.to_dict("records"),
            load_car_options(True),
            open_usage_options(),
            all_usage_options(),
            None)

    
# สร้างการเบิก (เก็บ end_time เป็นกำหนดวันคืน)
@callback(
    # ===== Outputs =====
    Output("usg-msg", "children", allow_duplicate=True),
    Output("usage-table", "data", allow_duplicate=True),
    Output("usg-car", "options", allow_duplicate=True),
    Output("ret-usage", "options", allow_duplicate=True),
    Output("del-usage", "options", allow_duplicate=True),
    Output("del-usage", "value", allow_duplicate=True),

    # ===== Inputs =====
    Input("btn-create", "n_clicks"),

    # ===== States ===== (เรียงลำดับให้ตรงกับพารามิเตอร์ฟังก์ชัน)
    State("usg-car", "value"),
    State("usg-user", "value"),
    State("usg-start-date", "date"),
    State("usg-start-hh", "value"),
    State("usg-start-mm", "value"),
    State("usg-end-date", "date"),
    State("usg-end-hh", "value"),
    State("usg-end-mm", "value"),
    State("usg-purpose", "value"),
    State("usg-maint", "value"),            # <<<< ensure this is included
    State("status-filter", "value"),
    State("usg-open-only", "value"),
    State("range-filter", "start_date"),
    State("range-filter", "end_date"),
    prevent_initial_call=True
)
def on_create_usage(n_clicks,
                    car_id, user_id,
                    start_date, start_hh, start_mm,
                    end_date, end_hh, end_mm,
                    purpose, maint_values,              # <<<< and included here
                    status_value, open_only_values,
                    range_start, range_end):

    if not n_clicks:
        raise exceptions.PreventUpdate

    # build ISO strings
    if not start_date:
        return ("❌ โปรดเลือกวันเริ่ม", dash.no_update, dash.no_update,
                dash.no_update, dash.no_update, dash.no_update)

    hh = (start_hh or "00").zfill(2)
    mm = (start_mm or "00").zfill(2)
    start_iso = f"{start_date}T{hh}:{mm}:00"

    end_iso = None
    if end_date:
        eh = (end_hh or "00").zfill(2)
        em = (end_mm or "00").zfill(2)
        end_iso = f"{end_date}T{eh}:{em}:00"

    is_maint = ("1" in (maint_values or []))

    # === สร้าง usage ===
    msg = create_usage(car_id, user_id, start_iso, end_iso, purpose, is_maint)

    # === Reload ตาราง + dropdowns หลังบันทึก ===
    df_full = load_usage_df()
    if "open" in (open_only_values or []):
        df_full = df_full[df_full["status"].isin(["in_use", "overdue", "maintenance"])]
    if status_value and status_value != "all":
        df_full = df_full[df_full["status"] == status_value]
    df_full = filter_by_range(df_full, range_start, range_end)

    return (
        msg,
        df_full.to_dict("records"),
        load_car_options(True),
        open_usage_options(),
        all_usage_options(),
        None
    )

# โหลดทะเบียนรถว่างใหม่
@callback(
    Output("usg-car", "options", allow_duplicate=True),
    Input("btn-reload-cars", "n_clicks"),
    prevent_initial_call=True
)
def reload_available_cars(_):
    return load_car_options(True)

# กรองตารางด้วย status / open-only
@callback(
    Output("usage-table", "data", allow_duplicate=True),
    Input("status-filter", "value"),
    Input("usg-open-only", "value"),
    prevent_initial_call=True
)
def on_filter(status_value, open_only_values):
    df_full = load_usage_df()
    if "open" in (open_only_values or []):
        df_full = df_full[df_full["status"].isin(["in_use", "overdue","maintenance"])]
    df = _filter_status(df_full, status_value)
    return df.to_dict("records")

# ตั้งค่า default วันเวลาคืน เมื่อเลือก usage ที่ยังไม่คืน
@callback(
    Output("ret-date", "date", allow_duplicate=True),
    Output("ret-hh", "value", allow_duplicate=True),
    Output("ret-mm", "value", allow_duplicate=True),
    Input("ret-usage", "value"),
    prevent_initial_call=True
)
def on_pick_usage_for_return(usage_id):
    if not usage_id:
        raise dash.exceptions.PreventUpdate
    now = datetime.now()
    return now.strftime("%Y-%m-%d"), f"{now.hour:02d}", f"{(now.minute // 5) * 5:02d}"

# คืนรถ (ตั้ง returned_at; ไม่แตะ end_time)
@callback(
    Output("usg-msg", "children", allow_duplicate=True),
    Output("usage-table", "data", allow_duplicate=True),
    Output("usg-car", "options", allow_duplicate=True),
    Output("ret-usage", "options", allow_duplicate=True),
    Output("ret-usage", "value", allow_duplicate=True),
    Output("ret-date", "date", allow_duplicate=True),
    Output("ret-hh", "value", allow_duplicate=True),
    Output("ret-mm", "value", allow_duplicate=True),
    Input("btn-return", "n_clicks"),
    State("ret-usage", "value"),
    State("ret-date", "date"),
    State("ret-hh", "value"),
    State("ret-mm", "value"),
    State("status-filter", "value"),
    State("usg-open-only", "value"),
    prevent_initial_call=True
)
def on_return(n, usage_id, date_str, hh, mm, status_value, open_only_values):
    if not n or not usage_id:
        raise dash.exceptions.PreventUpdate
    if not (date_str and hh is not None and mm is not None):
        return ("❌ โปรดเลือกรายการและกำหนดวัน/เวลา", dash.no_update, dash.no_update,
                dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update)

    end_iso = to_iso_from_date_hh_mm(date_str, hh, mm)
    msg = return_car_at(usage_id, end_iso)

    df_full = load_usage_df()
    if "open" in (open_only_values or []):
        df_full = df_full[df_full["status"].isin(["in_use", "overdue","maintenance"])]
    df = _filter_status(df_full, status_value)
    car_opts = load_car_options(True)
    ret_opts = open_usage_options()

    # เคลียร์คอนโทรลคืนรถ
    return (msg, df.to_dict("records"), car_opts, ret_opts, None, None, None, None)

#Callback “ค้นหา”
@callback(
    Output("usage-table", "data", allow_duplicate=True),
    Input("btn-search", "n_clicks"),
    State("status-filter", "value"),
    State("usg-open-only", "value"),
    State("range-filter", "start_date"),
    State("range-filter", "end_date"),
    prevent_initial_call=True
)
def on_search(n, status_value, open_only_values, start_date, end_date):
    if not n:
        raise dash.exceptions.PreventUpdate

    # ถ้าเลือกวันเดียว → end = start
    if start_date and not end_date:
        end_date = start_date

    df_full = load_usage_df()

    # open only → เหลือ in_use + overdue
    if "open" in (open_only_values or []):
        df_full = df_full[df_full["status"].isin(["in_use", "overdue","maintenance"])]

    # status filter
    if status_value and status_value != "all":
        df_full = df_full[df_full["status"] == status_value]

    # date-range filter
    df_full = filter_by_range(df_full, start_date, end_date)
    return df_full.to_dict("records")


#“รีเซ็ตช่วงวัน” (ให้ล้างค่า + แสดงทั้งตาราง)  
@callback(
    Output("range-filter", "start_date", allow_duplicate=True),
    Output("range-filter", "end_date", allow_duplicate=True),
    Output("usage-table", "data", allow_duplicate=True),
    Input("btn-reset-range", "n_clicks"),
    State("status-filter", "value"),
    State("usg-open-only", "value"),
    prevent_initial_call=True
)
def reset_range(n, status_value, open_only_values):
    if not n:
        raise dash.exceptions.PreventUpdate
    df_full = load_usage_df()
    if "open" in (open_only_values or []):
        df_full = df_full[df_full["status"].isin(["in_use", "overdue","maintenance"])]
    if status_value and status_value != "all":
        df_full = df_full[df_full["status"] == status_value]
    return None, None, df_full.to_dict("records")

