import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

STATUSES = {"queued", "running", "succeeded", "failed", "unknown"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStore:
    """Durable task journal; never blindly replay work with uncertain outcomes."""
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=10000")
        return con

    def _init_db(self) -> None:
        with self.connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, input_text TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','unknown')),
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, result_json TEXT, error_text TEXT
            );
            CREATE TABLE IF NOT EXISTS tool_executions (
              id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id), tool_name TEXT NOT NULL,
              input_json TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','unknown')),
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, result_json TEXT, error_text TEXT
            );
            """)

    def create_task(self, title: str, input_text: str) -> dict[str, Any]:
        now, task_id = utc_now(), str(uuid4())
        with self.connect() as con:
            con.execute("INSERT INTO tasks(id,title,input_text,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (task_id, title, input_text, "queued", now, now))
        return self.get_task(task_id)  # type: ignore[return-value]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def set_task_status(self, task_id: str, status: str, result: Any = None, error: str | None = None) -> None:
        if status not in STATUSES:
            raise ValueError("Invalid task status")
        with self.connect() as con:
            con.execute("UPDATE tasks SET status=?,updated_at=?,result_json=?,error_text=? WHERE id=?",
                        (status, utc_now(), json.dumps(result, ensure_ascii=False) if result is not None else None, error, task_id))

    def begin_tool(self, task_id: str, tool_name: str, tool_input: dict[str, Any]) -> str:
        execution_id, now = str(uuid4()), utc_now()
        with self.connect() as con:
            con.execute("INSERT INTO tool_executions(id,task_id,tool_name,input_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                        (execution_id, task_id, tool_name, json.dumps(tool_input, ensure_ascii=False), "running", now, now))
        return execution_id

    def finish_tool(self, execution_id: str, status: str, result: Any = None, error: str | None = None) -> None:
        if status not in {"succeeded", "failed", "unknown"}:
            raise ValueError("Invalid final tool status")
        with self.connect() as con:
            con.execute("UPDATE tool_executions SET status=?,updated_at=?,result_json=?,error_text=? WHERE id=?",
                        (status, utc_now(), json.dumps(result, ensure_ascii=False) if result is not None else None, error, execution_id))

    def list_tool_executions(self, task_id: str) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("SELECT * FROM tool_executions WHERE task_id=? ORDER BY created_at", (task_id,)).fetchall()
        return [dict(row) for row in rows]

    def mark_interrupted_as_unknown(self) -> int:
        now = utc_now()
        with self.connect() as con:
            tools = con.execute("UPDATE tool_executions SET status='unknown',updated_at=?,error_text=COALESCE(error_text,?) WHERE status='running'",
                                (now, "Process restarted during execution; verify effects before retrying"))
            tasks = con.execute("UPDATE tasks SET status='unknown',updated_at=?,error_text=COALESCE(error_text,?) WHERE status='running'",
                                (now, "Process restarted during task; verify effects before retrying"))
        return tools.rowcount + tasks.rowcount
