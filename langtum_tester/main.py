"""FastAPI application — Langtum workflow tester."""
import asyncio
import io
import json
import logging
import os
import sys
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from config import STATIC_DIR, RESULT_DIR, UPLOAD_DIR
from db import (
    init_db, conn_ctx, list_files, get_file, get_file_by_key,
    get_tasks_by_file, get_file_progress, insert_file, insert_task,
    delete_file as db_delete_file,
)
from parser import parse_uploaded_file, load_equipment_excel
from models import FileStartRequest, FileSummary, TaskDetail
from runner import start_file, abort_file, run_single_task, abort_single, retry_task
from excel import generate_file_excel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_sse_queues: list[asyncio.Queue] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    os.makedirs(RESULT_DIR, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    yield


app = FastAPI(title="Langtum 工作流测试系统", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


async def notify_sse(file_id: int, task_id: int, status: str):
    with conn_ctx() as conn:
        progress = get_file_progress(conn, file_id)
    msg = json.dumps({
        "type": "task_update",
        "file_id": file_id,
        "task_id": task_id,
        "status": status,
        "progress": progress,
    }, ensure_ascii=False)
    dead = []
    for i, q in enumerate(_sse_queues):
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(i)
    for i in reversed(dead):
        _sse_queues.pop(i)


@app.get("/", response_class=HTMLResponse)
async def index():
    return Path(os.path.join(STATIC_DIR, "index.html")).read_text(encoding="utf-8")


# --- Upload ---

@app.post("/api/files/upload")
async def api_upload(files: list[UploadFile] = File(...)):
    excel_data = load_equipment_excel()
    results = []

    for upload in files:
        if not upload.filename.endswith(".txt"):
            continue
        content = (await upload.read()).decode("utf-8")
        ship_key = upload.filename.replace("\\", "/").rsplit("/", 1)[-1].replace("_设备信息数组.txt", "").replace(".txt", "")

        # Extract folder name from webkitRelativePath (folder upload) or empty (file upload)
        rel_path = getattr(upload, '_webkit_relative_path', None) or ""
        # FastAPI/Starlette may store it differently
        if not rel_path and hasattr(upload, 'headers'):
            cd = upload.headers.get("content-disposition", "")
            # Try to extract from filename that may contain path
        folder_name = ""
        if "/" in rel_path:
            folder_name = rel_path.rsplit("/", 1)[0]
        elif "\\" in rel_path:
            folder_name = rel_path.rsplit("\\", 1)[0]

        with conn_ctx() as conn:
            existing = get_file_by_key(conn, ship_key)
            if existing:
                results.append({"file_id": existing["id"], "ship_key": ship_key,
                                "total_items": existing["total_items"], "skipped": True})
                continue

        try:
            ship_data = parse_uploaded_file(content, upload.filename, excel_data)
            parse_status = "success"
            parse_error = None
        except Exception as e:
            ship_data = {"ship_key": ship_key, "ship_name": ship_key, "ship_type": "",
                         "company": "", "items": []}
            parse_status = "failed"
            parse_error = str(e)

        with conn_ctx() as conn:
            file_id = insert_file(
                conn, upload.filename, ship_data["ship_key"],
                ship_data["ship_name"], ship_data["ship_type"],
                ship_data["company"], len(ship_data["items"]),
                file_content=content, folder_name=folder_name,
                parse_status=parse_status, parse_error=parse_error,
            )
            for i, item in enumerate(ship_data["items"]):
                insert_task(
                    conn, file_id, i,
                    item["manufacturer"], item["model"], item["source_name"],
                    item.get("equip_code", ""), item.get("equip_group", ""),
                )
        results.append({"file_id": file_id, "ship_key": ship_data["ship_key"],
                        "total_items": len(ship_data["items"]), "skipped": False})

    return {"uploaded": results}


# --- Files ---

@app.get("/api/files")
async def api_list_files():
    with conn_ctx() as conn:
        files = list_files(conn)
        result = []
        for f in files:
            progress = get_file_progress(conn, f["id"])
            result.append(FileSummary(
                id=f["id"], upload_name=f["upload_name"],
                folder_name=f.get("folder_name", ""),
                ship_key=f["ship_key"], ship_name=f.get("ship_name"),
                ship_type=f.get("ship_type"), company=f.get("company"),
                total_items=f["total_items"], parse_status=f.get("parse_status", "success"),
                status=f["status"],
                success=progress["success"], failed=progress["failed"],
                running=progress["running"], pending=progress["pending"],
            ))
    return result


@app.get("/api/files/{file_id}/tasks")
async def api_file_tasks(file_id: int):
    with conn_ctx() as conn:
        tasks = get_tasks_by_file(conn, file_id)
    return [TaskDetail(
        id=t["id"], item_index=t["item_index"], manufacturer=t["manufacturer"],
        model=t["model"], source_name=t["source_name"],
        equip_code=t.get("equip_code"), status=t["status"],
        error_message=t.get("error_message"),
        started_at=t.get("started_at"),
        raw_output=t.get("raw_output"),
    ) for t in tasks]


@app.post("/api/files/{file_id}/start")
async def api_file_start(file_id: int, req: FileStartRequest):
    await start_file(file_id, req.concurrency, notify=notify_sse)
    return {"status": "started"}


@app.post("/api/files/{file_id}/abort")
async def api_file_abort(file_id: int):
    await abort_file(file_id)
    return {"status": "aborted"}


@app.delete("/api/files/{file_id}")
async def api_file_delete(file_id: int):
    with conn_ctx() as conn:
        f = get_file(conn, file_id)
        ship_key = f["ship_key"]
        db_delete_file(conn, file_id)
    # Remove Excel if exists
    safe_key = ship_key.replace("/", "_").replace("\\", "_")
    excel_path = os.path.join(RESULT_DIR, f"{safe_key}_结果.xlsx")
    if os.path.exists(excel_path):
        os.remove(excel_path)
    return {"status": "deleted"}


@app.get("/api/files/{file_id}/download")
async def api_file_download(file_id: int):
    # Always regenerate to ensure latest results
    path = generate_file_excel(file_id)
    if not path or not os.path.exists(path):
        return {"error": "No successful results to generate"}
    return FileResponse(path, filename=os.path.basename(path))


@app.get("/api/files/download-all")
async def api_download_all():
    buf = io.BytesIO()
    count = 0
    with conn_ctx() as conn:
        files = list_files(conn)
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            with conn_ctx() as conn:
                progress = get_file_progress(conn, f["id"])
            if progress["success"] > 0:
                try:
                    path = generate_file_excel(f["id"])
                    if os.path.exists(path):
                        zf.write(path, f"{f['ship_key']}_结果.xlsx")
                        count += 1
                except Exception as e:
                    logger.error(f"download-all: failed for {f['ship_key']}: {e}")

    if count == 0:
        return {"error": "No results to download"}

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=all_results.zip"},
    )


# --- Tasks ---

@app.post("/api/tasks/{task_id}/start")
async def api_task_start(task_id: int):
    asyncio.create_task(run_single_task(task_id, notify=notify_sse))
    return {"status": "started"}


@app.post("/api/tasks/{task_id}/abort")
async def api_task_abort(task_id: int):
    await abort_single(task_id)
    return {"status": "aborted"}


@app.post("/api/tasks/{task_id}/retry")
async def api_task_retry(task_id: int):
    asyncio.create_task(retry_task(task_id, notify=notify_sse))
    return {"status": "retrying"}


# --- SSE ---

@app.get("/api/events")
async def api_events(request: Request):
    async def event_generator():
        q = asyncio.Queue(maxsize=100)
        _sse_queues.append(q)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=30)
                    yield {"data": data}
                except asyncio.TimeoutError:
                    yield {"event": "ping", "data": ""}
        finally:
            if q in _sse_queues:
                _sse_queues.remove(q)

    from sse_starlette.sse import EventSourceResponse
    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn
    from config import HOST, PORT
    uvicorn.run(app, host=HOST, port=PORT)
