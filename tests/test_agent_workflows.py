import asyncio
import json

import pytest
from fastapi import HTTPException

from aether import app as app_module
from aether.store import TaskStore


class PlanningAndSpecialistRouter:
    def __init__(self, fail_role=None):
        self.plan = {
            "subtasks": [
                {"title": "Inspect repository", "input": "Read the relevant implementation and report evidence", "role": "research"},
                {"title": "Review risks", "input": "Check implementation risks and missing tests", "role": "monitor"},
            ]
        }
        self.fail_role = fail_role
        self.planning_calls = []

    async def chat(self, message, task_type):
        self.planning_calls.append((message, task_type))
        return {"answer": json.dumps(self.plan)}

    async def chat_with_tools(self, message, task_type, **kwargs):
        if self.fail_role and f"You are the {self.fail_role} specialist" in message:
            raise RuntimeError("simulated specialist failure")
        return {"answer": f"Verified result for {task_type}", "tool_calls": 0}


class NoTools:
    def describe(self):
        return []


class ConfiguredRoute:
    configured = True


def configure(monkeypatch, tmp_path, *, fail_role=None):
    store = TaskStore(tmp_path / "workflow-app.sqlite3")
    router = PlanningAndSpecialistRouter(fail_role=fail_role)
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "router", router)
    monkeypatch.setattr(app_module, "tools", NoTools())
    monkeypatch.setattr(app_module, "reasoning_provider", ConfiguredRoute())
    return store, router


@pytest.mark.asyncio
async def test_orchestrator_persists_plan_tasks_and_qa_checkpoint(tmp_path, monkeypatch):
    store, router = configure(monkeypatch, tmp_path)

    result = await app_module.orchestrate_agent_work(
        app_module.AgentPlanRequest(goal="Inspect the repository and review its risks")
    )

    assert result["status"] == "succeeded"
    assert result["workflow_id"]
    assert result["workspace_modified"] is False
    assert result["approval_required_before_changes"] is True
    assert len(router.planning_calls) == 1

    saved = store.get_workflow(result["workflow_id"])
    assert saved is not None
    assert saved["status"] == "succeeded"
    assert saved["plan"] == [
        {**item, "depends_on": item.get("depends_on", [])}
        for item in router.plan["subtasks"]
    ]
    assert [item["status"] for item in saved["results"]["tasks"]] == [
        "succeeded", "succeeded"
    ]
    assert saved["results"]["qa_review"]["status"] == "succeeded"
    assert saved["error_text"] is None

    # Checkpoints refer to durable task-journal entries, not only in-memory output.
    for item in saved["results"]["tasks"]:
        task = store.get_task(item["task_id"])
        assert task is not None
        assert task["status"] == "succeeded"
    qa = store.get_task(saved["results"]["qa_review"]["task_id"])
    assert qa is not None
    assert qa["status"] == "succeeded"


@pytest.mark.asyncio
async def test_orchestrator_persists_partial_outcome_when_specialist_fails(
    tmp_path, monkeypatch
):
    store, _router = configure(monkeypatch, tmp_path, fail_role="research")

    result = await app_module.orchestrate_agent_work(
        app_module.AgentPlanRequest(goal="Inspect a task and report issues")
    )

    assert result["status"] == "partial"
    saved = store.get_workflow(result["workflow_id"])
    assert saved is not None
    assert saved["status"] == "partial"
    assert saved["results"]["tasks"][0]["status"] == "failed"
    assert saved["results"]["tasks"][1]["status"] == "succeeded"
    assert saved["results"]["qa_review"]["status"] == "succeeded"
    assert saved["error_text"] is not None


def test_workflow_read_endpoints_return_saved_state_and_validate_ids(
    tmp_path, monkeypatch
):
    store, _router = configure(monkeypatch, tmp_path)
    workflow = store.create_workflow(
        "Saved workflow",
        [{"title": "Inspect", "input": "Read safely", "role": "research"}],
    )

    item = app_module.get_agent_workflow(workflow["id"])
    listing = app_module.list_agent_workflows(limit=10)

    assert item["id"] == workflow["id"]
    assert listing["workflows"][0]["id"] == workflow["id"]

    with pytest.raises(HTTPException) as missing:
        app_module.get_agent_workflow("missing-workflow")
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as bad_limit:
        app_module.list_agent_workflows(limit=0)
    assert bad_limit.value.status_code == 400


