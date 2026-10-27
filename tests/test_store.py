from pathlib import Path
from aether.store import TaskStore


def test_task_and_tool_execution_persist(tmp_path: Path):
    store = TaskStore(tmp_path / "test.sqlite3")
    task = store.create_task("test", "do a test")
    assert task["status"] == "queued"
    store.set_task_status(task["id"], "running")
    execution_id = store.begin_tool(task["id"], "workspace.list_files", {"path": "."})
    store.finish_tool(execution_id, "succeeded", result={"entries": []})
    store.set_task_status(task["id"], "succeeded", result={"ok": True})
    reopened = TaskStore(tmp_path / "test.sqlite3")
    assert reopened.get_task(task["id"])["status"] == "succeeded"
    records = reopened.list_tool_executions(task["id"])
    assert records[0]["status"] == "succeeded"
    assert '"entries": []' in records[0]["result_json"]


def test_running_work_is_marked_unknown_after_restart(tmp_path: Path):
    store = TaskStore(tmp_path / "test.sqlite3")
    task = store.create_task("crash test", "simulate restart")
    store.set_task_status(task["id"], "running")
    store.begin_tool(task["id"], "example", {})
    assert store.mark_interrupted_as_unknown() == 2
    assert store.get_task(task["id"])["status"] == "unknown"
    assert store.list_tool_executions(task["id"])[0]["status"] == "unknown"


