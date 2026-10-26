from aether.agents import list_agent_roles


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

    second = list_agent_roles()
    assert "injected_capability" not in second[0]["capabilities"]
