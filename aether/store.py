import json
import os
import sqlite3
import fcntl
from contextlib import contextmanager
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
        self._migrate_coding_proposals()

    @contextmanager
    def coding_apply_lock(self, blocking: bool = True):
        """Coordinate coding apply and startup recovery across local OS processes.

        The lock is released by the OS if a process exits or crashes. This lock
        is intentionally local-filesystem/POSIX scoped, matching the local Mac
        deployment; do not place the database on a network filesystem.
        """
        lock_path = self.db_path.with_name(self.db_path.name + ".coding-apply.lock")
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            flags = fcntl.LOCK_EX
            if not blocking:
                flags |= fcntl.LOCK_NB
            try:
                fcntl.flock(fd, flags)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path, timeout=10)
        con.row_factory = sqlite3.Row
        # SQLite's built-in lower() is ASCII-only unless built with ICU.
        # Register Python casefold so cross-session search handles Unicode
        # consistently with the ranking logic below.
        con.create_function(
            "aether_casefold",
            1,
            lambda value: value.casefold() if isinstance(value, str) else "",
            deterministic=True,
        )
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
            CREATE TABLE IF NOT EXISTS coding_proposals (
              id TEXT PRIMARY KEY, summary TEXT NOT NULL, changes_json TEXT NOT NULL,
              status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','applied')),
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error_text TEXT
            );
            CREATE TABLE IF NOT EXISTS memories (
              id TEXT PRIMARY KEY, category TEXT NOT NULL, content TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT 'user', tags_json TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY, title TEXT NOT NULL,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_messages (
              id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
              role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
              content TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_session_messages_session_created
              ON session_messages(session_id, created_at);
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

    def claim_task(self, task_id: str) -> bool:
        """Atomically transition a queued task to running; only one caller can claim it."""
        with self.connect() as con:
            cursor = con.execute(
                "UPDATE tasks SET status='running',updated_at=?,result_json=NULL,error_text=NULL "
                "WHERE id=? AND status='queued'",
                (utc_now(), task_id),
            )
            if cursor.rowcount == 1:
                return True
            row = con.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                raise KeyError("Task not found")
            return False

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

    def mark_interrupted_proposals_for_review(self) -> int:
        """Flag proposals left applying by a prior process for manual reconciliation.

        File replacement and SQLite status persistence cannot be one atomic
        transaction. Never reset these proposals to approved automatically.
        """
        now = utc_now()
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE coding_proposals
                SET updated_at=?,
                    error_text=COALESCE(
                        error_text,
                        'Process restarted while applying. Inspect workspace files and proposal changes before any manual recovery.'
                    )
                WHERE status='applying'
                """,
                (now,),
            )
        return cursor.rowcount

    def mark_interrupted_as_unknown(self) -> int:
        now = utc_now()
        with self.connect() as con:
            tools = con.execute("UPDATE tool_executions SET status='unknown',updated_at=?,error_text=COALESCE(error_text,?) WHERE status='running'",
                                (now, "Process restarted during execution; verify effects before retrying"))
            tasks = con.execute("UPDATE tasks SET status='unknown',updated_at=?,error_text=COALESCE(error_text,?) WHERE status='running'",
                                (now, "Process restarted during task; verify effects before retrying"))
        return tools.rowcount + tasks.rowcount


    def create_proposal(self, summary: str, changes: list[dict[str, Any]]) -> dict[str, Any]:
        proposal_id, now = str(uuid4()), utc_now()
        with self.connect() as con:
            con.execute(
                "INSERT INTO coding_proposals(id,summary,changes_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (proposal_id, summary, json.dumps(changes, ensure_ascii=False), "pending", now, now),
            )
        return self.get_proposal(proposal_id)  # type: ignore[return-value]

    def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM coding_proposals WHERE id=?", (proposal_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["changes"] = json.loads(result.pop("changes_json"))
        return result

    def list_proposals(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute("SELECT id FROM coding_proposals ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [proposal for row in rows if (proposal := self.get_proposal(row["id"])) is not None]

    def _migrate_coding_proposals(self) -> None:
        """Add the applying state while preserving all existing proposals."""
        con = self.connect()
        try:
            row = con.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='coding_proposals'"
            ).fetchone()
            if row is None:
                return

            schema = row["sql"] or ""
            if "'applying'" in schema:
                return

            con.execute("BEGIN IMMEDIATE")
            con.execute("""
                CREATE TABLE coding_proposals_new (
                    id TEXT PRIMARY KEY,
                    summary TEXT NOT NULL,
                    changes_json TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(
                        status IN ('pending','approved','applying','rejected','applied')
                    ),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error_text TEXT
                )
            """)
            con.execute("""
                INSERT INTO coding_proposals_new
                    (id, summary, changes_json, status, created_at, updated_at, error_text)
                SELECT id, summary, changes_json, status, created_at, updated_at, error_text
                FROM coding_proposals
            """)
            con.execute("DROP TABLE coding_proposals")
            con.execute("ALTER TABLE coding_proposals_new RENAME TO coding_proposals")
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def claim_proposal_for_apply(self, proposal_id: str) -> bool:
        """Atomically claim an approved proposal; only one caller can win."""
        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE coding_proposals
                SET status='applying', updated_at=?, error_text=NULL
                WHERE id=? AND status='approved'
                """,
                (utc_now(), proposal_id),
            )
            if cursor.rowcount == 1:
                return True

            row = con.execute(
                "SELECT id FROM coding_proposals WHERE id=?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise KeyError("Proposal not found")
            return False

    def set_proposal_status(self, proposal_id: str, status: str, error: str | None = None) -> None:
        if status not in {"pending", "approved", "applying", "rejected", "applied"}:
            raise ValueError("Invalid coding proposal status")

        with self.connect() as con:
            cursor = con.execute(
                """
                UPDATE coding_proposals
                SET status=?, updated_at=?, error_text=?
                WHERE id=? AND (
                    (status='pending' AND ? IN ('approved', 'rejected'))
                    OR (status='applying' AND ?='applied')
                    OR (status='applying' AND ?='approved' AND ? IS NOT NULL)
                    OR (status='applying' AND ?='applying' AND ? IS NOT NULL)
                    OR (status='approved' AND ?='approved' AND ? IS NOT NULL)
                )
                """,
                (
                    status, utc_now(), error, proposal_id,
                    status, status, status, error, status, error, status, error,
                ),
            )
            if cursor.rowcount == 0:
                row = con.execute(
                    "SELECT status FROM coding_proposals WHERE id=?",
                    (proposal_id,),
                ).fetchone()
                if row is None:
                    raise KeyError("Proposal not found")
                raise ValueError(
                    f"Invalid proposal status transition: {row['status']} -> {status}"
                )

    def add_memory(self, category: str, content: str, source: str = "user",
                   tags: list[str] | None = None) -> dict[str, Any]:
        memory_id, now = str(uuid4()), utc_now()
        with self.connect() as con:
            con.execute(
                "INSERT INTO memories(id,category,content,source,tags_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                (memory_id, category.strip(), content.strip(), source.strip() or "user",
                 json.dumps(tags or [], ensure_ascii=False), now, now),
            )
        return self.get_memory(memory_id)  # type: ignore[return-value]

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["tags"] = json.loads(result.pop("tags_json"))
        return result

    def list_memories(self, limit: int = 100, category: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as con:
            if category:
                rows = con.execute(
                    "SELECT id FROM memories WHERE category=? ORDER BY updated_at DESC LIMIT ?",
                    (category, limit),
                ).fetchall()
            else:
                rows = con.execute("SELECT id FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [item for row in rows if (item := self.get_memory(row["id"])) is not None]

    def search_memories(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        import re

        stop_words = {
            "what", "which", "did", "do", "does", "i", "you", "my", "me",
            "the", "a", "an", "is", "was", "were", "to", "of", "for",
            "in", "on", "that", "this", "please", "ask", "asked",
        }
        terms = [
            term.casefold()
            for term in re.findall(r"[\w-]+", query, flags=re.UNICODE)
            if term.casefold() not in stop_words
        ]
        if limit <= 0:
            return []
        candidates = self.list_memories(limit=500)
        recall_intent = bool(
            re.search(r"\b(remember|recall|memorized|saved)\b", query, re.IGNORECASE)
            and re.search(r"\b(what|which|code|thing|information|detail)\b", query, re.IGNORECASE)
        )
        ranked = []
        for item in candidates:
            haystack = (
                item["category"] + " " + item["content"] + " " + " ".join(item["tags"])
            ).casefold()
            score = sum(1 for term in terms if term in haystack)
            # Natural-language recall questions may not contain the saved value.
            # Give explicit user-requested memories a modest boost for those queries.
            if recall_intent and item.get("source") == "explicit_chat_request":
                score += 3
            if score:
                ranked.append((score, item["updated_at"], item))
        ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return [item for _, _, item in ranked[:limit]]

    def delete_memory(self, memory_id: str) -> bool:
        with self.connect() as con:
            cursor = con.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        return cursor.rowcount > 0


    def create_session(self, title: str = "New conversation") -> dict[str, Any]:
        session_id, now = str(uuid4()), utc_now()
        with self.connect() as con:
            con.execute("INSERT INTO sessions(id,title,created_at,updated_at) VALUES(?,?,?,?)",
                        (session_id, title.strip()[:120] or "New conversation", now, now))
        return self.get_session(session_id)  # type: ignore[return-value]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM session_messages m WHERE m.session_id=s.id) AS message_count "
                "FROM sessions s ORDER BY s.updated_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def add_session_message(self, session_id: str, role: str, content: str) -> dict[str, Any]:
        if role not in {"user", "assistant", "system"}:
            raise ValueError("Invalid message role")
        message_id, now = str(uuid4()), utc_now()
        with self.connect() as con:
            exists = con.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not exists:
                raise KeyError("Session not found")
            con.execute("INSERT INTO session_messages(id,session_id,role,content,created_at) VALUES(?,?,?,?,?)",
                        (message_id, session_id, role, content, now))
            con.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
            if role == "user":
                first_user = con.execute(
                    "SELECT content FROM session_messages WHERE session_id=? AND role='user' ORDER BY created_at LIMIT 1",
                    (session_id,),
                ).fetchone()
                if first_user:
                    title = first_user["content"].strip().replace("\\n", " ")[:80] or "New conversation"
                    con.execute("UPDATE sessions SET title=? WHERE id=? AND title='New conversation'",
                                (title, session_id))
        with self.connect() as con:
            row = con.execute("SELECT * FROM session_messages WHERE id=?", (message_id,)).fetchone()
        return dict(row)


    def add_session_turn(self, session_id: str, user_content: str, assistant_content: str) -> list[dict[str, Any]]:
        """Persist a successful user/assistant turn atomically."""
        user_id, assistant_id = str(uuid4()), str(uuid4())
        user_created_at, assistant_created_at = utc_now(), utc_now()
        with self.connect() as con:
            exists = con.execute("SELECT 1 FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not exists:
                raise KeyError("Session not found")
            con.execute(
                "INSERT INTO session_messages(id,session_id,role,content,created_at) VALUES(?,?,?,?,?)",
                (user_id, session_id, "user", user_content, user_created_at),
            )
            con.execute(
                "INSERT INTO session_messages(id,session_id,role,content,created_at) VALUES(?,?,?,?,?)",
                (assistant_id, session_id, "assistant", assistant_content, assistant_created_at),
            )
            title = user_content.strip().replace("\\n", " ")[:80] or "New conversation"
            con.execute(
                "UPDATE sessions SET updated_at=?, title=CASE WHEN title='New conversation' THEN ? ELSE title END WHERE id=?",
                (assistant_created_at, title, session_id),
            )
            rows = con.execute(
                "SELECT * FROM session_messages WHERE id IN (?, ?) "
                "ORDER BY CASE id WHEN ? THEN 0 ELSE 1 END",
                (user_id, assistant_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_session_messages(self, session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        # Use the declared primary key rather than SQLite rowid; the table may be
        # backed by a WITHOUT ROWID schema in an existing local database.
        with self.connect() as con:
            rows = con.execute(
                "SELECT * FROM (SELECT * FROM session_messages WHERE session_id=? "
                "ORDER BY created_at DESC, id DESC LIMIT ?) ORDER BY created_at, id",
                (session_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def search_session_messages(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        """Search message text across conversations, ranked by matching query terms."""
        if limit <= 0:
            return []
        terms = list(dict.fromkeys(term.casefold() for term in query.split() if term.strip()))
        if not terms:
            return []
        conditions = " OR ".join("instr(aether_casefold(m.content), aether_casefold(?)) > 0" for _ in terms)
        with self.connect() as con:
            rows = con.execute(
                "SELECT m.id, m.session_id, s.title AS session_title, m.role, "
                "m.content, m.created_at FROM session_messages AS m "
                "JOIN sessions AS s ON s.id=m.session_id WHERE " + conditions,
                terms,
            ).fetchall()
        ranked = []
        for row in rows:
            item = dict(row)
            haystack = item["content"].casefold()
            score = sum(1 for term in terms if term in haystack)
            if score:
                ranked.append((score, item["created_at"], item))
        ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        return [item for _, _, item in ranked[:limit]]

    def delete_session(self, session_id: str) -> bool:
        with self.connect() as con:
            cursor = con.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        return cursor.rowcount > 0
