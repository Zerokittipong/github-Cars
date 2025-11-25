# fleet/db.py
from __future__ import annotations
import os
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_SQLITE = PROJECT_DIR / "fleet.db"
DATABASE_URL = os.getenv("FLEET_DB_URL", f"sqlite:///{DEFAULT_SQLITE.as_posix()}")
print(f"[DB] Using -> {DATABASE_URL}")

UPLOAD_DIR = (Path(__file__).resolve().parent / "uploads" / "cars")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(DATABASE_URL, echo=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

def init_users_table():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                position   TEXT,
                org        TEXT
            )
        """))
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(users)")).all()}
        if "position" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN position TEXT"))
        if "org" not in cols:
            conn.execute(text("ALTER TABLE users ADD COLUMN org TEXT"))

def init_cars_table():
    # อย่างน้อยต้องมี id และ plate เพราะหน้า Usage select cars.plate
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS cars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plate  TEXT NOT NULL UNIQUE,
                model  TEXT,
                brand  TEXT,
                color  TEXT,
                year   INTEGER,
                status  TEXT DEFAULT 'available',      -- available/in_use/maintenance/lost
                asset_number   TEXT,
                vehicle_type   TEXT,                  -- รย.1 / รย.2 / รย.3
                description    TEXT,
                chassis_number TEXT,
                engine_number  TEXT,
                pdf_path       TEXT,
                car_condition  TEXT DEFAULT 'ปกติ', 
                caretaker_org  TEXT
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_cars_id ON cars (id)"))
# ✅ เติมคอลัมน์ที่ขาดให้ตารางเดิม (กัน error no such column)
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(cars)")).all()}
        def add_missing(name, ddl):
            if name not in cols:
                conn.execute(text(f"ALTER TABLE cars ADD COLUMN {ddl}"))
                cols.add(name)

        add_missing("brand",   "brand TEXT")
        add_missing("model",   "model TEXT")
        add_missing("color",   "color TEXT")
        add_missing("year",    "year INTEGER")
        add_missing("status",  "status TEXT DEFAULT 'available'")
        add_missing("asset_number",   "asset_number TEXT")
        add_missing("vehicle_type",   "vehicle_type TEXT")
        add_missing("description",    "description TEXT")
        add_missing("chassis_number", "chassis_number TEXT")
        add_missing("engine_number",  "engine_number TEXT")
        add_missing("pdf_path",       "pdf_path TEXT")
        add_missing("car_condition", "car_condition TEXT DEFAULT 'ปกติ'")
        add_missing("caretaker_org", "caretaker_org TEXT")

        # ให้แถวเก่าที่ status ยังว่าง เป็น 'available'
        conn.execute(text("UPDATE cars SET status='available' WHERE status IS NULL"))
        
def init_usage_logs_table():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS usage_logs (
                id INTEGER NOT NULL,
                car_id INTEGER,
                borrower_id INTEGER,
                start_time DATETIME,
                end_time   DATETIME,
                purpose    VARCHAR,
                returned_at       DATETIME,
                is_maintenance    INTEGER DEFAULT 0,
                planned_end_time  DATETIME,
                PRIMARY KEY (id),
                FOREIGN KEY(car_id)      REFERENCES cars (id),
                FOREIGN KEY(borrower_id) REFERENCES users (id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_usage_logs_id ON usage_logs (id)"))
        cols = {r[1] for r in conn.execute(text("PRAGMA table_info(usage_logs)")).all()}
        def add_missing(name, ddl):
            if name not in cols:
                conn.execute(text(f"ALTER TABLE usage_logs ADD COLUMN {ddl}"))
                cols.add(name)
        add_missing("returned_at",      "returned_at DATETIME")
        add_missing("is_maintenance",   "is_maintenance INTEGER DEFAULT 0")
        add_missing("planned_end_time", "planned_end_time DATETIME")

def init_maintenance_tables():
    with engine.begin() as conn:
        # Header table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS maintenance_orders (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                car_id        INTEGER NOT NULL,
                repair_date   TEXT,        -- YYYY-MM-DD
                accept_date   TEXT,        -- YYYY-MM-DD
                committee     TEXT,        -- เก็บชื่อหลายคนคั่นด้วย , หรือจะเก็บ id ก็ได้
                center_name   TEXT,
                note          TEXT,
                total_qty     INTEGER DEFAULT 0,
                subtotal      REAL    DEFAULT 0.0,
                vat           REAL    DEFAULT 0.0,
                grand_total   REAL    DEFAULT 0.0,
                pdf_path      TEXT,
                FOREIGN KEY(car_id) REFERENCES cars(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_maint_orders_id ON maintenance_orders (id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_maint_orders_car ON maintenance_orders (car_id)"))

        # Items table
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS maintenance_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id    INTEGER NOT NULL,
                item_no     INTEGER,
                description TEXT,
                qty         INTEGER DEFAULT 1,
                unit_price  REAL    DEFAULT 0.0,
                amount      REAL    DEFAULT 0.0,
                FOREIGN KEY(order_id) REFERENCES maintenance_orders(id)
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_maint_items_order ON maintenance_items (order_id)"))

        # ---- NEW: ตารางเชื่อมกรรมการตรวจรับ (order_id ↔ user_id) ----
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS maintenance_committee (
                order_id INTEGER NOT NULL,
                user_id  INTEGER NOT NULL,
                PRIMARY KEY (order_id, user_id),
                FOREIGN KEY(order_id) REFERENCES maintenance_orders(id) ON DELETE CASCADE,
                FOREIGN KEY(user_id)  REFERENCES users(id)              ON DELETE RESTRICT
            )
        """))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_mc_order ON maintenance_committee (order_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_mc_user  ON maintenance_committee (user_id)"))
        
     
        # (กันพลาด schema เก่า) เติมคอลัมน์ที่หายไป
        def ensure_cols(table, pairs):
            cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table})")).all()}
            for name, ddl in pairs:
                if name not in cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {ddl}"))

        ensure_cols("maintenance_orders", [
            ("note",        "note TEXT"),
            ("pdf_path",    "pdf_path TEXT"),
            ("total_qty",   "total_qty INTEGER DEFAULT 0"),
            ("subtotal",    "subtotal REAL DEFAULT 0.0"),
            ("vat",         "vat REAL DEFAULT 0.0"),
            ("grand_total", "grand_total REAL DEFAULT 0.0"),
        ])

