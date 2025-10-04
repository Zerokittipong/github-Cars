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




if __name__ == "__main__":
    init_db()
    print("✅ Database initialized")