@pytest.mark.asyncio
async def test_orchestrator_executes_dependencies_first_and_blocks_dependents_on_failure(
    tmp_path, monkeypatch
):
    store, router = configure(monkeypatch, tmp_path)
    router.plan = {
        "subtasks": [
            {"title": "Publish summary", "input": "Summarize findings", "role": "coding", "depends_on": [2]},
            {"title": "Independent check", "input": "Check independently", "role": "monitor"},
            {"title": "Gather evidence", "input": "Gather evidence", "role": "research"},
        ]
    }
    execution_order = []

    async def fake_run(task_id):
        task = store.get_task(task_id)
        execution_order.append(task["title"])
        store.claim_task(task_id)
        if task["title"].startswith("[research]"):
            store.set_task_status(task_id, "failed", error="simulated failure")
            return {"task_id": task_id, "status": "failed", "result": "", "tool_calls": 0, "tool_attempts": 0}
        store.set_task_status(task_id, "succeeded", result={"answer": "ok"})
        return {"task_id": task_id, "status": "succeeded", "result": "ok", "tool_calls": 0, "tool_attempts": 0}

    monkeypatch.setattr(app_module, "run_agent_task", fake_run)
    result = await app_module.orchestrate_agent_work(
        app_module.AgentPlanRequest(goal="Gather evidence then summarize")
    )

    assert any(title.startswith("[research] Gather evidence") for title in execution_order)
    assert any(title.startswith("[monitor] Independent check") for title in execution_order)
    assert not any(title.startswith("[coding] Publish summary") for title in execution_order)
    saved = store.get_workflow(result["workflow_id"])
    by_title = {item["title"]: item for item in saved["results"]["tasks"]}
    assert by_title["Gather evidence"]["status"] == "failed"
    assert by_title["Publish summary"]["status"] == "blocked"
    assert by_title["Publish summary"]["blocked_by"] == [2]
    assert result["status"] == "partial"
    diagnostics = result["diagnostics"]
    assert diagnostics["task_counts"]["failed"] == 1
    assert diagnostics["task_counts"]["blocked"] == 1
    assert diagnostics["failure_count"] == 2
    assert {item["category"] for item in diagnostics["failures"]} == {
        "task_failed", "dependency_blocked"
    }
    saved_diagnostics = store.get_workflow(result["workflow_id"])["results"]["diagnostics"]
    assert saved_diagnostics == diagnostics



@pytest.mark.asyncio
async def test_orchestrator_runs_independent_tasks_concurrently_with_a_hard_cap(
    tmp_path, monkeypatch
):
    store, router = configure(monkeypatch, tmp_path)
    router.plan = {
        "subtasks": [
            {"title": f"Independent {index}", "input": "Inspect independently", "role": "research"}
            for index in range(4)
        ]
    }
    active = 0
    peak_active = 0
    started = []
    lock = asyncio.Lock()
    release_batch = asyncio.Event()

    async def fake_run(task_id):
        nonlocal active, peak_active
        task = store.get_task(task_id)
        if task["title"].startswith("[qa_security]"):
            store.claim_task(task_id)
            store.set_task_status(task_id, "succeeded", result={"answer": "QA complete"})
            return {
                "task_id": task_id, "status": "succeeded", "result": "QA complete",
                "tool_calls": 0, "tool_attempts": 0,
            }
        async with lock:
            active += 1
            peak_active = max(peak_active, active)
            started.append(task["title"])
            if len(started) >= 3:
                release_batch.set()
        await asyncio.wait_for(release_batch.wait(), timeout=2)
        await asyncio.sleep(0.01)
        store.claim_task(task_id)
        store.set_task_status(task_id, "succeeded", result={"answer": task["title"]})
        async with lock:
            active -= 1
        return {
            "task_id": task_id, "status": "succeeded", "result": task["title"],
            "tool_calls": 0, "tool_attempts": 0,
        }

    monkeypatch.setattr(app_module, "run_agent_task", fake_run)
    result = await app_module.orchestrate_agent_work(
        app_module.AgentPlanRequest(goal="Run independent checks")
    )

    assert result["status"] == "succeeded"
    assert peak_active == 3
    assert len(started) == 4
    assert [item["plan_index"] for item in result["tasks"]] == [0, 1, 2, 3]
    assert result["max_concurrency"] == 3


