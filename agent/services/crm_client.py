import logging
import os
import httpx

from agent.state import CallState

logger = logging.getLogger("fortivex.crm")


async def sync_state_to_crm(state: CallState) -> bool:
    base_url = os.getenv("CRM_API_URL", "http://127.0.0.1:8000").rstrip("/")
    secret = os.getenv("CRM_INTERNAL_SECRET", "fortivex-demo-secret-2026")
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{base_url}/api/crm/sync",
                headers={"X-Internal-Secret": secret},
                json=state.to_crm_payload(),
            )
            if resp.status_code == 200:
                return True
            logger.warning("CRM sync returned %s: %s", resp.status_code, resp.text[:120])
            return False
    except Exception as exc:
        logger.warning("CRM sync skipped (server unreachable): %s", exc)
        return False
