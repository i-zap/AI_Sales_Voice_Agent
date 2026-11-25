import os
from datetime import datetime, timedelta, timezone
from typing import Any
import httpx

class CalComClient:
    BASE_URL = "https://api.cal.com/v2"

    def __init__(self):
        self.api_key = os.getenv("CAL_API_KEY", "")
        self.event_type_id = int(os.getenv("CAL_EVENT_TYPE_ID", "0"))

    def _headers(self, version: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "cal-api-version": version,
            "Content-Type": "application/json",
        }

    async def get_available_slots(
        self,
        days_ahead: int = 4,
        time_zone: str = "Asia/Kolkata",
        max_slots: int = 6,
    ) -> list[str]:
        """Fetch real open ISO slots for the configured Cal.com Event Type."""
        now = datetime.now(timezone.utc)
        start = now.strftime("%Y-%m-%d")
        end = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(
                f"{self.BASE_URL}/slots",
                headers=self._headers("2024-09-04"),
                params={
                    "eventTypeId": self.event_type_id,
                    "start": start,
                    "end": end,
                    "timeZone": time_zone,
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        raw_data = payload.get("data", {})
        if isinstance(raw_data, dict) and "slots" in raw_data:
            raw_data = raw_data["slots"]

        slots: list[str] = []
        if isinstance(raw_data, dict):
            for _day, entries in sorted(raw_data.items()):
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    ts = entry.get("start") or entry.get("time") if isinstance(entry, dict) else str(entry)
                    if ts:
                        slots.append(ts)
                    if len(slots) >= max_slots:
                        return slots
        return slots

    async def create_booking(
        self,
        start_iso: str,
        attendee_name: str,
        attendee_email: str,
        time_zone: str = "Asia/Kolkata",
        notes: str = "",
    ) -> dict[str, Any]:
        """Create a real Cal.com v2 appointment booking."""
        body: dict[str, Any] = {
            "start": start_iso,
            "eventTypeId": self.event_type_id,
            "attendee": {
                "name": attendee_name,
                "email": attendee_email,
                "timeZone": time_zone,
                "language": "en",
            },
        }
        if notes:
            body["bookingFieldsResponses"] = {"notes": notes}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self.BASE_URL}/bookings",
                headers=self._headers("2024-08-13"),
                json=body,
            )
            if resp.status_code not in (200, 201):
                return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
            data = resp.json().get("data", {})
            return {
                "ok": True,
                "booking_uid": data.get("uid", ""),
                "status": data.get("status", "accepted"),
                "start": data.get("start", start_iso),
                "meeting_url": data.get("meetingUrl", ""),
            }