@pytest.mark.asyncio
async def test_orchestrator_waits_for_all_prerequisites_before_dependent_task(
    tmp_path, monkeypatch
):
    store, router = configure(monkeypatch, tmp_path)
    router.plan = {
        "subtasks": [
            {"title": "Prerequisite A", "input": "A", "role": "research"},
            {"title": "Prerequisite B", "input": "B", "role": "monitor"},
            {"title": "Dependent C", "input": "Use A and B", "role": "coding", "depends_on": [0, 1]},
        ]
    }
    completed = set()
    completion_order = []
    lock = asyncio.Lock()

    async def fake_run(task_id):
        task = store.get_task(task_id)
        title = task["title"]
        if title.startswith("[coding]"):
            assert {"[research] Prerequisite A", "[monitor] Prerequisite B"} <= completed
        store.claim_task(task_id)
        await asyncio.sleep(0.01)
        store.set_task_status(task_id, "succeeded", result={"answer": title})
        async with lock:
            completed.add(title)
            completion_order.append(title)
        return {
            "task_id": task_id, "status": "succeeded", "result": title,
            "tool_calls": 0, "tool_attempts": 0,
        }

    monkeypatch.setattr(app_module, "run_agent_task", fake_run)
    result = await app_module.orchestrate_agent_work(
        app_module.AgentPlanRequest(goal="Run dependent checks safely")
    )

    assert result["status"] == "succeeded"
    assert completion_order.index("[coding] Dependent C") > completion_order.index("[research] Prerequisite A")
    assert completion_order.index("[coding] Dependent C") > completion_order.index("[monitor] Prerequisite B")



@pytest.mark.asyncio
async def test_orchestrator_marks_timed_out_task_unknown_and_blocks_dependents(
    tmp_path, monkeypatch
):
    store, router = configure(monkeypatch, tmp_path)
    monkeypatch.setenv("AETHER_AGENT_TASK_TIMEOUT_SECONDS", "1")
    router.plan = {
        "subtasks": [
            {"title": "Slow prerequisite", "input": "May take too long", "role": "research"},
            {"title": "Must wait", "input": "Use prerequisite", "role": "coding", "depends_on": [0]},
        ]
    }
    started = []

    async def fake_run(task_id):
        task = store.get_task(task_id)
        if task["title"].startswith("[qa_security]"):
            store.claim_task(task_id)
            store.set_task_status(task_id, "succeeded", result={"answer": "reviewed"})
            return {
                "task_id": task_id, "status": "succeeded", "result": "reviewed",
                "tool_calls": 0, "tool_attempts": 0,
            }
        started.append(task["title"])
        assert store.claim_task(task_id)
        if task["title"].startswith("[research]"):
            await asyncio.sleep(1.2)
        store.set_task_status(task_id, "succeeded", result={"answer": "ok"})
        return {
            "task_id": task_id, "status": "succeeded", "result": "ok",
            "tool_calls": 0, "tool_attempts": 0,
        }

    monkeypatch.setattr(app_module, "run_agent_task", fake_run)
    result = await app_module.orchestrate_agent_work(
        app_module.AgentPlanRequest(goal="Handle slow tasks safely")
    )

    assert result["status"] == "partial"
    assert result["task_timeout_seconds"] == 1
    assert len(started) == 1
    saved = store.get_workflow(result["workflow_id"])
    by_title = {item["title"]: item for item in saved["results"]["tasks"]}
    assert by_title["Slow prerequisite"]["status"] == "unknown"
    assert "timed out" in by_title["Slow prerequisite"]["error"].lower()
    assert by_title["Must wait"]["status"] == "blocked"
    assert saved["results"]["qa_review"]["status"] == "succeeded"
    diagnostic_categories = {
        item["category"] for item in saved["results"]["diagnostics"]["failures"]
    }
    assert diagnostic_categories == {"outcome_unknown", "dependency_blocked"}


