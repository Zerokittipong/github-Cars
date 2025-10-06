import base64, os
import dash
from dash import html, dcc, dash_table, Input, Output, State, callback, no_update
import pandas as pd
from sqlalchemy import text
from fleet.db import engine as db_engine, UPLOAD_DIR

dash.register_page(__name__, path="/maintenance", name="Maintenance")

# เก็บไฟล์แนบของใบงาน
MAINT_UPLOAD_DIR = (UPLOAD_DIR.parent / "maintenance")
MAINT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ---------- helpers ----------
def q(sql, params=None):
    with db_engine.begin() as conn:
        return conn.execute(text(sql), params or {})

def cars_options():
    rows = q("SELECT id, plate FROM cars ORDER BY plate").mappings().all()
    return [{"label": r["plate"], "value": r["id"]} for r in rows]

def users_options():
    rows = q("SELECT id, full_name FROM users ORDER BY full_name").mappings().all()
    return [{"label": r["full_name"], "value": r["full_name"]} for r in rows]   # เก็บเป็นชื่อ

def fetch_orders_df():
    rows = q("""
        SELECT o.id, c.plate, o.repair_date, o.accept_date,
               o.center_name, o.committee, o.total_qty, o.subtotal, o.vat, o.grand_total, o.pdf_path
        FROM maintenance_orders o
        LEFT JOIN cars c ON c.id = o.car_id
        ORDER BY COALESCE(o.accept_date, o.repair_date) DESC, o.id DESC
    """).mappings().all()
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
        "id","plate","repair_date","accept_date","center_name","committee",
        "total_qty","subtotal","vat","grand_total","pdf_path"
    ])
    df["has_pdf"] = df["pdf_path"].apply(lambda p: "✓" if p else "")
    return df

def fetch_items_df(order_id:int):
    rows = q("""
        SELECT id, item_no, description, qty, unit_price, amount
        FROM maintenance_items
        WHERE order_id=:oid
        ORDER BY COALESCE(item_no, id)
    """, {"oid": order_id}).mappings().all()
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
        "id","item_no","description","qty","unit_price","amount"
    ])

