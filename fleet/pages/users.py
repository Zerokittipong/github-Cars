# pages/users.py
from dash import html, dcc, dash_table, callback, Input, Output, State
import dash
import pandas as pd
from sqlalchemy import text
from fleet.db import engine, SessionLocal, init_users_table


dash.register_page(__name__, path="/users", name="Users")


# สร้างตาราง/คอลัมน์ที่ต้องใช้ (ครั้งเดียว)
init_users_table()

ORG_OPTIONS = [
    {"label": "สสป ที่ 1", "value": "สสป ที่ 1"},
    {"label": "สสป ที่ 2", "value": "สสป ที่ 2"},
    {"label": "สสป ที่ 3", "value": "สสป ที่ 3"},
    {"label": "สสป ที่ 4", "value": "สสป ที่ 4"},
    {"label": "สบท",     "value": "สบท"},
]

def fetch_users_df():
    with engine.begin() as conn:
        rows = conn.execute(text("SELECT id, full_name, position, org FROM users ORDER BY id ASC")).mappings().all()
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["id","full_name","position","org"])

layout = html.Div(
    [
        html.H1("Users"),
        dcc.Store(id="user-store"),  # เก็บ snapshot ล่าสุดสำหรับทำ diff

        # -------- แถบเพิ่มผู้ใช้งาน --------
        html.Div(
            [
                html.Label("ชื่อ นามสกุล *", className="mr-2"),
                dcc.Input(id="inp-fullname", type="text", placeholder="เช่น สมชาย ใจดี",
                          style={"width": "240px", "marginRight": "8px"}),

                html.Label("ตำแหน่ง", className="mr-2"),
                dcc.Input(id="inp-position", type="text", placeholder="เช่น พนักงานขับรถ",
                          style={"width": "200px", "marginRight": "8px"}),

                html.Label("หน่วยงาน", className="mr-2"),
                dcc.Dropdown(id="inp-org", options=ORG_OPTIONS, placeholder="เลือกหน่วยงาน",
                             clearable=True, style={"width": "200px", "display": "inline-block", "marginRight": "8px"}),

                html.Button("➕ เพิ่มผู้ใช้งาน", id="btn-add", n_clicks=0),
                dcc.Checklist(id="chk-del", options=[{"label":"โหมดลบ","value":"on"}], value=[],
                              style={"display":"inline-block","marginLeft":"12px"}),
                html.Div(id="msg", style={"color":"crimson","marginTop":"6px"}),
            ],
            style={"marginBottom":"10px"},
        ),

        # -------- ตาราง --------
        dash_table.DataTable(
            id="tbl-users",
            columns=[
                {"name": "ID", "id": "id", "type": "numeric", "editable": False},
                {"name": "ชื่อ นามสกุล", "id": "full_name", "type": "text", "editable": True},
                {"name": "ตำแหน่ง", "id": "position", "type": "text", "editable": True},
                {"name": "หน่วยงาน", "id": "org", "presentation": "dropdown"},
            ],
            data=[],  # จะใส่ผ่าน callback
            editable=True,
            row_deletable=False,  # toggle ด้วย chk-del
            dropdown={"org": {"options": ORG_OPTIONS}},
            filter_action="native",
            sort_action="native",
            page_action="native",
            page_current=0,
            page_size=10,
            style_cell={"fontSize":"14px","padding":"6px","whiteSpace":"normal","height":"auto"},
            style_cell_conditional=[
                {"if":{"column_id":"id"}, "width":"60px","maxWidth":"60px","minWidth":"60px","textAlign":"center"},
                {"if":{"column_id":"full_name"},"width":"30%"},
                {"if":{"column_id":"position"},"width":"22%"},
                {"if":{"column_id":"org"},"width":"18%"},
            ],
            style_header={"backgroundColor":"#f8f6ff","fontWeight":"bold"},
        ),
    ]
)

# -------- โหลดข้อมูลครั้งแรก -> table + store --------
@callback(
    Output("tbl-users", "data"),
    Output("user-store", "data"),
    Input("tbl-users", "id"),   # ทริกเกอร์ตอนเพจ mount
    prevent_initial_call=False,
)
def load_users(_):
    df = fetch_users_df()
    return df.to_dict("records"), df.to_dict("records")

# -------- toggle โหมดลบ --------
@callback(
    Output("tbl-users", "row_deletable"),
    Input("chk-del", "value"),
)
def toggle_delete_mode(v):
    return "on" in (v or [])

# -------- เพิ่มผู้ใช้ใหม่ (INSERT) --------
@callback(
    Output("tbl-users", "data", allow_duplicate=True),
    Output("user-store", "data", allow_duplicate=True),
    Output("msg", "children"),
    Input("btn-add", "n_clicks"),
    State("inp-fullname", "value"),
    State("inp-position", "value"),
    State("inp-org", "value"),
    prevent_initial_call=True,
)
def add_user(n, full_name, position, org):
    if not n:
        raise dash.exceptions.PreventUpdate
    if not (full_name and str(full_name).strip()):
        return dash.no_update, dash.no_update, "กรุณากรอก ‘ชื่อ นามสกุล’"

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (full_name, position, org) VALUES (:fn, :pos, :org)"),
            {"fn": full_name.strip(), "pos": (position or "").strip(), "org": org or ""}
        )

    df = fetch_users_df()
    return df.to_dict("records"), df.to_dict("records"), ""

# -------- Persist การแก้ไข/ลบจาก DataTable -> DB (UPSERT+DELETE แบบ diff) --------
@callback(
    Output("tbl-users", "data", allow_duplicate=True),
    Output("user-store", "data", allow_duplicate=True),
    Input("tbl-users", "data"),
    State("user-store", "data"),
    prevent_initial_call=True,
)
def persist_changes(new_rows, old_rows):
    # new_rows: หลังผู้ใช้แก้ไข/ลบบนตาราง
    new_df = pd.DataFrame(new_rows or [])
    old_df = pd.DataFrame(old_rows or [])

    new_ids = set(new_df["id"].astype(int)) if not new_df.empty else set()
    old_ids = set(old_df["id"].astype(int)) if not old_df.empty else set()

    deleted_ids = old_ids - new_ids
    kept_ids    = new_ids & old_ids

    with engine.begin() as conn:
        # ลบแถวที่หายไป
        if deleted_ids:
            conn.execute(text(f"DELETE FROM users WHERE id IN ({','.join([':id'+str(i) for i,_ in enumerate(deleted_ids)])})"),
                         {('id'+str(i)): v for i, v in enumerate(deleted_ids)})

        # อัปเดตแถวที่แก้ไข
        if kept_ids:
            new_map = {int(r["id"]): r for r in new_rows}
            old_map = {int(r["id"]): r for r in old_rows}
            for _id in kept_ids:
                n, o = new_map[_id], old_map[_id]
                if (n.get("full_name") != o.get("full_name")) or (n.get("position") != o.get("position")) or (n.get("org") != o.get("org")):
                    conn.execute(
                        text("""UPDATE users
                                SET full_name = :fn, position = :pos, org = :org
                                WHERE id = :id"""),
                        {"fn": (n.get("full_name") or "").strip(),
                         "pos": (n.get("position") or "").strip(),
                         "org": n.get("org") or "",
                         "id": int(_id)}
                    )

    # รีโหลดจาก DB ให้แน่ใจว่า data ตรง
    df = fetch_users_df()
    return df.to_dict("records"), df.to_dict("records")
