import os
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DB_PATH = os.getenv("CRM_DB_PATH", "fortivex_crm.db")
engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class CallRecord(Base):
    __tablename__ = "call_records"

    id = Column(Integer, primary_key=True, index=True)
    room_name = Column(String(120), unique=True, index=True, nullable=False)
    lead_name = Column(String(120), default="Unknown Prospect")
    lead_email = Column(String(160), default="")
    current_role = Column(String(120), default="")
    target_course = Column(String(160), default="")
    timeline = Column(String(80), default="")
    budget_comfort = Column(String(80), default="")
    lead_score = Column(Integer, default=0)
    lead_tier = Column(String(20), default="Unqualified")
    sentiment = Column(String(30), default="Neutral")
    booking_status = Column(String(40), default="Not Booked")
    booking_time = Column(String(80), default="")
    booking_uid = Column(String(120), default="")
    active_provider = Column(String(80), default="OpenAI")
    failover_events = Column(Integer, default=0)
    summary = Column(Text, default="")
    next_action = Column(String(240), default="")
    transcript_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

def init_db() -> None:
    Base.metadata.create_all(bind=engine)