# ---------- layout ----------
layout = html.Div(
    [
        html.H1("Maintenance"),

        dcc.Store(id="maint-current-order-id"),
        dcc.Store(id="maint-items-store"),
        dcc.Store(id="orders-store"),
        
        dcc.Download(id="maint-export"),
        dcc.Download(id="maint-pdf-download"),
        dcc.Download(id="maint-items-export"),

        html.Div(
            [
                html.Div(
                    [
                        html.Label("ทะเบียนรถ"),
                        dcc.Dropdown(id="sel-car", options=cars_options(), placeholder="เลือกทะเบียน", clearable=False,
                                     style={"width":"200px"}),
                    ],
                    style={"display":"inline-block","marginRight":"12px"}
                ),
                html.Div(
                    [
                        html.Label("วันเข้าซ่อม"),
                        dcc.DatePickerSingle(id="date-repair"),
                    ],
                    style={"display":"inline-block","marginRight":"12px"}
                ),
                html.Div(
                    [
                        html.Label("วันตรวจรับ"),
                        dcc.DatePickerSingle(id="date-accept"),
                    ],
                    style={"display":"inline-block","marginRight":"12px"}
                ),
                html.Div(
                    [
                        html.Label("ศูนย์ซ่อม"),
                        dcc.Input(id="in-center", type="text", style={"width":"220px"}),
                    ],
                    style={"display":"inline-block","marginRight":"12px"}
                ),
                html.Div(
                    [
                        html.Label("กรรมการตรวจรับ (เลือกหลายคน)"),
                        dcc.Dropdown(id="sel-committee", options=users_options(), multi=True, placeholder="เลือกชื่อ"),
                    ],
                    style={"display":"inline-block","minWidth":"300px","verticalAlign":"top","marginRight":"12px"}
                ),
                html.Div(
                    [
                        html.Label("หมายเหตุ"),
                        dcc.Input(id="in-note", type="text", style={"width":"280px"}),
                    ],
                    style={"display":"inline-block","marginRight":"12px"}),
            ],
            style={"marginBottom":"10px"}
        ),

        # ปุ่มเครื่องมือ
        html.Div(
            [
        # กลุ่มซ้าย: ปุ่มการทำงาน + ข้อความสถานะ
                html.Div(
                    [
                        html.Button("🆕 ใบงานใหม่", id="btn-new"),
                        html.Button("💾 บันทึกใบงาน", id="btn-save"),
                        html.Button("⬇️ Export CSV", id="btn-export"),
                        html.Button("⬇️ ดาวน์โหลด PDF", id="btn-download-pdf"),
                        html.Span(id="msg_maint", style={"marginLeft":"10px","color":"crimson"}),
                    ],
                    style={"display":"flex","gap":"6px","alignItems":"center"}
                ),

        # กลุ่มขวา: แนบ PDF (ดันไปชิดขวา)
                dcc.Upload(
                    id="upload-maint-pdf",
                    children=html.Div(["📄 แนบ PDF", " ", html.A("(เลือกไฟล์)")]),
                    accept="application/pdf",
                    multiple=False,
                    style={
                        "display":"inline-block",
                        "padding":"4px 10px",
                        "border":"1px dashed #aaa",
                        "borderRadius":"8px",
                        "marginLeft":"auto",          # <<— ดันไปขวาสุด
                    },
                ),
            ],
            style={"display":"flex","alignItems":"center","gap":"8px","marginBottom":"10px"}
        ),

        # ตารางรายการ
        html.Div(
            [
                html.H4("รายการซ่อม/อะไหล่", style={"margin":"6px 0"}),  # ลดระยะห่าง
                dash_table.DataTable(
                    id="tbl-items",
                    data=[],
                    columns=[
                        {"name":"#", "id":"item_no", "type":"numeric", "editable":True},
                        {"name":"รายการ", "id":"description", "type":"text", "editable":True},
                        {"name":"จำนวน", "id":"qty", "type":"numeric", "editable":True},
                        {"name":"ราคา/หน่วย", "id":"unit_price", "type":"numeric", "editable":True},
                        {"name":"ยอดเงิน", "id":"amount", "type":"numeric", "editable":False},
                    ],
                    editable=True,
                    row_deletable=True,
                    page_action="none",
                    style_table={"maxHeight":"45vh","overflowY":"auto","minWidth":"700px"},
                    style_cell={"padding":"6px","fontSize":"14px"},
                    style_header={"backgroundColor":"#f8f6ff","fontWeight":"bold"},
                ),
            ],
            style={"marginBottom":"10px"}   # เว้นนิดเดียวก่อนแถวปุ่ม “เพิ่มรายการ…”
        ),
        html.Div(
            [
                html.Button("➕ เพิ่มรายการ", id="btn-add-item", style={"marginRight":"6px"}),
                html.Button("Export รายการ (CSV)", id="btn-export-items", style={"marginRight":"10px"}),
                html.Div(id="totals-box", style={"display":"inline-block","marginLeft":"12px","fontWeight":"600"}),
                html.Span(id="msg_items", style={"marginLeft":"10px","color":"#2b6"}),
            ],
            style={"marginBottom":"16px","marginTop":"6px"}
        ),

        html.Hr(),

        # รายการใบงานทั้งหมด (คลิกเพื่อโหลด)
        html.H4("ประวัติใบงานซ่อม"),
        html.Div(
            [
                dcc.Input(
                    id="maint-search",
                    placeholder="พิมพ์คำค้น เช่น ทะเบียน / ศูนย์ซ่อม / ชื่อกรรมการ",
                    type="text",
                    debounce=True,
                    style={"width":"360px","marginRight":"8px"}
                ),
                html.Button("ค้นหา", id="btn-search"),
                html.Button("ล้าง", id="btn-clear", style={"marginLeft":"6px"}),
            ],
            style={"margin":"6px 0 10px"}
        ),
        dash_table.DataTable(
            id="tbl-orders",
            data=[],
            columns=[
                {"name":"ID","id":"id","type":"numeric"},
                {"name":"ทะเบียน","id":"plate"},
                {"name":"วันเข้าซ่อม","id":"repair_date"},
                {"name":"วันตรวจรับ","id":"accept_date"},
                {"name":"ศูนย์ซ่อม","id":"center_name"},
                {"name":"กรรมการ","id":"committee"},
                {"name":"แถว","id":"total_qty","type":"numeric"},
                {"name":"ยอด","id":"grand_total","type":"numeric"},
                {"name":"PDF","id":"has_pdf"},
            ],
            row_selectable="single",
            page_action="native",
            page_size=10,
            style_table={"overflowX":"auto"},
            style_cell={"padding":"6px","fontSize":"14px"},
            style_header={"backgroundColor":"#f8f6ff","fontWeight":"bold"},
        ),
    ]
)

