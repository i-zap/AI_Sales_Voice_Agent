import asyncio
import json
import logging
import os
import re
from typing import Any
import httpx

from agent.services.crm_client import sync_state_to_crm
from agent.state import CallState

logger = logging.getLogger("fortivex.observer")

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
NAME_RE = re.compile(
    r"(?:my name is|i am|i'm|this is)\s+([A-Z][a-z]{1,20}(?:\s+[A-Z][a-z]{1,20})?)",
    re.IGNORECASE,
)
ROLE_PATTERNS = [
    (r"\b(final[- ]year|college student|student|undergrad|b\.?tech|cs engineer|computer science)\b", "CS/IT Student"),
    (r"\b(fresher|recent graduate|graduate)\b", "Fresher / Graduate"),
    (r"\b(software engineer|developer|swe|backend|frontend|full[- ]stack|sde)\b", "Software Engineer"),
    (r"\b(devops|cloud engineer|sre|sysadmin)\b", "Cloud / DevOps Engineer"),
    (r"\b(working professional|career switcher|switching career|data analyst|qa|tester)\b", "Working Professional"),
]
COURSE_PATTERNS = [
    (r"\b(voice\s*ai|voice\s*agent|fellowship|autonomous\s*ai)\b", "Autonomous AI & Voice Agents Engineering Fellowship"),
    (r"\b(cloud|devops|kubernetes|aws|azure)\b", "Cloud Engineering, Kubernetes & DevOps Accelerator"),
    (r"\b(full[- ]stack|gen\s*ai|generative\s*ai|agentic)\b", "Full-Stack Generative AI & Agentic Systems Cohort"),
]
TIMELINE_RE = re.compile(
    r"\b(immediately|right now|asap|this week|next week|this month|next month|next batch|next cohort|soon|within \d+ (?:days?|weeks?|months?)|in \d+ months?)\b",
    re.IGNORECASE,
)
BUDGET_RE = re.compile(
    r"\b((?:comfortable|okay|ok|fine|good|open) with (?:monthly )?emi|monthly emi|no[- ]cost emi|installments?|upfront|pay in full|scholarship|can afford|budget is fine)\b",
    re.IGNORECASE,
)

EXTRACT_SYSTEM = (
    "Extract EdTech sales lead qualification fields from the transcript. "
    "Return ONLY valid JSON with these exact keys (use empty string \"\" if not mentioned): "
    '"lead_name", "lead_email", "current_role", "target_course", "timeline", "budget_comfort", '
    '"sentiment" (one of: Positive, Neutral, Hesitant, Negative). '
    "Map target_course to one of Empowers Academy's tracks when clear: "
    "'Autonomous AI & Voice Agents Engineering Fellowship', "
    "'Cloud Engineering, Kubernetes & DevOps Accelerator', or "
    "'Full-Stack Generative AI & Agentic Systems Cohort'. "
    "Do NOT guess facts not stated by the prospect."
)


def heuristic_extract(text: str) -> dict[str, str]:
    """Deterministic sub-millisecond extraction so UI updates immediately on every user turn."""
    extracted: dict[str, str] = {}
    cleaned = (text or "").strip()
    if not cleaned:
        return extracted

    email_m = EMAIL_RE.search(cleaned)
    if email_m:
        extracted["lead_email"] = email_m.group(0)

    name_m = NAME_RE.search(cleaned)
    if name_m:
        candidate = name_m.group(1).strip()
        stop_words = {"a", "an", "the", "looking", "interested", "comfortable", "fine", "ready", "working", "final"}
        if candidate.split()[0].lower() not in stop_words:
            extracted["lead_name"] = candidate.title()

    lower = cleaned.lower()
    for pat, label in ROLE_PATTERNS:
        if re.search(pat, lower):
            extracted["current_role"] = label
            break

    for pat, label in COURSE_PATTERNS:
        if re.search(pat, lower):
            extracted["target_course"] = label
            break

    tl_m = TIMELINE_RE.search(cleaned)
    if tl_m:
        extracted["timeline"] = tl_m.group(0)

    bg_m = BUDGET_RE.search(cleaned)
    if bg_m:
        extracted["budget_comfort"] = bg_m.group(0)

    if any(w in lower for w in ("awesome", "sounds solid", "great", "perfect", "book", "confirm", "love it", "excited")):
        extracted["sentiment"] = "Positive"
    elif any(w in lower for w in ("expensive", "not sure", "hesitant", "worried", "doubt", "too much")):
        extracted["sentiment"] = "Hesitant"

    return extracted


async def llm_extract_fields(state: CallState) -> dict[str, Any]:
    """Async structured JSON extractor with OpenAI -> Groq failover."""
    user_turns = [t for t in state.transcript if t.get("role") == "user"]
    if not user_turns:
        return {}

    convo = "\n".join(f"{t['agent']}: {t['text']}" for t in state.transcript[-14:])
    providers = []
    if not state.openai_killed and os.getenv("OPENAI_API_KEY"):
        providers.append(("https://api.openai.com/v1/chat/completions", os.getenv("OPENAI_API_KEY", ""), "gpt-4.1-mini"))
    if os.getenv("GROQ_API_KEY"):
        providers.append(("https://api.groq.com/openai/v1/chat/completions", os.getenv("GROQ_API_KEY", ""), "openai/gpt-oss-20b"))

    for url, key, model in providers:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {key}"},
                    json={
                        "model": model,
                        "temperature": 0.0,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": EXTRACT_SYSTEM},
                            {"role": "user", "content": f"Conversation:\n{convo}"},
                        ],
                    },
                )
                resp.raise_for_status()
                raw = resp.json()["choices"][0]["message"]["content"]
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
        except Exception as exc:
            logger.debug("Observer LLM extract (%s) skipped: %s", model, exc)
    return {}


class LeadScoringObserver:
    """Non-blocking background observer that keeps Lead Score & CRM synced on every user turn."""

    def __init__(self, state: CallState) -> None:
        self.state = state
        self._lock = asyncio.Lock()
        self._pending = False
        self._task: asyncio.Task | None = None

    def on_user_turn(self, text: str) -> None:
        # 1. Instant deterministic pass
        fast_fields = heuristic_extract(text)
        if fast_fields:
            changed = self.state.merge_extracted_fields(fast_fields)
            if changed:
                self.state.schedule_telemetry(
                    "score_updated",
                    f"Lead score updated: {self.state.lead_score}/100 ({self.state.lead_tier})",
                )

        # 2. Schedule async LLM refinement pass (coalesced)
        self._pending = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._drain_loop())

    async def _drain_loop(self) -> None:
        async with self._lock:
            while self._pending:
                self._pending = False
                fields = await llm_extract_fields(self.state)
                if fields:
                    changed = self.state.merge_extracted_fields(fields)
                    if changed:
                        await self.state.publish_telemetry(
                            "score_updated",
                            f"Lead score updated: {self.state.lead_score}/100 ({self.state.lead_tier})",
                        )
                        await sync_state_to_crm(self.state)

    async def flush(self) -> None:
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=6.0)
            except Exception:
                pass
