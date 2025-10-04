# fleet/models.py
from __future__ import annotations
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime,
    ForeignKey, CheckConstraint, Text, Boolean
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
import os

# --- DB engine / Session ---
DB_PATH = os.getenv("DB_PATH", "fleet.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL, echo=False, future=True,
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()

# --- Models (define ONCE only) ---
class Car(Base):
    __tablename__ = "cars"

    id = Column(Integer, primary_key=True, index=True)
    plate = Column(String, nullable=False, unique=True)
    brand = Column(String)
    model = Column(String)
    year = Column(Integer)
    status = Column(String)  # available / in_use

    def __repr__(self) -> str:
        return f"<Car {self.plate} ({self.brand} {self.model})>"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, nullable=False)

    def __repr__(self) -> str:
        return f"<User {self.full_name}>"


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    car_id = Column(Integer, ForeignKey("cars.id"))
    borrower_id = Column(Integer, ForeignKey("users.id"))
    start_time = Column(DateTime)      # เวลาเริ่มใช้จริง
    

    planned_end_time = Column(DateTime, nullable=True)
    is_maintenance   = Column(Boolean, default=False)
    returned_at      = Column(DateTime, nullable=True)   # เวลาคืนจริง (ตอนกดคืนรถ)
    purpose = Column(String)
    returned_at = Column(DateTime, nullable=True)  # เวลาคืนจริง

    car = relationship("Car")
    borrower = relationship("User")

    def __repr__(self) -> str:
        return f"<UsageLog id={self.id} car={self.car_id} borrower={self.borrower_id}>"

# --- create tables if not exists ---
def init_db():
    Base.metadata.create_all(bind=engine)

if __name__ == "__main__":
    init_db()
    print("✅ Database checked/created")