# ---------- callbacks ----------

# โหลดเริ่มต้น
@callback(
    Output("tbl-orders","data"),
    Output("tbl-items","data"),
    Output("maint-items-store","data"),
    Output("maint-current-order-id","data"),
    Output("orders-store","data"), 
    Input("tbl-orders","id"),
    prevent_initial_call=False
)
def init_page(_):
    orders = fetch_orders_df()
    empty_items = pd.DataFrame(columns=["id","item_no","description","qty","unit_price","amount"])
    return (orders.to_dict("records"),
            empty_items.to_dict("records"),
            empty_items.to_dict("records"),
            None,
            orders.to_dict("records")
    ) 

# เลือกใบงาน -> โหลดฟอร์ม + รายการ
@callback(
    Output("sel-car","value"),
    Output("date-repair","date"),
    Output("date-accept","date"),
    Output("in-center","value"),
    Output("sel-committee","value"),
    Output("in-note","value"),
    Output("tbl-items","data", allow_duplicate=True),
    Output("maint-items-store","data", allow_duplicate=True),
    Output("maint-current-order-id","data", allow_duplicate=True),
    Input("tbl-orders","derived_virtual_selected_rows"),
    State("tbl-orders","derived_virtual_data"),
    prevent_initial_call=True
)
def load_order(sel_rows, vdata):
    if not sel_rows:
        return no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update, no_update
    idx = sel_rows[0]
    order = vdata[idx]
    # โหลด header
    header = q("SELECT * FROM maintenance_orders WHERE id=:i", {"i": order["id"]}).mappings().first()
    # รายการ
    items_df = fetch_items_df(order["id"])
    # committee เก็บเป็นสตริง -> list
    committee_list = [s.strip() for s in (header["committee"] or "").split(",") if s.strip()]
    return (header["car_id"], header["repair_date"], header["accept_date"], header["center_name"],
            committee_list, header["note"] or "",
            items_df.to_dict("records"), items_df.to_dict("records"), order["id"])

# เพิ่มแถวรายการ
@callback(
    Output("tbl-items","data", allow_duplicate=True),
    Output("maint-items-store","data", allow_duplicate=True),
    Input("btn-add-item","n_clicks"),
    State("tbl-items","data"),
    prevent_initial_call=True
)
def add_item(n, rows):
    rows = rows or []
    rows.append({"id": None, "item_no": len(rows)+1, "description":"", "qty":1, "unit_price":0.0, "amount":0.0})
    return rows, rows

# คำนวณยอดเงิน/รวม
@callback(
    Output("tbl-items","data", allow_duplicate=True),
    Output("maint-items-store","data", allow_duplicate=True),
    Output("totals-box","children"),
    Input("tbl-items","data"),
    prevent_initial_call=True
)
def recalc(rows):
    df = pd.DataFrame(rows or [])
    if df.empty:
        return rows, rows, "รวมแถว: 0 | Subtotal: 0.00 | VAT: 0.00 | Total: 0.00"
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce").fillna(0).astype(int)
    df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").fillna(0.0)
    df["amount"] = (df["qty"] * df["unit_price"]).round(2)
    total_qty = int(df["qty"].sum())
    subtotal = float(df["amount"].sum())
    vat = round(subtotal * 0.07, 2)  # ปรับอัตราได้
    total = round(subtotal + vat, 2)
    txt = f"รวมแถว: {total_qty} | Subtotal: {subtotal:,.2f} | VAT: {vat:,.2f} | Total: {total:,.2f}"
    return df.to_dict("records"), df.to_dict("records"), txt

