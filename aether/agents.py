"""Built-in specialist role catalog for AETHER CLAW.

This first increment defines explicit roles and least-privilege intent. It does not
claim to run agents or delegate tasks; execution is added in a later tested increment.
"""
from typing import Any

_AGENT_ROLES: tuple[dict[str, Any], ...] = (
    {
        "id": "planner",
        "name": "Planner Agent",
        "purpose": "Decompose a user-approved goal into bounded, ordered subtasks.",
        "capabilities": ["task_decomposition", "dependency_mapping"],
        "can_modify_files": False,
        "requires_approval_for_external_actions": True,
    },
    {
        "id": "coding",
        "name": "Coding Agent",
        "purpose": "Propose minimal code changes and explain implementation risks.",
        "capabilities": ["code_analysis", "change_proposals"],
        "can_modify_files": False,
        "requires_approval_for_external_actions": True,
    },
    {
        "id": "qa_security",
        "name": "QA & Security Agent",
        "purpose": "Review proposed changes, tests, and security boundaries independently.",
        "capabilities": ["test_review", "security_review"],
        "can_modify_files": False,
        "requires_approval_for_external_actions": True,
    },
    {
        "id": "research",
        "name": "Research Agent",
        "purpose": "Gather evidence and summarize technical options with source provenance.",
        "capabilities": ["web_research", "evidence_synthesis"],
        "can_modify_files": False,
        "requires_approval_for_external_actions": True,
    },
    {
        "id": "memory",
        "name": "Memory & Knowledge Agent",
        "purpose": "Find relevant stored context and propose memory organization improvements.",
        "capabilities": ["memory_retrieval", "knowledge_organization"],
        "can_modify_files": False,
        "requires_approval_for_external_actions": True,
    },
    {
        "id": "monitor",
        "name": "Monitor & Recovery Agent",
        "purpose": "Summarize failures and recommend safe, bounded recovery actions.",
        "capabilities": ["failure_analysis", "recovery_recommendations"],
        "can_modify_files": False,
        "requires_approval_for_external_actions": True,
    },
)


def list_agent_roles() -> list[dict[str, Any]]:
    """Return a fresh copy so API callers cannot mutate the internal role catalog."""
    return [
        {
            **role,
            "capabilities": list(role["capabilities"]),
        }
        for role in _AGENT_ROLES
    ]