def backfill_committees_from_legacy():
    """ย้ายข้อมูลจาก maintenance_orders.committee (TEXT รายชื่อคั่น ,) → maintenance_committee
       ชื่อที่หา user_id ไม่เจอจะถูกข้ามไป"""
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))

        users = conn.execute(text("SELECT id, full_name FROM users")).mappings().all()
        name2id = {u["full_name"].strip(): u["id"] for u in users}

        orders = conn.execute(text("""
            SELECT id, committee
            FROM maintenance_orders
            WHERE committee IS NOT NULL AND TRIM(committee) <> ''
        """)).mappings().all()

        for o in orders:
            names = [s.strip() for s in (o["committee"] or "").split(",") if s.strip()]
            uids  = [name2id[n] for n in names if n in name2id]
            if not uids:
                continue
            conn.execute(text("DELETE FROM maintenance_committee WHERE order_id=:oid"), {"oid": o["id"]})
            conn.execute(
                text("INSERT OR IGNORE INTO maintenance_committee (order_id, user_id) VALUES (:oid, :uid)"),
                [{"oid": o["id"], "uid": uid} for uid in uids]
            )


def init_carlendar():
    with engine.begin() as conn:
        conn.execute(text("""
    CREATE TABLE IF NOT EXISTS car_calendar (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        car_id       INTEGER NOT NULL,     -- FK ไปที่ cars.id
        start_date   DATE NOT NULL,        -- วันที่เริ่มใช้รถ
        end_date     DATE NOT NULL,        -- วันที่สิ้นสุดการใช้รถ
        user_name    TEXT NOT NULL,        -- ชื่อผู้ใช้รถ
        note         TEXT,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(car_id) REFERENCES cars(id) ON DELETE CASCADE
    );
"""))

def init_db():
    # ถ้ามี ORM models อื่น ๆ ก็ import เพื่อ create_all ได้ แต่ไม่บังคับ
    try:
        from . import models  # noqa: F401
        Base.metadata.create_all(bind=engine)
    except Exception:
        pass
    # สำคัญ: ทำให้ทั้ง 3 ตารางพร้อมใช้งาน
    init_users_table()
    init_cars_table()
    init_usage_logs_table()
    init_maintenance_tables()
    init_carlendar()

def install_usage_triggers():
    with engine.begin() as conn:
        conn.execute(text("PRAGMA foreign_keys = ON"))

        conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS usage_ins_set_in_use
        AFTER INSERT ON usage_logs
        WHEN NEW.returned_at IS NULL
        BEGIN
          UPDATE cars SET status='in_use' WHERE id=NEW.car_id;
        END;
        """))

        conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS usage_upd_set_available
        AFTER UPDATE OF returned_at ON usage_logs
        WHEN NEW.returned_at IS NOT NULL
        BEGIN
          UPDATE cars
          SET status='available'
          WHERE id=NEW.car_id
            AND NOT EXISTS (
              SELECT 1 FROM usage_logs
              WHERE car_id=NEW.car_id AND returned_at IS NULL
            );
        END;
        """))

        conn.execute(text("""
        CREATE TRIGGER IF NOT EXISTS usage_del_maybe_set_available
        AFTER DELETE ON usage_logs
        BEGIN
          UPDATE cars
          SET status='available'
          WHERE id=OLD.car_id
            AND NOT EXISTS (
              SELECT 1 FROM usage_logs
              WHERE car_id=OLD.car_id AND returned_at IS NULL
            );
        END;
        """))

        conn.execute(text("""
        CREATE INDEX IF NOT EXISTS ix_usage_active
        ON usage_logs(car_id)
        WHERE returned_at IS NULL;
        """))

    print("✅ ติดตั้ง Trigger สำหรับอัปเดตสถานะรถสำเร็จ")


# --- 3. ฟังก์ชันรีเซ็ตสถานะรถทั้งหมด (ใช้ครั้งเดียวตอนกู้ระบบ) ---
def reconcile_cars_once():
    with engine.begin() as conn:
        conn.execute(text("""
        UPDATE cars
        SET status = CASE
          WHEN EXISTS (
            SELECT 1 FROM usage_logs ul
            WHERE ul.car_id = cars.id AND ul.returned_at IS NULL
          ) THEN 'in_use'
          ELSE 'available'
        END;
        """))
    print("✅ รีเซ็ตสถานะรถทั้งหมดเรียบร้อย")



if __name__ == "__main__":
    init_db()
    install_usage_triggers()   # ติดตั้งทริกเกอร์ (มีผลกับเหตุการณ์อนาคต)
    # reconcile_cars_once()
    

# --- ชั่วคราว: ปิดรายการ usage ที่ค้างของ car_id 8 ---
    # from sqlalchemy import text
    # with engine.begin() as conn:
    #     conn.execute(text("""
    #         UPDATE usage_logs
    #         SET returned_at = datetime('now')
    #         WHERE car_id = 8 AND returned_at IS NULL
    #     """))
    # reconcile_cars_once()
    # --- ลบโค้ดบล็อกนี้หลังรันเสร็จ ---

    print("✅ Database initialized")