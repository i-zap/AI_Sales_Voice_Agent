import json
import os
import secrets
from pathlib import Path
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from livekit import api as lk_api
from sqlalchemy.orm import Session

from web.database import CallRecord, SessionLocal, init_db
from web.schemas import CRMSyncPayload, TokenRequest

load_dotenv()
init_db()

STATIC_DIR = Path(__file__).parent / "static"
CRM_SECRET = os.getenv("CRM_INTERNAL_SECRET", "fortivex-demo-secret-2026")

app = FastAPI(title="Fortivex AI — AI Academy Voice Sales & CRM")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/health")
def health():
    return {"status": "ok", "service": "fortivex-voice-crm"}

@app.get("/")
def serve_console():
    index_file = STATIC_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse({"status": "Backend ready — UI arrives in Step 4."})
    return FileResponse(index_file)

@app.get("/dashboard")
def serve_dashboard():
    dash_file = STATIC_DIR / "dashboard.html"
    if not dash_file.exists():
        return JSONResponse({"status": "CRM API ready — Dashboard UI arrives in Step 4."})
    return FileResponse(dash_file)

@app.post("/api/token")
def create_livekit_token(req: TokenRequest):
    lk_url = os.getenv("LIVEKIT_URL", "")
    api_key = os.getenv("LIVEKIT_API_KEY", "")
    api_secret = os.getenv("LIVEKIT_API_SECRET", "")
    if not (lk_url and api_key and api_secret):
        raise HTTPException(status_code=500, detail="LiveKit credentials missing in environment.")

    room_name = f"empowers-{secrets.token_hex(4)}"
    identity = f"lead-{secrets.token_hex(3)}"

    token = (
        lk_api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(req.participant_name.strip() or "Prospect")
        .with_grants(
            lk_api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )
        )
        .to_jwt()
    )
    return {
        "token": token,
        "url": lk_url,
        "room_name": room_name,
        "identity": identity,
    }

@app.post("/api/crm/sync")
def sync_crm_record(
    payload: CRMSyncPayload,
    x_internal_secret: str = Header(default=""),
    db: Session = Depends(get_db),
):
    if x_internal_secret != CRM_SECRET:
        raise HTTPException(status_code=401, detail="Invalid CRM internal secret.")

    record = db.query(CallRecord).filter(CallRecord.room_name == payload.room_name).first()
    if not record:
        record = CallRecord(room_name=payload.room_name)
        db.add(record)

    for field, value in payload.model_dump().items():
        setattr(record, field, value)

    db.commit()
    db.refresh(record)
    return {"ok": True, "id": record.id, "room_name": record.room_name}

@app.get("/api/crm/leads")
def list_crm_leads(db: Session = Depends(get_db)):
    rows = db.query(CallRecord).order_by(CallRecord.updated_at.desc()).limit(50).all()
    items = []
    for r in rows:
        try:
            transcript = json.loads(r.transcript_json or "[]")
        except json.JSONDecodeError:
            transcript = []
        items.append(
            {
                "id": r.id,
                "room_name": r.room_name,
                "lead_name": r.lead_name,
                "lead_email": r.lead_email,
                "current_role": r.current_role,
                "target_course": r.target_course,
                "timeline": r.timeline,
                "budget_comfort": r.budget_comfort,
                "lead_score": r.lead_score,
                "lead_tier": r.lead_tier,
                "sentiment": r.sentiment,
                "booking_status": r.booking_status,
                "booking_time": r.booking_time,
                "booking_uid": r.booking_uid,
                "active_provider": r.active_provider,
                "failover_events": r.failover_events,
                "summary": r.summary,
                "next_action": r.next_action,
                "transcript": transcript,
                "updated_at": r.updated_at.isoformat() if r.updated_at else "",
            }
        )
    return {"leads": items}

@app.get("/api/crm/stats")
def crm_stats(db: Session = Depends(get_db)):
    rows = db.query(CallRecord).all()
    total = len(rows)
    hot = sum(1 for r in rows if r.lead_tier == "Hot")
    booked = sum(1 for r in rows if r.booking_status == "Confirmed")
    avg_score = round(sum(r.lead_score for r in rows) / total, 1) if total else 0
    failovers = sum(r.failover_events for r in rows)
    return {
        "total_calls": total,
        "hot_leads": hot,
        "booked_meetings": booked,
        "avg_lead_score": avg_score,
        "failover_recoveries": failovers,
    }