@pytest.mark.asyncio
async def test_orchestrator_respects_configured_concurrency_limit(
    tmp_path, monkeypatch
):
    store, router = configure(monkeypatch, tmp_path)
    monkeypatch.setenv("AETHER_AGENT_MAX_CONCURRENCY", "2")
    router.plan = {
        "subtasks": [
            {"title": f"Bounded task {index}", "input": "Run safely", "role": "research"}
            for index in range(4)
        ]
    }
    active = 0
    peak_active = 0
    started = []
    lock = asyncio.Lock()
    release_batch = asyncio.Event()

    async def fake_run(task_id):
        nonlocal active, peak_active
        task = store.get_task(task_id)
        if task["title"].startswith("[qa_security]"):
            store.claim_task(task_id)
            store.set_task_status(task_id, "succeeded", result={"answer": "QA complete"})
            return {
                "task_id": task_id, "status": "succeeded", "result": "QA complete",
                "tool_calls": 0, "tool_attempts": 0,
            }
        async with lock:
            active += 1
            peak_active = max(peak_active, active)
            started.append(task["title"])
            if len(started) >= 2:
                release_batch.set()
        await asyncio.wait_for(release_batch.wait(), timeout=2)
        await asyncio.sleep(0.01)
        store.claim_task(task_id)
        store.set_task_status(task_id, "succeeded", result={"answer": task["title"]})
        async with lock:
            active -= 1
        return {
            "task_id": task_id, "status": "succeeded", "result": task["title"],
            "tool_calls": 0, "tool_attempts": 0,
        }

    monkeypatch.setattr(app_module, "run_agent_task", fake_run)
    result = await app_module.orchestrate_agent_work(
        app_module.AgentPlanRequest(goal="Respect configured concurrency")
    )

    assert result["status"] == "succeeded"
    assert peak_active == 2
    assert len(started) == 4
    assert result["max_concurrency"] == 2


@pytest.mark.parametrize(
    ("configured", "expected"),
    [("0", 1), ("1", 1), ("3", 3), ("99", 3), ("invalid", 3)],
)
def test_workflow_concurrency_configuration_is_clamped(
    tmp_path, monkeypatch, configured, expected
):
    monkeypatch.setenv("AETHER_AGENT_MAX_CONCURRENCY", configured)
    # The orchestration response exposes the effective safe limit. Reuse the
    # async orchestration test path through a synchronous pytest wrapper.
    import asyncio

    store, router = configure(monkeypatch, tmp_path)
    router.plan = {
        "subtasks": [
            {"title": "Single task", "input": "Run once", "role": "research"}
        ]
    }

    async def fake_run(task_id):
        task = store.get_task(task_id)
        store.claim_task(task_id)
        store.set_task_status(task_id, "succeeded", result={"answer": task["title"]})
        return {
            "task_id": task_id, "status": "succeeded", "result": task["title"],
            "tool_calls": 0, "tool_attempts": 0,
        }

    monkeypatch.setattr(app_module, "run_agent_task", fake_run)
    result = asyncio.run(
        app_module.orchestrate_agent_work(
            app_module.AgentPlanRequest(goal="Check safe concurrency setting")
        )
    )
    assert result["max_concurrency"] == expected



@pytest.mark.asyncio
async def test_cancelled_workflow_marks_running_task_unknown_and_checkpoints(
    tmp_path, monkeypatch
):
    store, router = configure(monkeypatch, tmp_path)
    router.plan = {
        "subtasks": [
            {"title": "Long-running task", "input": "Work until cancelled", "role": "research"}
        ]
    }
    started = asyncio.Event()
    never_release = asyncio.Event()

    async def fake_run(task_id):
        task = store.get_task(task_id)
        assert store.claim_task(task_id)
        started.set()
        await never_release.wait()
        store.set_task_status(task_id, "succeeded", result={"answer": "finished"})
        return {
            "task_id": task_id, "status": "succeeded", "result": "finished",
            "tool_calls": 0, "tool_attempts": 0,
        }

    monkeypatch.setattr(app_module, "run_agent_task", fake_run)
    operation = asyncio.create_task(
        app_module.orchestrate_agent_work(
            app_module.AgentPlanRequest(goal="Cancel safely")
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    workflow = store.list_workflows()[0]
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation

    saved_workflow = store.get_workflow(workflow["id"])
    assert saved_workflow["status"] == "unknown"
    outcome = saved_workflow["results"]["tasks"][0]
    assert outcome["status"] == "unknown"
    assert "cancelled" in outcome["error"].lower()
    assert store.get_task(outcome["task_id"])["status"] == "unknown"
    assert saved_workflow["results"]["diagnostics"]["failure_count"] == 1


@pytest.mark.asyncio
async def test_orchestrator_cancellation_during_qa_persists_unknown_state(
    tmp_path, monkeypatch
):
    store, _router = configure(monkeypatch, tmp_path)
    executed = []

    async def fake_run(task_id):
        task = store.get_task(task_id)
        assert task is not None
        assert store.claim_task(task_id)
        executed.append(task["title"])
        if task["title"].startswith("[qa_security]"):
            raise asyncio.CancelledError()
        store.set_task_status(task_id, "succeeded", result={"answer": "checked"})
        return {
            "task_id": task_id,
            "status": "succeeded",
            "result": "checked",
            "tool_calls": 0,
            "tool_attempts": 0,
        }

    monkeypatch.setattr(app_module, "run_agent_task", fake_run)

    with pytest.raises(asyncio.CancelledError):
        await app_module.orchestrate_agent_work(
            app_module.AgentPlanRequest(goal="Persist cancellation safely")
        )

    workflows = store.list_workflows(limit=10)
    assert len(workflows) == 1
    saved = store.get_workflow(workflows[0]["id"])
    assert saved["status"] == "unknown"
    assert "cancelled" in saved["error_text"].lower()
    assert saved["results"]["qa_review"]["status"] == "unknown"
    assert all(item["status"] == "succeeded" for item in saved["results"]["tasks"])
    qa_task = store.get_task(saved["results"]["qa_review"]["task_id"])
    assert qa_task is not None
    assert qa_task["status"] == "unknown"


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        ("invalid", 120.0),
        ("nan", 120.0),
        ("inf", 120.0),
        ("-inf", 120.0),
        ("0", 1.0),
        ("0.25", 1.0),
        ("999999", 600.0),
        ("30", 30.0),
    ],
)
def test_agent_task_timeout_config_is_finite_and_bounded(
    monkeypatch, configured, expected
):
    monkeypatch.setenv("AETHER_AGENT_TASK_TIMEOUT_SECONDS", configured)
    assert app_module.agent_task_timeout_seconds() == expected


