import logging
from livekit.agents import Agent, RunContext, function_tool

from agent.prompts import ADVISOR_PROMPT
from agent.rag.retriever import EdTechRAGRetriever
from agent.state import CallState

logger = logging.getLogger("fortivex.advisor")
_retriever = EdTechRAGRetriever()


class AdvisorAgent(Agent):
    def __init__(self, chat_ctx=None) -> None:
        super().__init__(instructions=ADVISOR_PROMPT, chat_ctx=chat_ctx)

    async def on_enter(self) -> None:
        state: CallState = self.session.userdata
        state.active_agent = "RAG Advisor"
        await state.publish_telemetry("agent_handoff", "Switched to EdTech RAG Course Advisor")
        self.session.generate_reply(
            instructions="Answer the prospect's course, fee, EMI, or placement question using search_empowers_catalog."
        )

    @function_tool
    async def search_empowers_catalog(
        self,
        context: RunContext[CallState],
        query: str,
    ) -> str:
        """Retrieve grounded Empowers Academy course curriculum, fees, EMI, placement, and refund facts."""
        hits = _retriever.search(query, top_k=2)
        state = context.userdata
        titles = [h["title"] for h in hits]
        state.rag_hits.extend(titles)

        if not state.target_course:
            for h in hits:
                if h["id"].startswith("course_"):
                    state.merge_extracted_fields({"target_course": h["title"]})
                    break

        await state.publish_telemetry("rag_lookup", f"RAG retrieved: {', '.join(titles)}")
        return "\n\n".join(f"[{h['title']}]: {h['content']}" for h in hits)

    @function_tool
    async def return_to_orchestrator(
        self,
        context: RunContext[CallState],
        handoff_note: str,
    ):
        """Hand control back to the Main Orchestrator after answering course questions or when lead is ready to book."""
        from agent.subagents.orchestrator import OrchestratorAgent

        context.userdata.last_handoff_note = handoff_note
        return OrchestratorAgent(chat_ctx=self.chat_ctx)
