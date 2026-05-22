"""Async Langtum workflow API client."""
import httpx
import json
import asyncio
from config import LANGTUM_BASE_URL, LANGTUM_API_KEY, LANGTUM_WORKFLOW_ID, POLL_INTERVALS


async def create_task(client: httpx.AsyncClient, equipment: dict,
                      ship_type: str = "", language: str = "") -> str:
    """Create a workflow task with one equipment item. Returns taskId."""
    payload = {
        "workflowEntityId": LANGTUM_WORKFLOW_ID,
        "input": {
            "equipment_list": [equipment],
            "ship_type": ship_type,
            "language": language,
        }
    }
    resp = await client.post(
        f"{LANGTUM_BASE_URL}/api/v1/workflow/createTask",
        headers={"Authorization": f"Bearer {LANGTUM_API_KEY}"},
        json=payload,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise RuntimeError(f"createTask failed: {data}")
    return data["data"]["taskId"]


async def poll_task(client: httpx.AsyncClient, task_id: str) -> dict:
    """Poll queryTask until SUCCEED/FAILED. No timeout — polls indefinitely."""
    url = f"{LANGTUM_BASE_URL}/api/v1/workflow/queryTask/{task_id}"
    headers = {"Authorization": f"Bearer {LANGTUM_API_KEY}"}

    delay = 5
    while True:
        await asyncio.sleep(delay)
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()["data"]
            if data["status"] in ("SUCCEED", "FAILED"):
                return data
            delay = min(delay + 2, 15)  # ramp up to 15s, keep polling forever
        except httpx.HTTPError:
            continue  # retry on network errors


async def abort_task(client: httpx.AsyncClient, task_id: str) -> bool:
    """Abort a running workflow task. Returns True if aborted, False if already done."""
    try:
        resp = await client.post(
            f"{LANGTUM_BASE_URL}/api/v1/workflow/abort",
            headers={"Authorization": f"Bearer {LANGTUM_API_KEY}"},
            json={"taskId": task_id},
        )
        return resp.status_code == 200
    except Exception:
        return False
