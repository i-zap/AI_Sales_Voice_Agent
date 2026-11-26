import json
import logging
import os
import httpx

from agent.services.lead_observer import heuristic_extract
from agent.state import CallState

logger = logging.getLogger("fortivex.summarizer")

SUMMARY_SYSTEM = (
    "You are a Fortivex AI Revenue Operations analyst for AI Academy (EdTech). "
    "Given a sales call transcript and lead profile, return ONLY valid JSON with keys: "
    '"summary" (2 concise sentences covering learner goal, objections, and outcome), '
    '"next_action" (1 concrete sales follow-up action), '
    '"sentiment" (one of: Positive, Neutral, Hesitant, Negative), '
    '"lead_name", "lead_email", "current_role", "target_course", "timeline", "budget_comfort" '
    '(fill any mentioned in the transcript, or "" if absent).'
)


async def _call_chat_json(url: str, api_key: str, model: str, user_prompt: str) -> dict:
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": model,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": SUMMARY_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return json.loads(content)


async def generate_call_summary(state: CallState) -> None:
    if not state.transcript:
        state.summary = "Call connected with no completed dialogue turns."
        state.next_action = "Send automated AI Academy brochure follow-up."
        state.compute_lead_score()
        return

    # Deterministic backfill across all user turns before LLM call
    full_user_text = " ".join(t["text"] for t in state.transcript if t.get("role") == "user")
    state.merge_extracted_fields(heuristic_extract(full_user_text))

    transcript_text = "\n".join(
        f"[{t['ts']}] {t['agent']}: {t['text']}" for t in state.transcript[-30:]
    )
    user_prompt = (
        f"Lead: {state.lead_name} ({state.lead_email or 'no email'})\n"
        f"Role: {state.current_role or 'unspecified'} | Target Course: {state.target_course or 'unspecified'}\n"
        f"Timeline: {state.timeline or 'unspecified'} | Budget: {state.budget_comfort or 'unspecified'}\n"
        f"Lead Score: {state.lead_score}/100 ({state.lead_tier}) | Booking: {state.booking_status} {state.booking_time}\n"
        f"Transcript:\n{transcript_text}"
    )

    providers = []
    if not state.openai_killed and os.getenv("OPENAI_API_KEY"):
        providers.append(("https://api.openai.com/v1/chat/completions", os.getenv("OPENAI_API_KEY", ""), "gpt-4.1-mini"))
    if os.getenv("GROQ_API_KEY"):
        providers.append(("https://api.groq.com/openai/v1/chat/completions", os.getenv("GROQ_API_KEY", ""), "openai/gpt-oss-20b"))

    for url, key, model in providers:
        try:
            data = await _call_chat_json(url, key, model, user_prompt)
            state.merge_extracted_fields(data)
            state.summary = data.get("summary", state.summary)
            state.next_action = data.get("next_action", state.next_action)
            return
        except Exception as exc:
            logger.warning("Summary provider %s failed: %s", model, exc)

    state.compute_lead_score()
    state.summary = (
        f"Spoke with {state.lead_name} regarding {state.target_course or 'AI Academy programs'}. "
        f"Lead tier: {state.lead_tier} ({state.lead_score}/100); booking status: {state.booking_status}."
    )
    state.next_action = (
        "Host scheduled counseling call."
        if state.booking_status == "Confirmed"
        else "Follow up with curriculum syllabus and EMI details."
    )
