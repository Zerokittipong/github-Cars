# fleet/pages/cars.py
import base64, os
from pathlib import Path
import dash
from dash import html, dcc, dash_table, Input, Output, State, callback, no_update
import pandas as pd
from sqlalchemy import text
from fleet.db import engine as db_engine, UPLOAD_DIR  # absolute import (สำคัญ)

dash.register_page(__name__, path="/cars", name="Cars")

# ---------- Dropdown options ----------
CARETAKER_OPTIONS = [
    {"label":"สสป ที่ 1","value":"สสป ที่ 1"},
    {"label":"สสป ที่ 2","value":"สสป ที่ 2"},
    {"label":"สสป ที่ 3","value":"สสป ที่ 3"},
    {"label":"สสป ที่ 4","value":"สสป ที่ 4"},
    {"label":"สบท","value":"สบท"},
]


STATUS_OPTIONS = [
    {"label": "Available",    "value": "available"},
    {"label": "In use",       "value": "in_use"},
    {"label": "Maintenance",  "value": "maintenance"},
    {"label": "Lost",         "value": "lost"},  # ✅ เพิ่มคำว่า lost
]

ALLOWED_STATUSES = {"available", "in_use", "maintenance", "lost"}

CONDITION_OPTIONS = [
    {"label": "ปกติ",       "value": "ปกติ"},
    {"label": "สูญหาย",     "value": "สูญหาย"},
    {"label": "ใช้การไม่ได้", "value": "ใช้การไม่ได้"},
    {"label": "รอจำหน่าย",  "value": "รอจำหน่าย"},
]

