import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from livekit import rtc

logger = logging.getLogger("fortivex.state")


@dataclass
class CallState:
    room_name: str
    room: rtc.Room | None = None

    # Lead & EdTech BANT Qualification
    lead_name: str = "Unknown Prospect"
    lead_email: str = ""
    current_role: str = ""
    target_course: str = ""
    timeline: str = ""
    budget_comfort: str = ""
    lead_score: int = 0
    lead_tier: str = "Unqualified"

    # Conversational Intelligence
    sentiment: str = "Neutral"
    active_agent: str = "Orchestrator"
    last_handoff_note: str = ""
    rag_hits: list[str] = field(default_factory=list)

    # Cal.com Live Booking
    booking_status: str = "Not Booked"
    booking_time: str = ""
    booking_uid: str = ""

    # Circuit Breaker Telemetry (OpenAI <-> Groq)
    openai_killed: bool = False
    circuit_status: str = "CLOSED"
    active_llm: str = "OpenAI gpt-4.1-mini"
    active_stt: str = "OpenAI gpt-4o-mini-transcribe"
    active_tts: str = "OpenAI gpt-4o-mini-tts"
    failover_events: int = 0

    # Transcript & Post-Call Summary
    transcript: list[dict[str, str]] = field(default_factory=list)
    summary: str = ""
    next_action: str = ""

    def active_provider_label(self) -> str:
        return "Groq (Failover)" if ("Groq" in self.active_llm or self.openai_killed) else "OpenAI (Primary)"

    def compute_lead_score(self) -> tuple[int, str]:
        score = 10  # Baseline inbound interest

        if self.lead_name and self.lead_name.strip().lower() not in ("unknown prospect", "prospect", "unknown", ""):
            score += 5
        if self.lead_email and "@" in self.lead_email:
            score += 10
        if self.current_role.strip():
            score += 15
        if self.target_course.strip():
            score += 20

        tl = self.timeline.lower().strip()
        urgent_tl = (
            "now", "immediate", "this month", "next month", "week", "soon", "asap",
            "next batch", "next cohort", "upcoming", "right away", "monday", "this year",
            "ready", "today", "tomorrow", "quarter", "1 month", "2 month",
        )
        if any(k in tl for k in urgent_tl):
            score += 20
        elif tl:
            score += 10

        bg = self.budget_comfort.lower().strip()
        positive_bg = (
            "emi", "installment", "monthly", "ready", "fine", "yes", "comfortable",
            "affordable", "okay", "ok", "upfront", "no issue", "no problem", "can pay",
            "scholarship", "works", "good with", "manageable", "budget",
        )
        if any(k in bg for k in positive_bg):
            score += 20
        elif bg:
            score += 10

        if self.sentiment == "Positive":
            score += 5

        if self.booking_status == "Confirmed":
            score = max(score + 25, 80)

        score = min(score, 100)
        if score >= 70:
            tier = "Hot"
        elif score >= 40:
            tier = "Warm"
        else:
            tier = "Cold"

        self.lead_score = score
        self.lead_tier = tier
        return score, tier

    def merge_extracted_fields(self, fields: dict[str, Any]) -> bool:
        """Merge non-empty extracted lead fields and recompute score; returns True if state changed."""
        before = (
            self.lead_name,
            self.lead_email,
            self.current_role,
            self.target_course,
            self.timeline,
            self.budget_comfort,
            self.sentiment,
            self.lead_score,
            self.lead_tier,
        )

        name = str(fields.get("lead_name") or "").strip()
        if name and name.lower() not in ("unknown", "unknown prospect", "prospect", "n/a", "none"):
            self.lead_name = name

        email = str(fields.get("lead_email") or "").strip()
        if email and "@" in email:
            self.lead_email = email

        for attr in ("current_role", "target_course", "timeline", "budget_comfort"):
            val = str(fields.get(attr) or "").strip()
            if val and val.lower() not in ("unknown", "n/a", "none", "unspecified"):
                setattr(self, attr, val)

        sent = str(fields.get("sentiment") or "").strip().capitalize()
        if sent in ("Positive", "Neutral", "Hesitant", "Negative"):
            self.sentiment = sent

        self.compute_lead_score()

        after = (
            self.lead_name,
            self.lead_email,
            self.current_role,
            self.target_course,
            self.timeline,
            self.budget_comfort,
            self.sentiment,
            self.lead_score,
            self.lead_tier,
        )
        return after != before

    def append_turn(self, role: str, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        self.transcript.append(
            {
                "role": role,
                "agent": self.active_agent if role == "assistant" else "Lead",
                "text": cleaned,
                "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            }
        )

    def to_crm_payload(self) -> dict[str, Any]:
        return {
            "room_name": self.room_name,
            "lead_name": self.lead_name,
            "lead_email": self.lead_email,
            "current_role": self.current_role,
            "target_course": self.target_course,
            "timeline": self.timeline,
            "budget_comfort": self.budget_comfort,
            "lead_score": self.lead_score,
            "lead_tier": self.lead_tier,
            "sentiment": self.sentiment,
            "booking_status": self.booking_status,
            "booking_time": self.booking_time,
            "booking_uid": self.booking_uid,
            "active_provider": self.active_provider_label(),
            "failover_events": self.failover_events,
            "summary": self.summary,
            "next_action": self.next_action,
            "transcript_json": json.dumps(self.transcript),
        }

    def to_telemetry_dict(self, event_type: str = "state_update", note: str = "") -> dict[str, Any]:
        return {
            "type": event_type,
            "note": note,
            "room_name": self.room_name,
            "active_agent": self.active_agent,
            "lead_name": self.lead_name,
            "lead_email": self.lead_email,
            "current_role": self.current_role,
            "target_course": self.target_course,
            "timeline": self.timeline,
            "budget_comfort": self.budget_comfort,
            "lead_score": self.lead_score,
            "lead_tier": self.lead_tier,
            "sentiment": self.sentiment,
            "booking_status": self.booking_status,
            "booking_time": self.booking_time,
            "openai_killed": self.openai_killed,
            "circuit_status": self.circuit_status,
            "active_llm": self.active_llm,
            "active_stt": self.active_stt,
            "active_tts": self.active_tts,
            "failover_events": self.failover_events,
            "rag_hits": self.rag_hits[-4:],
            "last_turn": self.transcript[-1] if self.transcript else None,
        }

    async def publish_telemetry(self, event_type: str = "state_update", note: str = "") -> None:
        if not self.room or not self.room.local_participant:
            return
        try:
            payload = json.dumps(self.to_telemetry_dict(event_type, note)).encode("utf-8")
            await self.room.local_participant.publish_data(
                payload,
                reliable=True,
                topic="fortivex_telemetry",
            )
        except Exception as exc:
            logger.debug("Telemetry publish skipped: %s", exc)

    def schedule_telemetry(self, event_type: str = "state_update", note: str = "") -> None:
        try:
            asyncio.get_running_loop().create_task(self.publish_telemetry(event_type, note))
        except RuntimeError:
            pass