# บันทึกใบงาน
@callback(
    Output("tbl-orders","data", allow_duplicate=True),
    Output("orders-store","data", allow_duplicate=True),
    Output("msg_maint","children"),
    Input("btn-save","n_clicks"),
    State("maint-current-order-id","data"),
    State("sel-car","value"),
    State("date-repair","date"),
    State("date-accept","date"),
    State("in-center","value"),
    State("sel-committee","value"),
    State("in-note","value"),
    State("maint-items-store","data"),
    prevent_initial_call=True
)
def save_order(n, order_id, car_id, repair_date, accept_date, center, committee_vals, note, items_rows):
    if not n:
        return no_update, ""
    if not car_id:
        return no_update, "กรุณาเลือกทะเบียนรถ"
    items_df = pd.DataFrame(items_rows or [])
    # คำนวณรวม
    items_df["qty"] = pd.to_numeric(items_df["qty"], errors="coerce").fillna(0).astype(int)
    items_df["unit_price"] = pd.to_numeric(items_df["unit_price"], errors="coerce").fillna(0.0)
    items_df["amount"] = (items_df["qty"] * items_df["unit_price"]).round(2)
    total_qty = int(items_df["qty"].sum())
    subtotal = float(items_df["amount"].sum())
    vat = round(subtotal * 0.07, 2)
    total = round(subtotal + vat, 2)
    committee = ", ".join(committee_vals or [])

    with db_engine.begin() as conn:
        if order_id:
            # update header
            conn.execute(text("""
                UPDATE maintenance_orders SET
                    car_id=:car, repair_date=:rd, accept_date=:ad,
                    committee=:cm, center_name=:cn, note=:note,
                    total_qty=:tq, subtotal=:sub, vat=:vat, grand_total=:gt
                WHERE id=:id
            """), {
                "car":car_id, "rd":repair_date, "ad":accept_date,
                "cm":committee, "cn":center or "", "note":note or "",
                "tq":total_qty, "sub":subtotal, "vat":vat, "gt":total,
                "id":int(order_id)
            })
            # replace items
            conn.execute(text("DELETE FROM maintenance_items WHERE order_id=:i"), {"i": int(order_id)})
            for i, row in items_df.reset_index(drop=True).iterrows():
                conn.execute(text("""
                    INSERT INTO maintenance_items (order_id, item_no, description, qty, unit_price, amount)
                    VALUES (:oid, :no, :desc, :q, :up, :amt)
                """), {"oid": int(order_id), "no": i+1, "desc": row.get("description",""),
                       "q": int(row.get("qty") or 0), "up": float(row.get("unit_price") or 0.0),
                       "amt": float(row.get("amount") or 0.0)})
        else:
            # insert header
            res = conn.execute(text("""
                INSERT INTO maintenance_orders
                  (car_id, repair_date, accept_date, committee, center_name, note,
                   total_qty, subtotal, vat, grand_total)
                VALUES (:car, :rd, :ad, :cm, :cn, :note, :tq, :sub, :vat, :gt)
            """), {"car":car_id, "rd":repair_date, "ad":accept_date, "cm":committee,
                   "cn":center or "", "note":note or "", "tq":total_qty,
                   "sub":subtotal, "vat":vat, "gt":total})
            new_id = res.lastrowid
            for i, row in items_df.reset_index(drop=True).iterrows():
                conn.execute(text("""
                    INSERT INTO maintenance_items (order_id, item_no, description, qty, unit_price, amount)
                    VALUES (:oid, :no, :desc, :q, :up, :amt)
                """), {"oid": int(new_id), "no": i+1, "desc": row.get("description",""),
                       "q": int(row.get("qty") or 0), "up": float(row.get("unit_price") or 0.0),
                       "amt": float(row.get("amount") or 0.0)})

    orders = fetch_orders_df()
    return orders.to_dict("records"), orders.to_dict("records"), "บันทึกเรียบร้อย"

# แนบ/โหลด PDF
@callback(
    Output("tbl-orders","data", allow_duplicate=True),
    Output("msg_maint","children", allow_duplicate=True),
    Output("orders-store","data", allow_duplicate=True),
    Input("upload-maint-pdf","contents"),
    State("upload-maint-pdf","filename"),
    State("maint-current-order-id","data"),
    prevent_initial_call=True
)
def upload_pdf(contents, filename, order_id):
    if not contents or not order_id:
        return no_update, "กรุณาเลือกใบงานก่อนแนบไฟล์"
    header, b64 = contents.split(",", 1)
    pdf_bytes = base64.b64decode(b64)
    path = (MAINT_UPLOAD_DIR / f"maint_{order_id}.pdf").as_posix()
    with open(path, "wb") as f:
        f.write(pdf_bytes)
    q("UPDATE maintenance_orders SET pdf_path=:p WHERE id=:i", {"p": path, "i": int(order_id)})
    orders = fetch_orders_df()
    return orders.to_dict("records"), orders.to_dict("records"), "อัปโหลด PDF สำเร็จ"  # ✅

@callback(
    Output("maint-pdf-download","data"),
    Input("btn-download-pdf","n_clicks"),
    State("maint-current-order-id","data"),
    prevent_initial_call=True
)
def download_pdf(n, order_id):
    if not order_id:
        return no_update
    row = q("SELECT pdf_path FROM maintenance_orders WHERE id=:i", {"i": int(order_id)}).first()
    if not row or not row[0] or not os.path.exists(row[0]):
        return no_update
    return dcc.send_file(row[0])

