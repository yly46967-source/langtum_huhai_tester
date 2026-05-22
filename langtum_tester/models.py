"""Pydantic models for API requests/responses."""
from pydantic import BaseModel


class FileStartRequest(BaseModel):
    concurrency: int = 20


class FileSummary(BaseModel):
    id: int
    upload_name: str
    folder_name: str
    ship_key: str
    ship_name: str | None
    ship_type: str | None
    company: str | None
    total_items: int
    parse_status: str
    status: str
    success: int = 0
    failed: int = 0
    running: int = 0
    pending: int = 0


class TaskDetail(BaseModel):
    id: int
    item_index: int
    manufacturer: str
    model: str
    source_name: str
    equip_code: str | None
    status: str
    error_message: str | None
    started_at: str | None
    raw_output: str | None
