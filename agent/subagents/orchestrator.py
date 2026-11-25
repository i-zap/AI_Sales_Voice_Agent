import logging
from livekit.agents import Agent, RunContext, function_tool

from agent.prompts import ORCHESTRATOR_PROMPT
from agent.services.crm_client import sync_state_to_crm
from agent.services.summarizer import generate_call_summary
from agent.state import CallState
from agent.subagents.advisor import AdvisorAgent
from agent.subagents.booking import BookingAgent
from agent.subagents.qualifier import QualifierAgent

logger = logging.getLogger("fortivex.orchestrator")


class OrchestratorAgent(Agent):
    def __init__(self, chat_ctx=None) -> None:
        super().__init__(instructions=ORCHESTRATOR_PROMPT, chat_ctx=chat_ctx)

    async def on_enter(self) -> None:
        state: CallState = self.session.userdata
        state.active_agent = "Orchestrator"
        await state.publish_telemetry("agent_handoff", "Active: Main Orchestrator Agent")
        if state.last_handoff_note:
            note = state.last_handoff_note
            state.last_handoff_note = ""
            self.session.generate_reply(
                instructions=f"The specialist just finished with note: '{note}'. Smoothly guide the prospect to the next step."
            )

    @function_tool
    async def update_sentiment(
        self,
        context: RunContext[CallState],
        sentiment: str,
        reason: str = "",
    ) -> str:
        """Update real-time caller sentiment (Positive, Neutral, Hesitant, or Negative)."""
        if sentiment in ("Positive", "Neutral", "Hesitant", "Negative"):
            context.userdata.sentiment = sentiment
            await context.userdata.publish_telemetry("sentiment", f"Sentiment -> {sentiment} ({reason})")
        return f"Sentiment updated to {context.userdata.sentiment}."

    @function_tool
    async def transfer_to_qualifier(self, context: RunContext[CallState]):
        """Route to the Lead Qualifier Sub-Agent to capture background, target track, timeline, and budget."""
        return QualifierAgent(chat_ctx=self.chat_ctx)

    @function_tool
    async def transfer_to_advisor(self, context: RunContext[CallState]):
        """Route to the EdTech RAG Course Advisor for grounded Empowers Academy curriculum, fee, EMI, or placement answers."""
        return AdvisorAgent(chat_ctx=self.chat_ctx)

    @function_tool
    async def transfer_to_booking(self, context: RunContext[CallState]):
        """Route to the Booking & CRM Sub-Agent to check live Cal.com slots and book a counseling session."""
        return BookingAgent(chat_ctx=self.chat_ctx)

    @function_tool
    async def finalize_and_sync_crm(self, context: RunContext[CallState]) -> str:
        """Generate structured call summary and push the final record to Fortivex CRM."""
        state = context.userdata
        await generate_call_summary(state)
        await sync_state_to_crm(state)
        await state.publish_telemetry("crm_synced", "Call summary generated and synced to Fortivex CRM")
        return "Summary generated and synced to CRM. Deliver a warm 1-sentence closing."
