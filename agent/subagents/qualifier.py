import logging
from livekit.agents import Agent, RunContext, function_tool

from agent.prompts import QUALIFIER_PROMPT
from agent.services.crm_client import sync_state_to_crm
from agent.state import CallState

logger = logging.getLogger("fortivex.qualifier")


class QualifierAgent(Agent):
    def __init__(self, chat_ctx=None) -> None:
        super().__init__(instructions=QUALIFIER_PROMPT, chat_ctx=chat_ctx)

    async def on_enter(self) -> None:
        state: CallState = self.session.userdata
        state.active_agent = "Qualifier"
        await state.publish_telemetry("agent_handoff", "Switched to Lead Qualifier Sub-Agent")
        self.session.generate_reply(
            instructions=(
                "FIRST check the conversation history: if the prospect already shared their name, role, target track, "
                "timeline, or EMI/budget comfort, IMMEDIATELY call record_lead_qualification with ALL known details "
                "before speaking. Then ask for any single missing detail or hand back to the orchestrator."
            )
        )

    @function_tool
    async def record_lead_qualification(
        self,
        context: RunContext[CallState],
        lead_name: str = "",
        current_role: str = "",
        target_course: str = "",
        timeline: str = "",
        budget_comfort: str = "",
        sentiment: str = "",
    ) -> str:
        """Save ALL known EdTech BANT lead qualification details and calculate lead score."""
        state = context.userdata
        state.merge_extracted_fields(
            {
                "lead_name": lead_name,
                "current_role": current_role,
                "target_course": target_course,
                "timeline": timeline,
                "budget_comfort": budget_comfort,
                "sentiment": sentiment,
            }
        )
        await sync_state_to_crm(state)
        await state.publish_telemetry(
            "qualification_saved",
            f"Lead scored {state.lead_score}/100 ({state.lead_tier})",
        )
        return f"Qualification recorded. Lead score is {state.lead_score}/100 ({state.lead_tier})."

    @function_tool
    async def return_to_orchestrator(
        self,
        context: RunContext[CallState],
        handoff_note: str,
    ):
        """Hand control back to the Main Orchestrator once qualification is captured or caller wants course/booking info."""
        from agent.subagents.orchestrator import OrchestratorAgent

        context.userdata.last_handoff_note = handoff_note
        return OrchestratorAgent(chat_ctx=self.chat_ctx)