def test_legacy_proposal_schema_migration_preserves_data(tmp_path: Path):
    import json
    import sqlite3

    db_path = tmp_path / "legacy.sqlite3"
    changes = [{
        "path": "sample.py",
        "original_content": "old",
        "original_sha256": "abc123",
        "content": "new",
        "diff": "-old\n+new",
    }]

    with sqlite3.connect(db_path) as con:
        con.execute("""
            CREATE TABLE coding_proposals (
                id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                changes_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('pending', 'approved', 'rejected', 'applied')
                ),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error_text TEXT
            )
        """)
        con.execute(
            """
            INSERT INTO coding_proposals
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-proposal",
                "Legacy proposal",
                json.dumps(changes),
                "approved",
                "2026-01-01T00:00:00+00:00",
                "2026-01-02T00:00:00+00:00",
                "previous error",
            ),
        )

    # Opening the legacy DB should perform any required schema migration.
    store = TaskStore(db_path)
    saved = store.get_proposal("legacy-proposal")

    assert saved is not None
    assert saved["id"] == "legacy-proposal"
    assert saved["summary"] == "Legacy proposal"
    assert saved["changes"] == changes
    assert saved["status"] == "approved"
    assert saved["created_at"] == "2026-01-01T00:00:00+00:00"
    assert saved["updated_at"] == "2026-01-02T00:00:00+00:00"
    assert saved["error_text"] == "previous error"

    with store.connect() as con:
        con.execute(
            "UPDATE coding_proposals SET status='applying' WHERE id=?",
            ("legacy-proposal",),
        )

    assert store.get_proposal("legacy-proposal")["status"] == "applying"


def test_proposal_can_only_be_claimed_once_for_apply(tmp_path: Path):
    store = TaskStore(tmp_path / "claim.sqlite3")
    proposal = store.create_proposal("Atomic claim test", [{
        "path": "sample.py",
        "original_content": "old",
        "original_sha256": "abc123",
        "content": "new",
        "diff": "-old\\n+new",
    }])

    store.set_proposal_status(proposal["id"], "approved")

    assert store.claim_proposal_for_apply(proposal["id"]) is True
    assert store.claim_proposal_for_apply(proposal["id"]) is False

    saved = store.get_proposal(proposal["id"])
    assert saved is not None
    assert saved["status"] == "applying"
    assert saved["error_text"] is None


def test_failed_proposal_migration_rolls_back_without_data_loss(
    tmp_path: Path, monkeypatch
):
    import json
    import sqlite3

    db_path = tmp_path / "migration-failure.sqlite3"
    changes = [{"path": "sample.py", "content": "preserve me"}]

    with sqlite3.connect(db_path) as con:
        con.execute("""
            CREATE TABLE coding_proposals (
                id TEXT PRIMARY KEY,
                summary TEXT NOT NULL,
                changes_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (
                    status IN ('pending', 'approved', 'rejected', 'applied')
                ),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error_text TEXT
            )
        """)
        con.execute(
            "INSERT INTO coding_proposals VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "keep-this-proposal",
                "Preserve this proposal",
                json.dumps(changes),
                "approved",
                "created",
                "updated",
                "existing error",
            ),
        )

    original_connect = TaskStore.connect

    class FailingConnection:
        def __init__(self, connection):
            self.connection = connection

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, sql, *args):
            if "ALTER TABLE coding_proposals_new RENAME TO coding_proposals" in sql:
                raise sqlite3.OperationalError("injected migration failure")
            return self.connection.execute(sql, *args)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    def failing_connect(self):
        return FailingConnection(original_connect(self))

    monkeypatch.setattr(TaskStore, "connect", failing_connect)

    import pytest

    with pytest.raises(sqlite3.OperationalError, match="injected migration failure"):
        TaskStore(db_path)

    monkeypatch.setattr(TaskStore, "connect", original_connect)

    with sqlite3.connect(db_path) as con:
        schema = con.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='table' AND name='coding_proposals'"
        ).fetchone()
        assert schema is not None
        assert "'applying'" not in schema[0]

        row = con.execute(
            "SELECT id, summary, changes_json, status, created_at, "
            "updated_at, error_text FROM coding_proposals "
            "WHERE id='keep-this-proposal'"
        ).fetchone()
        assert row == (
            "keep-this-proposal",
            "Preserve this proposal",
            json.dumps(changes),
            "approved",
            "created",
            "updated",
            "existing error",
        )

        leftover = con.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='coding_proposals_new'"
        ).fetchone()
        assert leftover is None


def test_interrupted_applying_proposals_are_flagged_for_manual_review(tmp_path: Path):
    store = TaskStore(tmp_path / "test.sqlite3")
    applying = store.create_proposal("interrupted", [{"path": "sample.py"}])
    approved = store.create_proposal("not interrupted", [])
    store.set_proposal_status(applying["id"], "approved")
    assert store.claim_proposal_for_apply(applying["id"]) is True
    store.set_proposal_status(approved["id"], "approved")

    changed = store.mark_interrupted_proposals_for_review()

    assert changed == 1
    saved = store.get_proposal(applying["id"])
    assert saved is not None
    assert saved["status"] == "applying"
    assert "Process restarted while applying" in saved["error_text"]
    assert store.get_proposal(approved["id"])["status"] == "approved"


def test_interrupted_proposal_review_preserves_existing_error(tmp_path: Path):
    store = TaskStore(tmp_path / "test.sqlite3")
    proposal = store.create_proposal("interrupted", [])
    store.set_proposal_status(proposal["id"], "approved")
    assert store.claim_proposal_for_apply(proposal["id"]) is True
    store.set_proposal_status(proposal["id"], "applying", error="rollback failed")

    assert store.mark_interrupted_proposals_for_review() == 1
    saved = store.get_proposal(proposal["id"])
    assert saved["status"] == "applying"
    assert saved["error_text"] == "rollback failed"


def test_coding_apply_lock_excludes_other_store_instances(tmp_path: Path):
    db_path = tmp_path / "shared.sqlite3"
    first = TaskStore(db_path)
    second = TaskStore(db_path)

    with first.coding_apply_lock() as acquired:
        assert acquired is True
        with second.coding_apply_lock(blocking=False) as acquired_elsewhere:
            assert acquired_elsewhere is False

    with second.coding_apply_lock(blocking=False) as acquired_after_release:
        assert acquired_after_release is True


def test_claim_task_is_atomic_and_only_claims_queued_tasks(tmp_path: Path):
    store = TaskStore(tmp_path / "claim.sqlite3")
    task = store.create_task("queued task", "run once")
    assert store.claim_task(task["id"]) is True
    assert store.get_task(task["id"])["status"] == "running"
    assert store.claim_task(task["id"]) is False
    assert store.get_task(task["id"])["status"] == "running"


def test_claim_task_raises_for_missing_task(tmp_path: Path):
    import pytest

    store = TaskStore(tmp_path / "claim-missing.sqlite3")
    with pytest.raises(KeyError, match="Task not found"):
        store.claim_task("missing-id")

def test_session_search_matches_complete_words_not_substrings(tmp_path: Path):
    store = TaskStore(tmp_path / "session-search.sqlite3")
    session = store.create_session("Word boundary search")
    store.add_session_message(session["id"], "user", "The party starts at noon.")
    store.add_session_message(session["id"], "assistant", "A piece of art is on the wall.")

    results = store.search_session_messages("art")

    assert len(results) == 1
    assert results[0]["content"] == "A piece of art is on the wall."


def test_session_search_finds_hyphenated_identifier_components(tmp_path: Path):
    store = TaskStore(tmp_path / "session-search.sqlite3")
    session = store.create_session("Identifier search")
    store.add_session_message(session["id"], "user", "The project is AETHER-CLAW.")

    results = store.search_session_messages("CLAW")

    assert len(results) == 1
    assert results[0]["content"] == "The project is AETHER-CLAW."


def test_session_search_ignores_punctuation_only_query(tmp_path: Path):
    store = TaskStore(tmp_path / "session-search.sqlite3")
    session = store.create_session("Punctuation search")
    store.add_session_message(session["id"], "user", "A useful saved conversation.")

    assert store.search_session_messages("... --- !!!") == []



def test_set_task_status_raises_for_missing_task(tmp_path: Path):
    import pytest

    store = TaskStore(tmp_path / "missing-task.sqlite3")
    with pytest.raises(KeyError, match="Task not found"):
        store.set_task_status("missing-id", "failed", error="should not be lost")


def test_set_task_status_persists_result_and_error(tmp_path: Path):
    import json

    store = TaskStore(tmp_path / "task-status.sqlite3")
    task = store.create_task("status test", "verify status persistence")

    store.set_task_status(task["id"], "failed", result={"attempt": 1}, error="expected failure")

    saved = store.get_task(task["id"])
    assert saved["status"] == "failed"
    assert json.loads(saved["result_json"]) == {"attempt": 1}
    assert saved["error_text"] == "expected failure"
