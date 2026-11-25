import asyncio
import os
from datetime import datetime, timedelta, timezone
import httpx
from dotenv import load_dotenv
from livekit import api as lk_api

load_dotenv()

async def check_openai(client: httpx.AsyncClient) -> str:
    r = await client.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY', '')}"},
        json={
            "model": "gpt-4.1-mini",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        },
    )
    return "OK" if r.status_code == 200 else f"FAIL ({r.status_code}: {r.text[:120]})"

async def check_groq_llm(client: httpx.AsyncClient) -> str:
    r = await client.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '')}"},
        json={
            "model": "openai/gpt-oss-20b",
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 5,
        },
    )
    return "OK" if r.status_code == 200 else f"FAIL ({r.status_code}: {r.text[:120]})"

async def check_calcom(client: httpx.AsyncClient) -> str:
    now = datetime.now(timezone.utc)
    start = now.strftime("%Y-%m-%d")
    end = (now + timedelta(days=5)).strftime("%Y-%m-%d")
    r = await client.get(
        "https://api.cal.com/v2/slots",
        headers={
            "Authorization": f"Bearer {os.getenv('CAL_API_KEY', '')}",
            "cal-api-version": "2024-09-04",
        },
        params={
            "eventTypeId": os.getenv("CAL_EVENT_TYPE_ID", ""),
            "start": start,
            "end": end,
            "timeZone": "Asia/Kolkata",
        },
    )
    if r.status_code == 200:
        data = r.json().get("data", {})
        slot_count = sum(len(v) for v in data.values()) if isinstance(data, dict) else 0
        return f"OK ({slot_count} open slots found in next 5 days)"
    return f"FAIL ({r.status_code}: {r.text[:140]})"

async def check_livekit() -> str:
    try:
        lk = lk_api.LiveKitAPI(
            url=os.getenv("LIVEKIT_URL", ""),
            api_key=os.getenv("LIVEKIT_API_KEY", ""),
            api_secret=os.getenv("LIVEKIT_API_SECRET", ""),
        )
        res = await lk.room.list_rooms(lk_api.ListRoomsRequest())
        await lk.aclose()
        return f"OK (connected, {len(res.rooms)} active rooms)"
    except Exception as exc:
        return f"FAIL ({exc})"

async def main():
    async with httpx.AsyncClient(timeout=15.0) as client:
        results = await asyncio.gather(
            check_livekit(),
            check_openai(client),
            check_groq_llm(client),
            check_calcom(client),
        )
    names = [
        "LiveKit Cloud",
        "OpenAI (gpt-4.1-mini)",
        "Groq (openai/gpt-oss-20b)",
        "Cal.com v2 Slots",
    ]
    print("\n=== FORTIVEX PRE-FLIGHT KEY CHECK ===")
    for name, res in zip(names, results):
        print(f"  {name:<28} -> {res}")
    print("=====================================\n")

if __name__ == "__main__":
    asyncio.run(main())