VEHICLE_TYPES = [
    {"label": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน (รย.1)", "value": "รย.1"},
    {"label": "รถยนต์นั่งส่วนบุคคลเกิน 7 คน (รย.2)",   "value": "รย.2"},
    {"label": "รถยนต์บรรทุกส่วนบุคคล (รย.3)",          "value": "รย.3"},
]
VEHICLE_TYPE_FULL = {
    "รย.1": "รถยนต์นั่งส่วนบุคคลไม่เกิน 7 คน",
    "รย.2": "รถยนต์นั่งส่วนบุคคลเกิน 7 คน",
    "รย.3": "รถยนต์บรรทุกส่วนบุคคล",
}

BRAND_OPTIONS = [  # ✅ ยี่ห้อสำหรับฟอร์มลงทะเบียน
    {"label": "Toyota", "value": "Toyota"},
    {"label": "Honda", "value": "Honda"},
    {"label": "Isuzu", "value": "Isuzu"},
    {"label": "Mazda", "value": "Mazda"},
    {"label": "Mitsubishi", "value": "Mitsubishi"},
    {"label": "Ford", "value": "Ford"},
    {"label": "Suzuki", "value": "Suzuki"},
    {"label": "Nissan", "value": "Nissan"},
    {"label": "Hino", "value": "Hino"},
    {"label": "Fuso", "value": "Fuso"},
]

def fetch_df():
    with db_engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT
              c.id, c.plate, c.brand, c.model, c.color, c.year,
              COALESCE(
                CASE
                  WHEN EXISTS (SELECT 1 FROM usage_logs u WHERE u.car_id=c.id AND u.returned_at IS NULL AND u.is_maintenance=1) THEN 'maintenance'
                  WHEN EXISTS (SELECT 1 FROM usage_logs u WHERE u.car_id=c.id AND u.returned_at IS NULL AND u.is_maintenance=0) THEN 'in_use'
                  ELSE c.status
                END, 'available'
            ) AS status_display,
            c.asset_number, c.vehicle_type, c.description,
            c.chassis_number, c.engine_number, c.pdf_path,
            c.car_condition,                            
            c.caretaker_org  
            FROM cars c
            ORDER BY c.plate ASC
        """)).mappings().all()

    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
    "id","plate","car_condition","caretaker_org","brand","model","color","year","status_display",
    "asset_number","vehicle_type","description","chassis_number","engine_number","pdf_path"
    ])
    # ชื่อเต็มประเภทรถสำหรับแสดงผล
    df["vehicle_type_display"] = df["vehicle_type"].map(VEHICLE_TYPE_FULL).fillna(df["vehicle_type"])
    # มีไฟล์หรือไม่
    df["has_pdf"] = df["pdf_path"].apply(lambda p: "✓" if p else "")
    return df


layout = html.Div(
    [
        html.H1("Cars"),
        dcc.Store(id="cars-store"),
        dcc.Download(id="cars-download"),
        dcc.Download(id="pdf-download"),

        # ----- ฟอร์มลงทะเบียนรถ (ค่าเริ่มต้นเฉพาะตอนเพิ่ม) -----
        html.Div(
            [
                html.Label("ทะเบียน *"),
                dcc.Input(id="in-plate", type="text",
                          style={"width":"140px", "marginRight":"8px"}),

                html.Label("สภาพรถ"),
                dcc.Dropdown(id="in-condition",options=CONDITION_OPTIONS,value="ปกติ",
                             clearable=False,style={"width":"180px","display":"inline-block","marginRight":"8px"}),

                html.Label("ยี่ห้อ"),
                dcc.Dropdown(id="in-brand", options=BRAND_OPTIONS, placeholder="เลือกยี่ห้อ",
                             clearable=True, style={"width":"160px","display":"inline-block","marginRight":"8px"}),

                html.Label("รุ่น"),
                dcc.Input(id="in-model", type="text",
                          style={"width":"120px","marginRight":"8px"}),

                html.Label("ปี"),
                dcc.Input(id="in-year", type="number",
                          style={"width":"90px","marginRight":"8px"}),

                html.Label("สี"),
                dcc.Input(id="in-color", type="text",
                          style={"width":"100px","marginRight":"8px"}),

                html.Label("Asset number"),
                dcc.Input(id="in-asset", type="text",
                          style={"width":"150px","marginRight":"8px"}),

                html.Label("ประเภทรถ"),
                dcc.Dropdown(id="in-vtype", options=VEHICLE_TYPES, placeholder="เลือกประเภท",
                             clearable=True, style={"width":"280px","display":"inline-block","marginRight":"8px"}),

                html.Label("Description"),
                dcc.Input(id="in-desc", type="text",
                          style={"width":"240px","marginRight":"8px"}),

                html.Label("เลขตัวถัง"),
                dcc.Input(id="in-chassis", type="text",
                          style={"width":"180px","marginRight":"8px"}),

                html.Label("เลขเครื่อง"),
                dcc.Input(id="in-engine", type="text",
                          style={"width":"180px","marginRight":"8px"}),

                html.Button("➕ เพิ่มรถ", id="btn-add-car"),
                html.Span(id="msg_cars", style={"color":"crimson","marginLeft":"10px"}),
            ],
            style={"marginBottom":"10px"}
        ),

        # ----- ปุ่มทั่วไป -----
        html.Div(
            [
                html.Button("↳ เปิดโหมดลบ", id="btn-del-mode", n_clicks=0, style={"marginRight":"8px"}),
                html.Button("⬇️ Export CSV", id="btn-export", n_clicks=0, style={"marginRight":"8px"}),
                dcc.Upload(
                    id="upload-pdf",
                    children=html.Div(["📄 ลากไฟล์ PDF มาวาง หรือ ", html.A("เลือกไฟล์")]),
                    accept="application/pdf",
                    multiple=False,
                    style={
                        "display":"inline-block","padding":"6px 12px","border":"1px dashed #aaa",
                        "borderRadius":"8px","marginRight":"8px"
                    }
                ),
                html.Button("⬇️ ดาวน์โหลด PDF ของแถวที่เลือก", id="btn-download-pdf"),
                html.Span(id="msg_cars_upload", style={"color":"#2b6","marginLeft":"8px"}),
            ],
            style={"marginBottom":"6px"}
        ),

        # ----- ตาราง -----
        dash_table.DataTable(
            id="tbl-cars",
            data=[],

            # ✅ ย้าย "สถานะ" มาชิดขวาของ "ทะเบียน" + ล็อกห้ามแก้ 5 คอลัมน์ตามข้อกำหนด
            columns=[
                {"name":"ID","id":"id","type":"numeric","editable":False},
                {"name":"ทะเบียน","id":"plate","type":"text","editable":True},
                {"name":"สถานะ","id":"status_display","type":"text","editable":False},
                {"name":"สภาพรถ","id":"car_condition","presentation":"dropdown"},
                {"name":"ส่วนดูแล","id":"caretaker_org","presentation":"dropdown"},
                {"name":"ยี่ห้อ","id":"brand","type":"text","editable":True},
                {"name":"รุ่น","id":"model","type":"text","editable":True},
                {"name":"ปี","id":"year","type":"numeric","editable":True},
                {"name":"สี","id":"color","type":"text","editable":True},
                

                # 🔒 ปิดแก้ไขหลังลงทะเบียน (อ่านอย่างเดียว)
                {"name":"Asset number","id":"asset_number","type":"text","editable":False},
                {"name":"ประเภทรถ","id":"vehicle_type_display","type":"text","editable":False},
                {"name":"คำอธิบาย","id":"description","type":"text","editable":False},
                {"name":"เลขตัวถัง","id":"chassis_number","type":"text","editable":False},
                {"name":"เลขเครื่อง","id":"engine_number","type":"text","editable":False},

                {"name":"PDF","id":"has_pdf","editable":False},
            ],
            dropdown={
                "car_condition": {"options": CONDITION_OPTIONS},
                "caretaker_org": {"options": CARETAKER_OPTIONS},
            },
            editable=True,
            row_deletable=False,
            sort_action="native",
            filter_action="native",
            page_action="native",
            page_size=12,
            row_selectable="single",
            selected_rows=[],

  # ✅ สีพื้นตามสถานะ
            style_data_conditional=[
                {"if":{"column_id":"status_display","filter_query":'{status_display} = "available"'},
                 "backgroundColor":"#e8f7e8","color":"#1a7f37","fontWeight":"600"},
                {"if":{"column_id":"status_display","filter_query":'{status_display} = "in_use"'},
                 "backgroundColor":"#fff7cc","color":"#8a6d00","fontWeight":"600"},
                {"if":{"column_id":"status_display","filter_query":'{status_display} = "maintenance"'},
                 "backgroundColor":"#ffe0e0","color":"#a40000","fontWeight":"600"},
                {"if":{"column_id":"status_display","filter_query":'{status_display} = "lost"'},
                 "backgroundColor":"#ffe0e0","color":"#a40000","fontWeight":"600"},
            ],

            
            # ✅ ทำให้เลื่อนได้เมื่อข้อมูลยาว + ตรึง header
            fixed_rows={"headers": True},
            style_table={
                "maxHeight": "70vh",
                "overflowY": "auto",
                "overflowX": "auto",
            },

            style_cell={"fontSize":"14px","padding":"6px"},
            style_cell_conditional=[
                {"if":{"column_id":"id"},"width":"60px","textAlign":"center"},
                {"if":{"column_id":"plate"},"width":"120px"},
                {"if":{"column_id":"status_display"},"width":"150px","textAlign":"center"},
                {"if":{"column_id":"vehicle_type_display"},"width":"260px"},
                {"if":{"column_id":"has_pdf"},"width":"70px","textAlign":"center"},
                {"if":{"column_id":"caretaker_org"},"width":"140px"},
            ],
            style_header={"backgroundColor":"#f8f6ff","fontWeight":"bold"},
        ),
    ]
)

# ---------- โหลดครั้งแรก ----------
@callback(
    Output("tbl-cars","data"),
    Output("cars-store","data"),
    Input("tbl-cars","id"),
    prevent_initial_call=False
)
def load_init(_):
    df = fetch_df()
    return df.to_dict("records"), df.to_dict("records")

# ---------- เปิดโหมดลบ ----------
@callback(
    Output("tbl-cars","row_deletable"),
    Input("btn-del-mode","n_clicks")
)
def toggle_delete(n):
    return (n or 0) % 2 == 1

# ---------- เพิ่มรถใหม่ (ฟิลด์ที่ล็อก จะถูกกำหนดตั้งแต่ตอนนี้) ----------
@callback(
    Output("tbl-cars","data", allow_duplicate=True),
    Output("cars-store","data", allow_duplicate=True),
    Output("msg_cars","children"),
    Input("btn-add-car","n_clicks"),
    State("in-plate","value"),
    State("in-brand","value"),
    State("in-model","value"),
    State("in-year","value"),
    State("in-color","value"),
    State("in-asset","value"),
    State("in-vtype","value"),
    State("in-desc","value"),
    State("in-chassis","value"),
    State("in-engine","value"),
    State("in-condition","value"),     # ✅ เปลี่ยนมาใช้ตัวนี้
    prevent_initial_call=True
)
def add_car(n, plate, brand, model, year, color,
            asset, vtype, desc, chassis, engine_no, condition):
    if not n:
        return no_update, no_update, ""
    if not plate or not str(plate).strip():
        return no_update, no_update, "กรุณากรอกทะเบียน"

    # ทำความสะอาดทะเบียน (ตัดช่องว่างซ้ำ)
    plate_norm = " ".join(str(plate).split())

    # validate สภาพรถ
    allowed = {o["value"] for o in CONDITION_OPTIONS}
    cond = condition if condition in allowed else "ปกติ"

    # ตรวจทะเบียนซ้ำ (ไม่สนช่องว่าง/ตัวเล็กใหญ่)
    plate_key = "".join(plate_norm.split()).lower()

    with db_engine.begin() as conn:
        exists = conn.execute(
            text("""
                SELECT id FROM cars
                WHERE lower(replace(plate,' ','')) = :k
            """),
            {"k": plate_key},
        ).first()
        if exists:
            return no_update, no_update, f"ทะเบียน '{plate_norm}' มีอยู่แล้ว (ID {exists.id})"

        # บันทึกข้อมูลใหม่
        conn.execute(
            text("""
                INSERT INTO cars
                  (plate, status, brand, model, year, color,
                   asset_number, vehicle_type, description, chassis_number, engine_number,
                   car_condition, caretaker_org)
                VALUES
                  (:plate, 'available', :brand, :model, :year, :color,
                   :asset, :vtype, :desc, :chassis, :engine,
                   :cond, :care_org)
            """),
            {
                "plate": plate_norm,
                "brand": brand or "",
                "model": model or "",
                "year": year,
                "color": color or "",
                "asset": asset or "",
                "vtype": vtype or "",
                "desc":  desc  or "",
                "chassis": chassis or "",
                "engine":  engine_no or "",
                "cond": cond,          # สภาพรถ
                "care_org": "",        # ส่วนดูแล (เริ่มต้นว่าง ให้แก้ในตาราง)
            },
        )

    df = fetch_df()
    return df.to_dict("records"), df.to_dict("records"), "บันทึกสำเร็จ"



# ---------- แก้ไข/ลบจากตาราง -> DB ----------
@callback(
    Output("tbl-cars","data", allow_duplicate=True),
    Output("cars-store","data", allow_duplicate=True),
    Input("tbl-cars","data"),
    State("cars-store","data"),
    prevent_initial_call=True
)
def persist_changes(new_rows, old_rows):
    new_df = pd.DataFrame(new_rows or [])
    old_df = pd.DataFrame(old_rows or [])
    new_ids = set(new_df["id"].astype(int)) if not new_df.empty else set()
    old_ids = set(old_df["id"].astype(int)) if not old_df.empty else set()
    deleted = old_ids - new_ids
    kept    = new_ids & old_ids

    # คีย์ที่อนุญาตให้แก้ไข
    editable_keys = ["plate", "brand", "model", "year", "color",
                     "car_condition", "caretaker_org"]

    with db_engine.begin() as conn:
        # ลบแถวที่ถูกลบออกจาก DataTable
        if deleted:
            params = {f"id{i}": v for i, v in enumerate(deleted)}
            in_clause = ",".join(f":id{i}" for i in range(len(deleted)))
            conn.execute(text(f"DELETE FROM cars WHERE id IN ({in_clause})"), params)

        # อัปเดตแถวที่ยังอยู่
        if kept:
            nm = {int(r["id"]): r for r in new_rows}
            om = {int(r["id"]): r for r in old_rows}
            for _id in kept:
                n, o = nm[_id], om[_id]

                # มีการเปลี่ยนแปลงในฟิลด์ที่อนุญาตหรือไม่
                changed = any((n.get(k) or "") != (o.get(k) or "") for k in editable_keys)
                if changed:
                    conn.execute(
                        text("""
                            UPDATE cars SET
                                plate=:plate,
                                brand=:brand,
                                model=:model,
                                year=:year,
                                color=:color,
                                car_condition=:cond,
                                caretaker_org=:org
                            WHERE id=:id
                        """),
                        dict(
                            plate=(n.get("plate") or "").strip(),
                            brand=n.get("brand") or "",
                            model=n.get("model") or "",
                            year=n.get("year"),
                            color=n.get("color") or "",
                            cond=(n.get("car_condition") or o.get("car_condition") or "ปกติ"),
                            org=(n.get("caretaker_org") or o.get("caretaker_org") or ""),
                            id=int(_id),
                        )
                    )

    df = fetch_df()
    return df.to_dict("records"), df.to_dict("records")


# ---------- Export CSV ----------
@callback(
    Output("cars-download","data"),
    Input("btn-export","n_clicks"),
    prevent_initial_call=True
)
def export_csv(n):
    df = fetch_df().drop(columns=["has_pdf"])
    # UTF-8 + BOM ให้ Excel เดา encoding ถูก และใช้ CRLF สำหรับ Windows
    return dcc.send_data_frame(
        df.to_csv,
        "cars.csv",
        index=False,
        encoding="utf-8-sig",
        lineterminator="\r\n",
    )

# ---------- Upload PDF (ต่อคัน) ----------
@callback(
    Output("tbl-cars","data", allow_duplicate=True),
    Output("cars-store","data", allow_duplicate=True),
    Output("msg_cars_upload","children"),
    Input("upload-pdf","contents"),
    State("upload-pdf","filename"),
    State("tbl-cars","selected_rows"),
    State("tbl-cars","data"),
    prevent_initial_call=True
)
def upload_pdf(contents, filename, selected_rows, data):
    if not contents:
        return no_update, no_update, ""
    if not selected_rows:
        return no_update, no_update, "กรุณาเลือกแถวก่อนอัปโหลด PDF"

    row_idx = selected_rows[0]
    car_id = data[row_idx]["id"]

    header, b64 = contents.split(",", 1)
    pdf_bytes = base64.b64decode(b64)
    path = (UPLOAD_DIR / f"car_{car_id}.pdf").as_posix()
    with open(path, "wb") as f:
        f.write(pdf_bytes)

    with db_engine.begin() as conn:
        conn.execute(text("UPDATE cars SET pdf_path=:p WHERE id=:i"), dict(p=path, i=int(car_id)))

    df = fetch_df()
    return df.to_dict("records"), df.to_dict("records"), "อัปโหลดสำเร็จ"

# ---------- ดาวน์โหลด PDF ----------
@callback(
    Output("pdf-download","data"),
    Input("btn-download-pdf","n_clicks"),
    State("tbl-cars","selected_rows"),
    State("tbl-cars","data"),
    prevent_initial_call=True
)
def download_pdf(n, selected, rows):
    if not selected:
        return no_update
    ridx = selected[0]
    pdf_path = rows[ridx].get("pdf_path")
    if not pdf_path or not os.path.exists(pdf_path):
        return no_update
    return dcc.send_file(pdf_path)
