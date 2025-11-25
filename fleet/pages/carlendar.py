# fleet/pages/carlendar.py
import calendar as pycal
from collections import defaultdict
from datetime import date, timedelta

import dash
from dash import html, dcc, dash_table, Input, Output, State, callback, no_update
import pandas as pd
from sqlalchemy import text

from fleet.db import engine as db_engine

dash.register_page(__name__, path="/carlendar", name="Carlendar")

# ---------- helpers ----------
def fetch_users_options():
    with db_engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, full_name FROM users ORDER BY full_name ASC")
        ).mappings().all()

    return [
        {"label": r["full_name"], "value": r["full_name"]}
        for r in rows
    ]

def month_range_3months(base: date):
    """
    รับวันที่ base แล้วคืนค่า (start_date, end_date)
    ช่วง 3 เดือนล่วงหน้า เช่น base = 2025-11-10
    -> start = 2025-11-01, end = 2026-01-31
    """
    start = base.replace(day=1)

    # เดือนสุดท้ายของช่วง 3 เดือน
    m = base.month + 2  # base เดือน + 2 = รวม 3 เดือน
    y = base.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    last_day = pycal.monthrange(y, m)[1]
    end = date(y, m, last_day)
    return start, end


def fetch_car_options():
    """ดึงรายการรถสำหรับ dropdown"""
    with db_engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT id, plate
                FROM cars
                WHERE car_condition != 'สูญหาย'
                ORDER BY plate ASC
            """)
        ).mappings().all()
    return [{"label": r["plate"], "value": r["id"]} for r in rows]


def fetch_calendar_df(start_date: date, end_date: date):
    """ดึงรายการจองที่ 'ทับซ้อน' กับช่วงวันที่กำหนด"""
    with db_engine.begin() as conn:
        rows = conn.execute(
            text("""
                SELECT
                    cal.id,
                    cal.start_date,
                    cal.end_date,
                    c.plate,
                    cal.user_name,
                    cal.note
                FROM car_calendar cal
                JOIN cars c ON c.id = cal.car_id
                WHERE NOT (cal.end_date < :s OR cal.start_date > :e)
                ORDER BY cal.start_date ASC, c.plate ASC
            """),
            {"s": start_date.isoformat(), "e": end_date.isoformat()},
        ).mappings().all()

    if not rows:
        return pd.DataFrame(columns=["id", "start_date", "end_date", "plate", "user_name", "note"])

    df = pd.DataFrame(rows)
    df["start_date"] = pd.to_datetime(df["start_date"]).dt.strftime("%Y-%m-%d")
    df["end_date"]   = pd.to_datetime(df["end_date"]).dt.strftime("%Y-%m-%d")
    return df


def build_calendar_grid(year: int, month: int, df_events: pd.DataFrame):
    """สร้าง UI ปฏิทินแบบ Grid (เหมือน Outlook / Google Calendar)"""
    # เตรียม mapping วันที่ -> list ของ event
    events_by_date = defaultdict(list)
    if df_events is not None and not df_events.empty:
        tmp = df_events.copy()
        tmp["start_date"] = pd.to_datetime(tmp["start_date"]).dt.date
        tmp["end_date"]   = pd.to_datetime(tmp["end_date"]).dt.date

        month_first = date(year, month, 1)
        month_last = date(year, month, pycal.monthrange(year, month)[1])

        for _, r in tmp.iterrows():
            s = max(r["start_date"], month_first)
            e = min(r["end_date"], month_last)
            if pd.isna(s) or pd.isna(e) or s > e:
                continue
            d = s
            while d <= e:
                events_by_date[d].append(r)
                d += timedelta(days=1)

    first_weekday, num_days = pycal.monthrange(year, month)  # Monday=0
    day_names = ["จันทร์", "อังคาร", "พุธ", "พฤหัส", "ศุกร์", "เสาร์", "อาทิตย์"]

    # header ชื่อวัน
    header_row = html.Div(
        [
            html.Div(
                dn,
                style={
                    "textAlign": "center",
                    "fontWeight": "600",
                    "padding": "4px 0",
                },
            )
            for dn in day_names
        ],
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(7, 1fr)",
            "marginBottom": "4px",
        },
    )

    # cells ของวันที่
    cells = []

    # ช่องว่างก่อนวันแรกของเดือน
    for _ in range(first_weekday):
        cells.append(
            html.Div(
                "",
                style={
                    "border": "1px solid #eee",
                    "backgroundColor": "#fafafa",
                },
            )
        )

  
       # ช่องวันที่ 1..num_days
    for day in range(1, num_days + 1):
        d = date(year, month, day)
        events = events_by_date.get(d, [])

        # ข้อความแต่ละ booking
        event_divs = [
            html.Div(
                f"{ev['plate']} – {ev['user_name']}",
                style={
                    "fontSize": "11px",
                    "whiteSpace": "nowrap",
                    "overflow": "hidden",
                    "textOverflow": "ellipsis",
                },
            )
            for ev in events
        ]

        # สไตล์พื้นฐานของ cell
        cell_style = {
            "border": "1px solid #ddd",
            "padding": "4px",
            "fontSize": "12px",
            "minHeight": "80px",
            "backgroundColor": "#fff",
        }

        # ถ้าวันนี้มีการจอง → เปลี่ยนพื้นหลังเป็นฟ้าอ่อน + เน้นขอบด้านซ้าย
        if events:
            cell_style.update(
                {
                    "backgroundColor": "#e6f4ff",
                    "borderLeft": "4px solid #1a73e8",
                }
            )

        cells.append(
            html.Div(
                [
                    html.Div(
                        str(day),
                        style={
                            "fontWeight": "600",
                            "marginBottom": "2px",
                        },
                    ),
                    html.Div(event_divs),
                ],
                style=cell_style,
            )
        )


    # เติมช่องว่างท้ายเดือนให้ครบสัปดาห์สุดท้าย
    while len(cells) % 7 != 0:
        cells.append(
            html.Div(
                "",
                style={
                    "border": "1px solid #eee",
                    "backgroundColor": "#fafafa",
                },
            )
        )

    grid = html.Div(
        cells,
        style={
            "display": "grid",
            "gridTemplateColumns": "repeat(7, 1fr)",
            "gridAutoRows": "minmax(80px, auto)",
            "gap": "2px",
        },
    )

    return [
        html.H3(f"ปฏิทินประจำเดือน {month:02d}/{year}", style={"marginBottom": "8px"}),
        header_row,
        grid,
    ]


# ---------- layout ----------
layout = html.Div(
    [
        html.H1("Calendar – การจองรถ"),

        dcc.Store(id="cal-store"),
        dcc.Store(id="cal-range-store"),  # เก็บช่วง 3 เดือนที่กำลังดู

        # เลือกเดือนที่ต้องการดู (Calendar Grid จะใช้เดือนนี้)
        html.Div(
            [
                html.Label("เลือกเดือนที่ต้องการดู", style={"marginRight": "8px"}),
                dcc.DatePickerSingle(
                    id="cal-start-date",
                    display_format="YYYY-MM-DD",
                    date=date.today().replace(day=1).isoformat(),
                    style={"marginRight": "12px"},
                ),
                html.Span("ระบบจะแสดงข้อมูลจองล่วงหน้า 3 เดือนจากเดือนนี้"),
            ],
            style={"marginBottom": "12px"},
        ),

        html.Hr(),

        # ----- ฟอร์มเพิ่มการจอง (ช่วงวันที่) -----
        html.Div(
            [
                html.Label("ทะเบียนรถ *"),
                dcc.Dropdown(
                    id="cal-car-id",
                    options=[],
                    placeholder="เลือกทะเบียนรถ",
                    style={"width": "200px", "display": "inline-block", "marginRight": "8px"},
                    clearable=False,
                ),

                html.Label("ช่วงวันที่ใช้รถ *"),
                dcc.DatePickerRange(
                    id="cal-date-range",
                    display_format="YYYY-MM-DD",
                    style={"marginRight": "8px"},
                ),

                html.Label("ผู้ใช้ *"),
                html.Div(
                    dcc.Dropdown(
                        id="cal-user",
                        options=[],
                        placeholder="เลือกผู้ใช้",
                        clearable=True,
                    ),
                    style={"width": "180px", "display": "inline-block", "marginRight": "8px"},
                ),

                html.Label("หมายเหตุ"),
                dcc.Input(
                    id="cal-note",
                    type="text",
                    style={"width": "220px", "marginRight": "8px"},
                ),

                html.Button("➕ เพิ่มการจอง", id="btn-add-book"),
                html.Span(id="msg_calendar", style={"color": "crimson", "marginLeft": "10px"}),
            ],
            style={"marginBottom": "16px"},
        ),

        html.Hr(),

        # ----- Calendar Grid -----
        html.Div(id="calendar-grid", style={"marginBottom": "24px"}),

        html.Hr(),

        # ----- ตารางรายการจองแบบ list (ไว้ลบ/แก้ไขได้ง่าย) -----
        dash_table.DataTable(
            id="tbl-calendar",
            data=[],
            columns=[
                {"name": "ID", "id": "id", "type": "numeric", "editable": False},
                {"name": "เริ่มใช้", "id": "start_date", "type": "text", "editable": False},
                {"name": "สิ้นสุด", "id": "end_date", "type": "text", "editable": False},
                {"name": "ทะเบียนรถ", "id": "plate", "type": "text", "editable": False},
                {"name": "ผู้ใช้", "id": "user_name", "type": "text", "editable": True},
                {"name": "หมายเหตุ", "id": "note", "type": "text", "editable": True},
            ],
            editable=True,
            row_deletable=True,
            sort_action="native",
            filter_action="native",
            page_action="native",
            page_size=20,
            style_table={
                "maxHeight": "60vh",
                "overflowY": "auto",
            },
            style_cell={"fontSize": "14px", "padding": "6px"},
            style_header={"backgroundColor": "#f8f6ff", "fontWeight": "bold"},
            style_cell_conditional=[
                {"if": {"column_id": "id"}, "width": "60px", "textAlign": "center"},
                {"if": {"column_id": "start_date"}, "width": "110px"},
                {"if": {"column_id": "end_date"}, "width": "110px"},
                {"if": {"column_id": "plate"}, "width": "120px"},
            ],
        ),
    ]
)

@callback(
    Output("cal-user", "options"),
    Input("cal-user", "id"),
    prevent_initial_call=False
)
def load_users_for_calendar(_):
    return fetch_users_options()


# ---------- initial: โหลดรายการรถ ----------
@callback(
    Output("cal-car-id", "options"),
    Input("cal-car-id", "id"),
    prevent_initial_call=False,
)
def load_car_options(_):
    return fetch_car_options()


# ---------- โหลดข้อมูลจองตามเดือน (3 เดือนล่วงหน้า) ----------
@callback(
    Output("tbl-calendar", "data"),
    Output("cal-store", "data"),
    Output("cal-range-store", "data"),
    Input("cal-start-date", "date"),
    prevent_initial_call=False,
)
def load_calendar(start_date_str):
    base = date.fromisoformat(start_date_str) if start_date_str else date.today().replace(day=1)
    start, end = month_range_3months(base)
    df = fetch_calendar_df(start, end)
    return df.to_dict("records"), df.to_dict("records"), {
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


# ---------- Calendar Grid (อัปเดตเมื่อเปลี่ยนเดือน หรือมีการจองใหม่) ----------
@callback(
    Output("calendar-grid", "children"),
    Input("cal-start-date", "date"),
    Input("cal-store", "data"),
    prevent_initial_call=False,
)
def update_calendar_grid(start_date_str, store_data):
    base = date.fromisoformat(start_date_str) if start_date_str else date.today().replace(day=1)
    year, month = base.year, base.month
    df = pd.DataFrame(store_data or [])
    return build_calendar_grid(year, month, df)


# ---------- เพิ่มการจอง (ช่วงวันที่) ----------
@callback(
    Output("tbl-calendar", "data", allow_duplicate=True),
    Output("cal-store", "data", allow_duplicate=True),
    Output("msg_calendar", "children"),
    Input("btn-add-book", "n_clicks"),
    State("cal-car-id", "value"),
    State("cal-date-range", "start_date"),
    State("cal-date-range", "end_date"),
    State("cal-user", "value"),
    State("cal-note", "value"),
    State("cal-range-store", "data"),
    prevent_initial_call=True,
)
def add_booking(n, car_id, start_date_str, end_date_str, user_name, note, range_data):
    if not n:
        return no_update, no_update, ""
    if not car_id or not start_date_str or not end_date_str or not (user_name and user_name.strip()):
        return no_update, no_update, "กรุณาเลือกทะเบียนรถ กำหนดช่วงวันที่ และกรอกชื่อผู้ใช้"

    start_d = date.fromisoformat(start_date_str)
    end_d = date.fromisoformat(end_date_str)
    if end_d < start_d:
        return no_update, no_update, "วันสิ้นสุดต้องไม่ก่อนวันเริ่มต้น"

    with db_engine.begin() as conn:
        # ป้องกันการจองซ้อน "เป๊ะวัน" ของทะเบียนเดียวกัน (ถ้าไม่ต้องการตรวจ ลบบล็อกนี้ได้)
        exists = conn.execute(
            text("""
                SELECT id FROM car_calendar
                WHERE car_id = :cid
                  AND NOT (end_date < :s OR start_date > :e)
            """),
            {"cid": car_id, "s": start_d.isoformat(), "e": end_d.isoformat()},
        ).first()
        if exists:
            return no_update, no_update, "ทะเบียนนี้มีการจองทับซ้อนในช่วงวันที่ดังกล่าวแล้ว"

        conn.execute(
            text("""
                INSERT INTO car_calendar (car_id, start_date, end_date, user_name, note)
                VALUES (:cid, :s, :e, :u, :n)
            """),
            {
                "cid": car_id,
                "s": start_d.isoformat(),
                "e": end_d.isoformat(),
                "u": user_name.strip(),
                "n": note or "",
            },
        )

    # reload data ตามช่วง 3 เดือนเดิม
    if not range_data:
        base = date.today().replace(day=1)
        start, end = month_range_3months(base)
    else:
        start = date.fromisoformat(range_data["start"])
        end = date.fromisoformat(range_data["end"])

    df = fetch_calendar_df(start, end)
    return df.to_dict("records"), df.to_dict("records"), "บันทึกการจองสำเร็จ"


# ---------- แก้ไข/ลบรายการในตาราง list ----------
@callback(
    Output("tbl-calendar", "data", allow_duplicate=True),
    Output("cal-store", "data", allow_duplicate=True),
    Input("tbl-calendar", "data"),
    State("cal-store", "data"),
    State("cal-range-store", "data"),
    prevent_initial_call=True,
)
def persist_calendar_changes(new_rows, old_rows, range_data):
    new_df = pd.DataFrame(new_rows or [])
    old_df = pd.DataFrame(old_rows or [])

    new_ids = set(new_df["id"].astype(int)) if not new_df.empty else set()
    old_ids = set(old_df["id"].astype(int)) if not old_df.empty else set()

    deleted = old_ids - new_ids
    kept = new_ids & old_ids

    with db_engine.begin() as conn:
        # ลบแถวที่ผู้ใช้ลบออกจาก DataTable
        if deleted:
            params = {f"id{i}": v for i, v in enumerate(deleted)}
            in_clause = ",".join(f":id{i}" for i in range(len(deleted)))
            conn.execute(
                text(f"DELETE FROM car_calendar WHERE id IN ({in_clause})"),
                params,
            )

        # อัปเดตชื่อผู้ใช้ / หมายเหตุ
        if kept:
            nm = {int(r["id"]): r for r in new_rows}
            om = {int(r["id"]): r for r in old_rows}
            for _id in kept:
                n = nm[_id]
                o = om[_id]
                changed = (
                    (n.get("user_name") or "") != (o.get("user_name") or "") or
                    (n.get("note") or "") != (o.get("note") or "")
                )
                if changed:
                    conn.execute(
                        text("""
                            UPDATE car_calendar
                            SET user_name = :u, note = :n
                            WHERE id = :id
                        """),
                        {
                            "u": n.get("user_name") or "",
                            "n": n.get("note") or "",
                            "id": int(_id),
                        },
                    )

    # reload เพื่อ sync กับ Calendar Grid
    if not range_data:
        base = date.today().replace(day=1)
        start, end = month_range_3months(base)
    else:
        start = date.fromisoformat(range_data["start"])
        end = date.fromisoformat(range_data["end"])

    df = fetch_calendar_df(start, end)
    return df.to_dict("records"), df.to_dict("records")
