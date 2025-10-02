# fleet/seed.py
from datetime import datetime
from fleet.db import SessionLocal, init_db, engine
from fleet.models import Car, User, UsageLog

# บังคับสร้างตารางก่อนเสมอ (เผื่อ DB ใหม่/ว่าง)
init_db()
print("Using DB:", engine.url)

with SessionLocal() as s:
    if not s.query(Car).first():
        s.add_all([
            Car(plate="กข1234", brand="Toyota", model="Vios", year=2019, status="available"),
            Car(plate="ขค5678", brand="Isuzu", model="D-Max", year=2021, status="available"),
        ])
    if not s.query(User).first():
        u1 = User(full_name="Alice")
        u2 = User(full_name="Bob")
        s.add_all([u1, u2])
        s.flush()
        s.add(UsageLog(
            car_id=1, borrower_id=1,
            start_time=datetime.fromisoformat("2025-09-28T09:00:00"),
            end_time=datetime.fromisoformat("2025-09-28T17:30:00"),
            purpose="ออกภาคสนาม",
        ))
    s.commit()
print("✅ Seeded sample data.")
