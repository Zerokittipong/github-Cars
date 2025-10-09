# fleet/reset_db.py
from __future__ import annotations
import sys
import shutil
from datetime import datetime
from pathlib import Path
from sqlalchemy import text
from fleet.db import engine, Base, init_db
from fleet.db import install_usage_triggers, reconcile_cars_once

def _backup_sqlite():
    """สำรองไฟล์ SQLite เดิมก่อนลบทิ้ง (ถ้า backend เป็น sqlite)"""
    if engine.url.get_backend_name() != "sqlite":
        return None
    db_path = Path(engine.url.database).resolve()
    if not db_path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak_path = db_path.with_suffix(f".bak-{ts}.db")
    shutil.copy2(db_path, bak_path)
    print(f"🧰 Backup created -> {bak_path}")
    return bak_path

def _drop_all():
    """ลบทุกตาราง โดยปิด FK check ชั่วคราว (สำหรับ SQLite)"""
    with engine.begin() as conn:
        if engine.url.get_backend_name() == "sqlite":
            conn.execute(text("PRAGMA foreign_keys = OFF"))
        # ลบทุกตารางที่ map ด้วย SQLAlchemy ORM
        Base.metadata.drop_all(bind=engine)
        if engine.url.get_backend_name() == "sqlite":
            conn.execute(text("PRAGMA foreign_keys = ON"))
    print("🧨 Dropped all tables.")

def _recreate_schema():
    """สร้าง schema ใหม่ + ติดตั้ง triggers ที่จำเป็น"""
    init_db()                   # สร้างทุกตาราง (idempotent)
    install_usage_triggers()    # ติดตั้ง triggers สำหรับตาราง usage_logs
    reconcile_cars_once()       # sync สถานะรถ (เผื่อ seed มี usage ค้าง)
    print("🏗️  Recreated schema & installed triggers.")

def main():
    force = "--force" in sys.argv
    do_seed = "--seed" in sys.argv

    print(f"DB URL: {engine.url}")

    if not force:
        print(
            "\n⚠️  This will ERASE ALL DATA in the database.\n"
            "Run again with '--force' to proceed.\n"
            "Optional: add '--seed' to insert sample data after reset.\n"
            "Example:  python -m fleet.reset_db --force --seed\n"
        )
        return

    # 1) สำรอง (ถ้าเป็น SQLite)
    _backup_sqlite()

    # 2) ลบทุกตาราง
    _drop_all()

    # 3) สร้างใหม่ + ติดตั้ง triggers
    _recreate_schema()

    # 4) (ตัวเลือก) ลง seed ตัวอย่าง
    if do_seed:
        print("🌱 Seeding sample data...")
        # การ import จะรันโค้ดใน fleet/seed.py อัตโนมัติ (ไฟล์ seed ปัจจุบันทำงานแบบ top-level)
        import importlib
        importlib.import_module("fleet.seed")
        print("✅ Seeded.")

    print("✅ Reset complete.")

if __name__ == "__main__":
    main()
