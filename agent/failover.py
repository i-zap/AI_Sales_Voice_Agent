import logging
from typing import Any

from livekit.agents import APIConnectionError, DEFAULT_API_CONNECT_OPTIONS, NOT_GIVEN, llm, stt, tts, vad as lk_vad
from livekit.plugins import groq, openai

from agent.state import CallState

logger = logging.getLogger("fortivex.failover")


class _ChaosFailedLLMStream(llm.LLMStream):
    async def _run(self) -> None:
        raise APIConnectionError("Simulated OpenAI LLM outage via Chaos Toggle")


class ChaosOpenAILLM(openai.LLM):
    def __init__(self, state: CallState, **kwargs: Any):
        super().__init__(**kwargs)
        self._state = state

    def chat(self, *, chat_ctx, tools=None, conn_options=DEFAULT_API_CONNECT_OPTIONS, **kwargs):
        if self._state.openai_killed:
            return _ChaosFailedLLMStream(
                self,
                chat_ctx=chat_ctx,
                tools=tools or [],
                conn_options=conn_options,
            )
        return super().chat(chat_ctx=chat_ctx, tools=tools, conn_options=conn_options, **kwargs)


class ChaosOpenAISTT(openai.STT):
    def __init__(self, state: CallState, **kwargs: Any):
        super().__init__(**kwargs)
        self._state = state

    async def _recognize_impl(self, buffer, *, language=NOT_GIVEN, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        if self._state.openai_killed:
            raise APIConnectionError("Simulated OpenAI STT outage via Chaos Toggle")
        return await super()._recognize_impl(buffer, language=language, conn_options=conn_options)


class _ChaosFailedTTSStream(tts.ChunkedStream):
    async def _run(self, *args: Any, **kwargs: Any) -> None:
        raise APIConnectionError("Simulated OpenAI TTS outage via Chaos Toggle")


class ChaosOpenAITTS(openai.TTS):
    def __init__(self, state: CallState, **kwargs: Any):
        super().__init__(**kwargs)
        self._state = state

    def synthesize(self, text: str, *, conn_options=DEFAULT_API_CONNECT_OPTIONS):
        if self._state.openai_killed:
            return _ChaosFailedTTSStream(tts=self, input_text=text, conn_options=conn_options)
        return super().synthesize(text, conn_options=conn_options)


def build_resilient_pipeline(
    state: CallState,
    vad: lk_vad.VAD,
) -> tuple[stt.FallbackAdapter, llm.FallbackAdapter, tts.FallbackAdapter]:
    """Build 2-Tier OpenAI -> Groq FallbackAdapters with circuit-breaker telemetry hooks."""
    primary_llm = ChaosOpenAILLM(state=state, model="gpt-4.1-mini", temperature=0.4)
    backup_llm = groq.LLM(model="openai/gpt-oss-20b", temperature=0.4)
    fallback_llm = llm.FallbackAdapter(
        llm=[primary_llm, backup_llm],
        attempt_timeout=10.0,
        max_retry_per_llm=0,
        retry_interval=3.0,
    )

    primary_stt = stt.StreamAdapter(
        stt=ChaosOpenAISTT(state=state, model="gpt-4o-mini-transcribe", language="en"),
        vad=vad,
    )
    backup_stt = stt.StreamAdapter(
        stt=groq.STT(model="whisper-large-v3-turbo", language="en"),
        vad=vad,
    )
    fallback_stt = stt.FallbackAdapter(
        stt=[primary_stt, backup_stt],
        attempt_timeout=10.0,
        max_retry_per_stt=0,
        retry_interval=3.0,
    )

    primary_tts = ChaosOpenAITTS(state=state, model="gpt-4o-mini-tts", voice="alloy")
    backup_tts = groq.TTS(model="canopylabs/orpheus-v1-english", voice="autumn")
    fallback_tts = tts.FallbackAdapter(
        tts=[primary_tts, backup_tts],
        max_retry_per_tts=0,
    )

    @fallback_llm.on("llm_availability_changed")
    def _on_llm_change(ev: Any) -> None:
        if ev.llm is primary_llm:
            if not ev.available:
                state.circuit_status = "OPEN (FAILOVER -> GROQ)"
                state.active_llm = "Groq openai/gpt-oss-20b"
                state.failover_events += 1
                logger.warning("Circuit OPEN: LLM failed over to Groq openai/gpt-oss-20b")
                state.schedule_telemetry("failover", "LLM circuit OPEN — switched to Groq openai/gpt-oss-20b")
            else:
                state.circuit_status = "CLOSED"
                state.active_llm = "OpenAI gpt-4.1-mini"
                logger.info("Circuit CLOSED: LLM recovered to OpenAI gpt-4.1-mini")
                state.schedule_telemetry("recovery", "LLM recovered to OpenAI gpt-4.1-mini")

    @fallback_stt.on("stt_availability_changed")
    def _on_stt_change(ev: Any) -> None:
        if ev.stt is primary_stt:
            state.active_stt = (
                "OpenAI gpt-4o-mini-transcribe" if ev.available else "Groq whisper-large-v3-turbo"
            )
            state.schedule_telemetry("stt_switch", f"Active STT: {state.active_stt}")

    @fallback_tts.on("tts_availability_changed")
    def _on_tts_change(ev: Any) -> None:
        if ev.tts is primary_tts:
            state.active_tts = (
                "OpenAI gpt-4o-mini-tts" if ev.available else "Groq orpheus-v1-english"
            )
            state.schedule_telemetry("tts_switch", f"Active TTS: {state.active_tts}")

    return fallback_stt, fallback_llm, fallback_tts
