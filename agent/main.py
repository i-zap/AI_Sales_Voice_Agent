import json
import logging
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import AgentServer, AgentSession, JobContext, JobProcess, cli
from livekit.plugins import silero

from agent.failover import build_resilient_pipeline
from agent.services.crm_client import sync_state_to_crm
from agent.services.summarizer import generate_call_summary
from agent.state import CallState
from agent.subagents.orchestrator import OrchestratorAgent

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fortivex.worker")

server = AgentServer()


def prewarm(proc: JobProcess) -> None:
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session()
async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()
    room_name = ctx.room.name
    logger.info("Joined LiveKit room: %s", room_name)

    vad = ctx.proc.userdata["vad"]
    state = CallState(room_name=room_name, room=ctx.room)
    fallback_stt, fallback_llm, fallback_tts = build_resilient_pipeline(state, vad=vad)

    session = AgentSession[CallState](
        vad=vad,
        stt=fallback_stt,
        llm=fallback_llm,
        tts=fallback_tts,
        userdata=state,
    )

    @ctx.room.on("data_received")
    def _on_data_received(packet: rtc.DataPacket) -> None:
        if packet.topic != "fortivex_control":
            return
        try:
            cmd = json.loads(packet.data.decode("utf-8"))
        except Exception:
            return

        action = cmd.get("action")
        if action == "kill_openai":
            state.openai_killed = True
            state.circuit_status = "OPEN (SIMULATED OUTAGE)"
            state.active_llm = "Groq openai/gpt-oss-20b"
            state.active_stt = "Groq whisper-large-v3-turbo"
            state.active_tts = "Groq orpheus-v1-english"
            state.failover_events += 1
            logger.warning("CHAOS TOGGLE: OpenAI killed — routing next turn to Groq")
            state.schedule_telemetry("chaos_engaged", "OpenAI killed — Groq failover active on next turn")
        elif action == "restore_openai":
            state.openai_killed = False
            state.circuit_status = "HALF_OPEN -> CLOSED"
            state.active_llm = "OpenAI gpt-4.1-mini"
            state.active_stt = "OpenAI gpt-4o-mini-transcribe"
            state.active_tts = "OpenAI gpt-4o-mini-tts"
            logger.info("CHAOS TOGGLE: OpenAI restored to Primary")
            state.schedule_telemetry("chaos_restored", "OpenAI restored — recovering to Primary")

    @session.on("conversation_item_added")
    def _on_item_added(ev) -> None:
        item = getattr(ev, "item", None)
        if not item:
            return
        role = getattr(item, "role", "")
        text = getattr(item, "text_content", "") or ""
        if role in ("user", "assistant") and text.strip():
            state.append_turn(role, text)
            state.schedule_telemetry("transcript", "")

    async def _on_shutdown() -> None:
        logger.info("Finalizing CRM summary for room %s...", room_name)
        await generate_call_summary(state)
        await sync_state_to_crm(state)

    ctx.add_shutdown_callback(_on_shutdown)

    await session.start(
        agent=OrchestratorAgent(),
        room=ctx.room,
    )

    await state.publish_telemetry("connected", "Voice agent joined room — OpenAI Primary active")
    await session.generate_reply(
        instructions=(
            "Greet the prospect warmly on behalf of Empowers Academy by Fortivex AI, "
            "briefly note this AI-assisted call may be recorded for quality, and ask what tech career goal or course they are exploring today."
        )
    )


if __name__ == "__main__":
    cli.run_app(server)
