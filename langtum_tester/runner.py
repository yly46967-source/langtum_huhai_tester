"""Task execution engine — per-file and per-task granularity."""
import asyncio
import json
import logging
from typing import Callable
import httpx
from db import conn_ctx, get_pending_tasks, get_running_tasks, update_task_status, update_file_status, get_file_progress
from workflow import create_task, poll_task, abort_task

logger = logging.getLogger(__name__)

# Track running file tasks for cancellation
_running_file_tasks: dict[int, asyncio.Task] = {}


async def run_file_tasks(file_id: int, concurrency: int, notify: Callable = None):
    """Run all pending tasks for a file with given concurrency."""
    with conn_ctx() as conn:
        pending = get_pending_tasks(conn, file_id)

    if not pending:
        logger.info(f"File {file_id}: no pending tasks")
        return

    logger.info(f"File {file_id}: starting {len(pending)} tasks, concurrency={concurrency}")

    with conn_ctx() as conn:
        update_file_status(conn, file_id, "running")

    semaphore = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=120.0) as client:
        coros = [run_single(client, semaphore, task, notify) for task in pending]
        await asyncio.gather(*coros, return_exceptions=True)

    # Check if all tasks done
    with conn_ctx() as conn:
        progress = get_file_progress(conn, file_id)
        if progress["pending"] == 0 and progress["running"] == 0:
            update_file_status(conn, file_id, "completed")
            # Auto-generate Excel
            if progress["success"] > 0:
                try:
                    from excel import generate_file_excel
                    generate_file_excel(file_id)
                    logger.info(f"File {file_id}: auto-generated Excel")
                except Exception as e:
                    logger.error(f"File {file_id}: auto-generate Excel failed: {e}")

    # Cleanup
    _running_file_tasks.pop(file_id, None)
    logger.info(f"File {file_id}: finished")


async def start_file(file_id: int, concurrency: int, notify: Callable = None):
    """Start file tasks as a background asyncio.Task."""
    if file_id in _running_file_tasks:
        return  # Already running
    task = asyncio.create_task(run_file_tasks(file_id, concurrency, notify))
    _running_file_tasks[file_id] = task


async def abort_file(file_id: int):
    """Abort all running tasks for a file."""
    # Cancel the background task if exists
    bg_task = _running_file_tasks.get(file_id)
    if bg_task and not bg_task.done():
        bg_task.cancel()

    # Abort each running task on Langtum
    with conn_ctx() as conn:
        running = get_running_tasks(conn, file_id)

    async with httpx.AsyncClient(timeout=30.0) as client:
        for task in running:
            if task.get("wf_task_id"):
                await abort_task(client, task["wf_task_id"])
            with conn_ctx() as conn:
                update_task_status(conn, task["id"], "failed", error_message="用户中止")

    logger.info(f"File {file_id}: aborted {len(running)} running tasks")


async def run_single_task(task_id: int, notify: Callable = None):
    """Run a single task by ID."""
    with conn_ctx() as conn:
        from db import get_task
        task = get_task(conn, task_id)

    if task["status"] not in ("pending", "failed"):
        return

    semaphore = asyncio.Semaphore(1)
    async with httpx.AsyncClient(timeout=120.0) as client:
        await run_single(client, semaphore, task, notify)

    # Check file completion
    with conn_ctx() as conn:
        progress = get_file_progress(conn, task["file_id"])
        if progress["pending"] == 0 and progress["running"] == 0:
            update_file_status(conn, task["file_id"], "completed")


async def abort_single(task_id: int):
    """Abort a single running task."""
    with conn_ctx() as conn:
        from db import get_task
        task = get_task(conn, task_id)

    if task["status"] != "running" or not task.get("wf_task_id"):
        return

    async with httpx.AsyncClient(timeout=30.0) as client:
        await abort_task(client, task["wf_task_id"])

    with conn_ctx() as conn:
        update_task_status(conn, task_id, "failed", error_message="用户中止")


async def retry_task(task_id: int, notify: Callable = None):
    """Reset a task to pending and re-execute it."""
    with conn_ctx() as conn:
        from db import get_task, reset_task
        task = get_task(conn, task_id)
        reset_task(conn, task_id)
        task["status"] = "pending"

    semaphore = asyncio.Semaphore(1)
    async with httpx.AsyncClient(timeout=120.0) as client:
        await run_single(client, semaphore, task, notify)

    # Check file completion
    with conn_ctx() as conn:
        progress = get_file_progress(conn, task["file_id"])
        if progress["pending"] == 0 and progress["running"] == 0:
            update_file_status(conn, task["file_id"], "completed")


async def run_single(client: httpx.AsyncClient, sem: asyncio.Semaphore,
                     task: dict, notify: Callable = None):
    """Execute one workflow task: create -> poll -> save result."""
    async with sem:
        task_id = task["id"]
        file_id = task["file_id"]
        equipment = {
            "manufacturer": task["manufacturer"],
            "model": task["model"],
            "source_name": task["source_name"],
        }

        with conn_ctx() as conn:
            update_task_status(conn, task_id, "running")
            from db import get_file
            file_rec = get_file(conn, file_id)

        ship_type = file_rec.get("ship_type", "") if file_rec else ""

        final_status = "failed"
        try:
            wf_task_id = await create_task(client, equipment, ship_type=ship_type)

            with conn_ctx() as conn:
                conn.execute("UPDATE tasks SET wf_task_id=? WHERE id=?", (wf_task_id, task_id))

            result = await poll_task(client, wf_task_id)
            status = result["status"]
            raw_output = json.dumps(result.get("detail", {}), ensure_ascii=False)

            if status == "SUCCEED":
                final_status = "success"
                with conn_ctx() as conn:
                    update_task_status(conn, task_id, "success", raw_output=raw_output)
            else:
                error = result.get("detail", {}).get("output", {}).get("error", "FAILED")
                with conn_ctx() as conn:
                    update_task_status(conn, task_id, "failed", raw_output=raw_output,
                                       error_message=str(error)[:500])

        except Exception as e:
            logger.error(f"Task {task_id} error: {e}")
            with conn_ctx() as conn:
                update_task_status(conn, task_id, "failed", error_message=str(e)[:500])

        if notify:
            await notify(file_id, task_id, final_status)
