import pytest

from aether.agents import list_agent_roles, plan_subtasks


def test_specialist_agent_registry_has_unique_roles():
    roles = list_agent_roles()
    ids = [role["id"] for role in roles]
    assert len(ids) >= 6
    assert len(ids) == len(set(ids))
    assert {"planner", "coding", "qa_security", "research", "memory", "monitor"} <= set(ids)


def test_registry_roles_do_not_claim_direct_file_mutation():
    for role in list_agent_roles():
        assert role["can_modify_files"] is False
        assert role["requires_approval_for_external_actions"] is True


def test_registry_returns_defensive_copies():
    first = list_agent_roles()
    first[0]["capabilities"].append("injected_capability")
    assert "injected_capability" not in list_agent_roles()[0]["capabilities"]


def test_plan_validation_accepts_valid_bounded_tasks():
    result = plan_subtasks([{"title":"Inspect code","input":"Review current implementation","role":"qa_security"}])
    assert result == [{"title":"Inspect code","input":"Review current implementation","role":"qa_security"}]


@pytest.mark.parametrize("value", [None, [], [{}], [{"title":"x","input":"y","role":"root"}],
                                  [{"title":"x"*121,"input":"y","role":"coding"}],
                                  [{"title":"x","input":"y"*2001,"role":"coding"}],
                                  [{"title":"x","input":"y","role":"coding"}]*9])
def test_plan_validation_rejects_invalid_or_oversized_tasks(value):
    with pytest.raises(ValueError):
        plan_subtasks(value)
