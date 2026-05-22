"""SQLite database setup and CRUD operations."""
import sqlite3
from contextlib import contextmanager
from config import DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def conn_ctx():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with conn_ctx() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                upload_name TEXT NOT NULL,
                folder_name TEXT NOT NULL DEFAULT '',
                ship_key TEXT NOT NULL,
                ship_name TEXT,
                ship_type TEXT,
                company TEXT,
                total_items INTEGER NOT NULL DEFAULT 0,
                file_content TEXT NOT NULL DEFAULT '',
                parse_status TEXT NOT NULL DEFAULT 'success',
                parse_error TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT DEFAULT (datetime('now','localtime')),
                completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
                item_index INTEGER NOT NULL,
                manufacturer TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                source_name TEXT NOT NULL DEFAULT '',
                equip_code TEXT DEFAULT '',
                equip_group TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                wf_task_id TEXT,
                raw_output TEXT,
                error_message TEXT,
                started_at TEXT,
                completed_at TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                UNIQUE(file_id, item_index)
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_file_status ON tasks(file_id, status);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_files_ship_key ON files(ship_key);
        """)

        # Migrate: add folder_name column if missing
        cols = [r[1] for r in conn.execute("PRAGMA table_info(files)").fetchall()]
        if "folder_name" not in cols:
            conn.execute("ALTER TABLE files ADD COLUMN folder_name TEXT NOT NULL DEFAULT ''")


# --- File CRUD ---

def insert_file(conn, upload_name: str, ship_key: str, ship_name: str,
                ship_type: str, company: str, total_items: int,
                file_content: str, folder_name: str = '',
                parse_status: str = 'success', parse_error: str = None) -> int:
    conn.execute("""INSERT OR REPLACE INTO files
        (upload_name, folder_name, ship_key, ship_name, ship_type, company, total_items,
         file_content, parse_status, parse_error, status)
        VALUES (?,?,?,?,?,?,?,?,?,?,'pending')""",
        (upload_name, folder_name, ship_key, ship_name, ship_type, company, total_items,
         file_content, parse_status, parse_error))
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def get_file(conn, file_id: int) -> dict:
    return dict(conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone())


def get_file_by_key(conn, ship_key: str) -> dict | None:
    row = conn.execute("SELECT * FROM files WHERE ship_key=?", (ship_key,)).fetchone()
    return dict(row) if row else None


def list_files(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM files ORDER BY folder_name, id").fetchall()]


def delete_file(conn, file_id: int):
    conn.execute("DELETE FROM tasks WHERE file_id=?", (file_id,))
    conn.execute("DELETE FROM files WHERE id=?", (file_id,))


def update_file_status(conn, file_id: int, status: str):
    if status == "completed":
        conn.execute("UPDATE files SET status=?, completed_at=datetime('now','localtime') WHERE id=?",
                     (status, file_id))
    else:
        conn.execute("UPDATE files SET status=? WHERE id=?", (status, file_id))


def get_file_progress(conn, file_id: int) -> dict:
    row = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) as success,
            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
            SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) as running,
            SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending
        FROM tasks WHERE file_id=?
    """, (file_id,)).fetchone()
    return dict(row)


# --- Task CRUD ---

def insert_task(conn, file_id: int, item_index: int, manufacturer: str,
                model: str, source_name: str, equip_code: str = '',
                equip_group: str = ''):
    conn.execute("""INSERT OR IGNORE INTO tasks
        (file_id, item_index, manufacturer, model, source_name, equip_code, equip_group, status)
        VALUES (?,?,?,?,?,?,?,'pending')""",
        (file_id, item_index, manufacturer, model, source_name, equip_code, equip_group))


def get_task(conn, task_id: int) -> dict:
    return dict(conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())


def get_tasks_by_file(conn, file_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE file_id=? ORDER BY item_index", (file_id,)).fetchall()]


def get_pending_tasks(conn, file_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE file_id=? AND status='pending'", (file_id,)).fetchall()]


def get_running_tasks(conn, file_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE file_id=? AND status='running'", (file_id,)).fetchall()]


def get_success_tasks(conn, file_id: int) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM tasks WHERE file_id=? AND status='success' ORDER BY item_index", (file_id,)).fetchall()]


def update_task_status(conn, task_id: int, status: str,
                       wf_task_id: str = None, raw_output: str = None,
                       error_message: str = None):
    if status == "running":
        conn.execute("UPDATE tasks SET status=?, started_at=datetime('now','localtime') WHERE id=?",
                     (status, task_id))
    elif status in ("success", "failed"):
        conn.execute("""UPDATE tasks SET status=?, wf_task_id=COALESCE(?,wf_task_id),
                        raw_output=COALESCE(?,raw_output), error_message=?,
                        completed_at=datetime('now','localtime') WHERE id=?""",
                     (status, wf_task_id, raw_output, error_message, task_id))
    else:
        conn.execute("UPDATE tasks SET status=? WHERE id=?", (status, task_id))


def reset_task(conn, task_id: int):
    """Reset a task to pending, clearing previous results for retry."""
    conn.execute("""UPDATE tasks SET status='pending', wf_task_id=NULL,
                    raw_output=NULL, error_message=NULL,
                    started_at=NULL, completed_at=NULL WHERE id=?""", (task_id,))
