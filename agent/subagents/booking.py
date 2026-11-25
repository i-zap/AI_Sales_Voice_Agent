import logging
from datetime import datetime
from livekit.agents import Agent, RunContext, function_tool

from agent.prompts import BOOKING_PROMPT
from agent.services.calcom import CalComClient
from agent.services.crm_client import sync_state_to_crm
from agent.state import CallState

logger = logging.getLogger("fortivex.booking")
_calcom = CalComClient()


def _format_human_slot(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%a %b %d at %I:%M %p %Z").strip()
    except Exception:
        return iso_str


class BookingAgent(Agent):
    def __init__(self, chat_ctx=None) -> None:
        super().__init__(instructions=BOOKING_PROMPT, chat_ctx=chat_ctx)

    async def on_enter(self) -> None:
        state: CallState = self.session.userdata
        state.active_agent = "Booking & CRM"
        await state.publish_telemetry("agent_handoff", "Switched to Cal.com Booking & CRM Sub-Agent")
        self.session.generate_reply(
            instructions="Check available Cal.com slots immediately and help the prospect book their 15-minute counseling call."
        )

    @function_tool
    async def check_calcom_slots(
        self,
        context: RunContext[CallState],
        time_zone: str = "Asia/Kolkata",
    ) -> str:
        """Fetch real open 15-minute counseling slots from Cal.com v2."""
        try:
            slots = await _calcom.get_available_slots(days_ahead=4, time_zone=time_zone, max_slots=5)
        except Exception as exc:
            logger.error("Cal.com slots error: %s", exc)
            return "Unable to reach Cal.com right now. Ask the user for their preferred day and email so our counselor can send an invite."

        if not slots:
            return "No open slots found in the next 4 days. Ask for their preferred time and email."

        formatted = [f"- {s} ({_format_human_slot(s)})" for s in slots[:4]]
        await context.userdata.publish_telemetry("calcom_slots", f"Fetched {len(slots)} live Cal.com slots")
        return "Available Cal.com slots (use exact ISO string when booking):\n" + "\n".join(formatted)

    @function_tool
    async def book_calcom_appointment(
        self,
        context: RunContext[CallState],
        start_iso: str,
        attendee_name: str,
        attendee_email: str,
        time_zone: str = "Asia/Kolkata",
    ) -> str:
        """Book a live Cal.com counseling slot AFTER verifying attendee name, email, and chosen slot."""
        state = context.userdata
        state.lead_name = attendee_name.strip()
        state.lead_email = attendee_email.strip()

        notes = (
            f"Empowers Academy Lead | Track: {state.target_course or 'General'} | "
            f"Score: {state.lead_score}/100 ({state.lead_tier}) | Sentiment: {state.sentiment}"
        )
        result = await _calcom.create_booking(
            start_iso=start_iso,
            attendee_name=state.lead_name,
            attendee_email=state.lead_email,
            time_zone=time_zone,
            notes=notes,
        )
        if result.get("ok"):
            state.booking_status = "Confirmed"
            state.booking_time = _format_human_slot(result.get("start", start_iso))
            state.booking_uid = result.get("booking_uid", "")
            state.sentiment = "Positive"
            state.compute_lead_score()
            await sync_state_to_crm(state)
            await state.publish_telemetry("booking_confirmed", f"Cal.com booking confirmed: {state.booking_time}")
            return (
                f"Booking confirmed! Slot: {state.booking_time}. "
                f"Confirmation invite sent to {state.lead_email} (Booking ID: {state.booking_uid})."
            )

        logger.warning("Cal.com booking failed: %s", result.get("error"))
        return f"Booking failed: {result.get('error')}. Apologize briefly and ask to double-check the email or try another slot."

    @function_tool
    async def return_to_orchestrator(
        self,
        context: RunContext[CallState],
        handoff_note: str,
    ):
        """Hand control back to the Main Orchestrator after booking completes or if caller has other questions."""
        from agent.subagents.orchestrator import OrchestratorAgent

        context.userdata.last_handoff_note = handoff_note
        return OrchestratorAgent(chat_ctx=self.chat_ctx)
