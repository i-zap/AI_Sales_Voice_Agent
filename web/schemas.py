from pydantic import BaseModel, Field

class TokenRequest(BaseModel):
    participant_name: str = Field(default="Prospect", max_length=60)

class CRMSyncPayload(BaseModel):
    room_name: str
    lead_name: str = "Unknown Prospect"
    lead_email: str = ""
    current_role: str = ""
    target_course: str = ""
    timeline: str = ""
    budget_comfort: str = ""
    lead_score: int = 0
    lead_tier: str = "Unqualified"
    sentiment: str = "Neutral"
    booking_status: str = "Not Booked"
    booking_time: str = ""
    booking_uid: str = ""
    active_provider: str = "OpenAI"
    failover_events: int = 0
    summary: str = ""
    next_action: str = ""
    transcript_json: str = "[]"