@pytest.mark.asyncio
async def test_orchestrator_reports_normalized_timeout_for_nonfinite_config(
    tmp_path, monkeypatch
):
    configure(monkeypatch, tmp_path)
    monkeypatch.setenv("AETHER_AGENT_TASK_TIMEOUT_SECONDS", "nan")

    result = await app_module.orchestrate_agent_work(
        app_module.AgentPlanRequest(goal="Inspect the repository and review its risks")
    )

    assert result["status"] == "succeeded"
    assert result["task_timeout_seconds"] == 120.0


@pytest.mark.asyncio
async def test_qa_timeout_preserves_durable_error_diagnostic(tmp_path, monkeypatch):
    store, _router = configure(monkeypatch, tmp_path)
    monkeypatch.setenv("AETHER_AGENT_TASK_TIMEOUT_SECONDS", "1")
    qa_started = asyncio.Event()

    async def fake_run(task_id):
        task = store.get_task(task_id)
        assert task is not None
        assert store.claim_task(task_id)
        if task["title"].startswith("[qa_security]"):
            qa_started.set()
            await asyncio.Event().wait()
        store.set_task_status(task_id, "succeeded", result={"answer": "reviewed"})
        return {
            "task_id": task_id,
            "status": "succeeded",
            "result": "reviewed",
            "tool_calls": 0,
            "tool_attempts": 0,
        }

    monkeypatch.setattr(app_module, "run_agent_task", fake_run)
    result = await app_module.orchestrate_agent_work(
        app_module.AgentPlanRequest(goal="Inspect the repository and review its risks")
    )

    assert qa_started.is_set()
    assert result["status"] == "partial"
    qa = result["qa_review"]
    assert qa["status"] == "unknown"
    assert qa["error"]
    saved_task = store.get_task(qa["task_id"])
    assert saved_task is not None
    assert saved_task["status"] == "unknown"
    assert saved_task["error_text"]


@pytest.mark.parametrize(
    ("exception", "phase", "expected"),
    [
        (RuntimeError("secret token should not leak"), "Agent task", "RuntimeError"),
        (ValueError("private path /Users/alice/private"), "QA review", "ValueError"),
        (TimeoutError(), "QA review", "timed out"),
    ],
)
def test_workflow_exception_diagnostics_are_safe_and_actionable(
    exception, phase, expected
):
    message = app_module.workflow_exception_diagnostic(exception, phase=phase)
    assert expected.lower() in message.lower()
    assert "secret token" not in message
    assert "/Users/alice/private" not in message
    assert len(message) <= 1000


def test_http_exception_detail_is_preserved_in_workflow_diagnostics():
    error = HTTPException(status_code=504, detail="Agent task timed out safely")
    assert app_module.workflow_exception_diagnostic(
        error, phase="Agent task"
    ) == "Agent task timed out safely"
