import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "agent_eval.py"
SPEC = importlib.util.spec_from_file_location("agent_eval", MODULE_PATH)
agent_eval = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(agent_eval)


def test_load_cases_accepts_bounded_valid_case(tmp_path):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps([{
        "name": "basic",
        "message": "Say READY",
        "expected_contains": ["READY"],
        "expected_tools": [],
        "min_tool_calls": 0,
    }]), encoding="utf-8")

    cases = agent_eval.load_cases(path)

    assert len(cases) == 1
    assert cases[0]["name"] == "basic"


@pytest.mark.parametrize("payload", [
    [],
    [{}],
    [{"name": "same", "message": "one"}, {"name": "same", "message": "two"}],
    [{"name": "bad", "message": "go", "min_tool_calls": True}],
    [{"name": "bad", "message": "go", "mode": "manual"}],
    [{"name": "bad", "message": "go", "expected_task_status": "maybe"}],
])
def test_load_cases_rejects_invalid_cases(tmp_path, payload):
    path = tmp_path / "cases.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        agent_eval.load_cases(path)


def test_expected_tool_failure_can_pass_when_journal_confirms_it(monkeypatch):
    responses = iter([
        {
            "answer": "The file could not be read.",
            "task_id": "task-123",
            "tool_calls": 0,
        },
        {
            "status": "failed",
            "tool_executions": [
                {"tool_name": "workspace.read_file", "status": "failed"}
            ],
        },
    ])

    def fake_request(*_args, **_kwargs):
        return next(responses)

    monkeypatch.setattr(agent_eval, "_request_json", fake_request)
    case = {
        "name": "missing file",
        "message": "read missing file",
        "expected_contains": ["could not be read"],
        "expected_tools": ["workspace.read_file"],
        "min_tool_calls": 1,
        "expected_task_status": "failed",
    }

    result = agent_eval.run_case(
        case,
        base_url="http://127.0.0.1:8000",
        token="test-token",
        timeout=1,
    )

    assert result["passed"] is True
    assert result["task_status"] == "failed"
    assert result["tool_calls"] == 0
    assert result["tools_observed"] == ["workspace.read_file"]
    assert "message" not in result
    assert "answer" not in result


def test_unexpected_task_status_fails_evaluation(monkeypatch):
    responses = iter([
        {"answer": "I cannot read it.", "task_id": "task-456", "tool_calls": 0},
        {"status": "unknown", "tool_executions": []},
    ])
    monkeypatch.setattr(agent_eval, "_request_json", lambda *_a, **_kw: next(responses))
    case = {
        "name": "status mismatch",
        "message": "read a file",
        "expected_task_status": "succeeded",
    }

    result = agent_eval.run_case(
        case,
        base_url="http://127.0.0.1:8000",
        token="test-token",
        timeout=1,
    )

    assert result["passed"] is False
    assert "unexpected_task_status" in result["checks_failed"]
