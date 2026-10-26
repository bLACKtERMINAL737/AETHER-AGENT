"""Specialist role registry and strict validation for bounded task plans."""
from typing import Any

_ALLOWED_ROLES = {"planner", "coding", "qa_security", "research", "memory", "monitor"}
_AGENT_ROLES: tuple[dict[str, Any], ...] = (
    {"id":"planner","name":"Planner Agent","purpose":"Decompose a goal into bounded, ordered subtasks.","capabilities":["task_decomposition","dependency_mapping"],"can_modify_files":False,"requires_approval_for_external_actions":True},
    {"id":"coding","name":"Coding Agent","purpose":"Propose minimal code changes and explain implementation risks.","capabilities":["code_analysis","change_proposals"],"can_modify_files":False,"requires_approval_for_external_actions":True},
    {"id":"qa_security","name":"QA & Security Agent","purpose":"Review proposed changes, tests, and security boundaries independently.","capabilities":["test_review","security_review"],"can_modify_files":False,"requires_approval_for_external_actions":True},
    {"id":"research","name":"Research Agent","purpose":"Gather evidence and summarize technical options with source provenance.","capabilities":["web_research","evidence_synthesis"],"can_modify_files":False,"requires_approval_for_external_actions":True},
    {"id":"memory","name":"Memory & Knowledge Agent","purpose":"Find relevant stored context and propose memory organization improvements.","capabilities":["memory_retrieval","knowledge_organization"],"can_modify_files":False,"requires_approval_for_external_actions":True},
    {"id":"monitor","name":"Monitor & Recovery Agent","purpose":"Summarize failures and recommend safe, bounded recovery actions.","capabilities":["failure_analysis","recovery_recommendations"],"can_modify_files":False,"requires_approval_for_external_actions":True},
)


def list_agent_roles() -> list[dict[str, Any]]:
    """Return a fresh copy so callers cannot mutate the internal role catalog."""
    return [{**role, "capabilities": list(role["capabilities"])} for role in _AGENT_ROLES]


def plan_subtasks(value: Any) -> list[dict[str, str]]:
    """Validate untrusted planner output before creating any durable task records."""
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ValueError("Plan must contain between 1 and 8 subtasks")
    validated: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Each subtask must be an object")
        title, task_input, role = item.get("title"), item.get("input"), item.get("role")
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 120:
            raise ValueError("Each subtask title must be 1 to 120 characters")
        if not isinstance(task_input, str) or not task_input.strip() or len(task_input.strip()) > 2000:
            raise ValueError("Each subtask input must be 1 to 2000 characters")
        if not isinstance(role, str) or role not in _ALLOWED_ROLES:
            raise ValueError("Each subtask must use a registered agent role")
        validated.append({"title": title.strip(), "input": task_input.strip(), "role": role})
    return validated
