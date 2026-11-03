"""Deterministic, content-minimizing evaluation of persisted agent workflows."""
import json
from typing import Any


def _qa_verdict(review: Any) -> str:
    if not isinstance(review, dict) or review.get("status") != "succeeded":
        return "NOT_PASSED"
    value = review.get("result")
    if isinstance(value, dict):
        payload = value
    elif isinstance(value, str):
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            return "UNVERIFIED"
    else:
        return "UNVERIFIED"
    if not isinstance(payload, dict):
        return "UNVERIFIED"
    verdict = payload.get("verdict")
    return verdict if verdict in {"PASS", "NEEDS_ATTENTION"} else "UNVERIFIED"


def evaluate_workflow(workflow: dict[str, Any]) -> dict[str, Any]:
    """Evaluate saved checkpoints without model calls or exposing task content."""
    plan = workflow.get("plan")
    results = workflow.get("results")
    plan = plan if isinstance(plan, list) else []
    results = results if isinstance(results, dict) else {}
    tasks = results.get("tasks")
    tasks = tasks if isinstance(tasks, list) else []
    valid_tasks = [item for item in tasks if isinstance(item, dict)]
    counts = {status: 0 for status in ("queued", "running", "succeeded", "failed", "unknown", "blocked")}
    for item in valid_tasks:
        status = item.get("status")
        if status in counts:
            counts[status] += 1
    qa_verdict = _qa_verdict(results.get("qa_review"))
    plan_consistent = len(plan) == len(valid_tasks) and len(tasks) == len(valid_tasks)
    all_tasks_succeeded = plan_consistent and len(plan) > 0 and counts["succeeded"] == len(plan)
    qa_passed = qa_verdict == "PASS"
    workflow_status = workflow.get("status")
    passed = workflow_status == "succeeded" and all_tasks_succeeded and qa_passed
    if passed:
        outcome = "passed"
    elif workflow_status in {"running", "unknown"} or counts["queued"] or counts["running"]:
        outcome = "incomplete"
    else:
        outcome = "needs_attention"
    return {
        "outcome": outcome,
        "workflow_status": workflow_status,
        "planned_tasks": len(plan),
        "recorded_tasks": len(valid_tasks),
        "task_counts": counts,
        "qa_verdict": qa_verdict,
        "checks": {
            "plan_consistent": plan_consistent,
            "all_tasks_succeeded": all_tasks_succeeded,
            "qa_passed": qa_passed,
            "workflow_succeeded": workflow_status == "succeeded",
        },
        "tool_calls": sum(
            item.get("tool_calls", 0) for item in valid_tasks
            if type(item.get("tool_calls", 0)) is int and item.get("tool_calls", 0) >= 0
        ),
        "tool_attempts": sum(
            item.get("tool_attempts", 0) for item in valid_tasks
            if type(item.get("tool_attempts", 0)) is int and item.get("tool_attempts", 0) >= 0
        ),
        "diagnostics": results.get("diagnostics") if isinstance(results.get("diagnostics"), dict) else {},
    }


def summarize_workflows(workflows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate recent workflow evaluations without exposing workflow content or IDs."""
    outcomes = {"passed": 0, "incomplete": 0, "needs_attention": 0}
    task_counts = {status: 0 for status in ("queued", "running", "succeeded", "failed", "unknown", "blocked")}
    qa_verdicts = {"PASS": 0, "NEEDS_ATTENTION": 0, "NOT_PASSED": 0, "UNVERIFIED": 0}
    tool_calls = 0
    tool_attempts = 0
    for workflow in workflows:
        report = evaluate_workflow(workflow)
        outcomes[report["outcome"]] += 1
        for status, count in report["task_counts"].items():
            if status in task_counts and type(count) is int and count >= 0:
                task_counts[status] += count
        verdict = report["qa_verdict"]
        if verdict in qa_verdicts:
            qa_verdicts[verdict] += 1
        tool_calls += report["tool_calls"]
        tool_attempts += report["tool_attempts"]
    total = len(workflows)
    return {
        "sampled_workflows": total,
        "outcomes": outcomes,
        "pass_rate": round(outcomes["passed"] / total, 4) if total else None,
        "task_counts": task_counts,
        "qa_verdicts": qa_verdicts,
        "tool_calls": tool_calls,
        "tool_attempts": tool_attempts,
    }
