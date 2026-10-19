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