# Export
@callback(
    Output("maint-export","data"),
    Input("btn-export","n_clicks"),
    prevent_initial_call=True
)
def export_orders(n):
    df = fetch_orders_df().drop(columns=["has_pdf"])
    return dcc.send_data_frame(df.to_csv, "maintenance_orders.csv", index=False, encoding="utf-8-sig", lineterminator="\r\n")

# ใบงานใหม่ = เคลียร์ฟอร์ม+ตาราง
@callback(
    Output("sel-car","value", allow_duplicate=True),
    Output("date-repair","date", allow_duplicate=True),
    Output("date-accept","date", allow_duplicate=True),
    Output("in-center","value", allow_duplicate=True),
    Output("sel-committee","value", allow_duplicate=True),
    Output("in-note","value", allow_duplicate=True),
    Output("tbl-items","data", allow_duplicate=True),
    Output("maint-items-store","data", allow_duplicate=True),
    Output("maint-current-order-id","data", allow_duplicate=True),
    Input("btn-new","n_clicks"),
    prevent_initial_call=True
)
def new_order(_):
    empty = pd.DataFrame(columns=["id","item_no","description","qty","unit_price","amount"]).to_dict("records")
    return None, None, None, "", [], "", empty, empty, None

# กรองเมื่อพิมพ์หรือกดปุ่ม
@callback(
    Output("tbl-orders","data", allow_duplicate=True),
    Input("maint-search","value"),
    State("orders-store","data"),
    prevent_initial_call=True
)
def filter_orders(keyword, orders_full):
    if not orders_full:
        return no_update

    df = pd.DataFrame(orders_full)
    if not keyword:
        # ไม่มีคำค้น → แสดงทั้งหมด
        return orders_full

    key = str(keyword).strip().lower()
    if not key:
        return orders_full

    # รองรับหลายคำคั่นช่องว่าง (แสดงถ้าตรง "คำใดคำหนึ่ง")
    terms = [t for t in key.split() if t]
    def row_match(r):
        hay = f"{r.get('plate','')} {r.get('center_name','')} {r.get('committee','')}".lower()
        return any(t in hay for t in terms)   # ถ้าอยากให้ตรง "ทุกคำ" เปลี่ยน any -> all

    filtered = [r for r in orders_full if row_match(r)]
    return filtered

# ปุ่มล้างค้นหา
@callback(
    Output("maint-search","value"),
    Output("tbl-orders","data", allow_duplicate=True),
    Input("btn-clear","n_clicks"),
    State("orders-store","data"),
    prevent_initial_call=True
)
def clear_search(n, orders_full):
    if not n:
        return no_update, no_update
    return "", (orders_full or [])
    

@callback(
    Output("maint-items-export", "data"),
    Input("btn-export-items", "n_clicks"),
    State("maint-items-store", "data"),
    State("maint-current-order-id", "data"),
    prevent_initial_call=True
)
def export_items_csv(n, rows, order_id):
    

    # ไม่มีข้อมูลก็ไม่ทำอะไร
    if not n or rows is None:
        return dash.no_update

    df = pd.DataFrame(rows)
    if df.empty:
        return dash.no_update

    # จัดลำดับคอลัมน์ให้อ่านง่าย
    cols = ["item_no", "description", "qty", "unit_price", "amount"]
    df = df.reindex(columns=[c for c in cols if c in df.columns])

    # ตั้งชื่อไฟล์ให้รู้ว่าเป็นของใบงานไหน
    filename = "maintenance_items.csv"
    if order_id:
        # ลองหาทะเบียนเพื่อใส่ในชื่อไฟล์ (ถ้าเจอ)
        with db_engine.begin() as conn:
            row = conn.execute(text("""
                SELECT c.plate
                FROM maintenance_orders o
                JOIN cars c ON c.id = o.car_id
                WHERE o.id = :i
            """), {"i": int(order_id)}).first()
        plate = (row[0] if row else "").replace(" ", "_")
        filename = f"maint_{plate or 'order'}_{order_id}_items.csv"

    # ส่งออก CSV (UTF-8 SIG เพื่อให้ Excel เปิดแล้วภาษาไทยไม่เพี้ยน)
    return dcc.send_data_frame(
        df.to_csv, filename, index=False, encoding="utf-8-sig", lineterminator="\r\n"
    )
