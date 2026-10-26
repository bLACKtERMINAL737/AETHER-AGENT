"""Regression coverage for saved-memory recall edge cases."""

from aether import app as app_module


def test_recall_returns_none_when_no_saved_memories_match():
    memories = [
        {
            "source": "explicit_chat_request",
            "content": "My project name is AETHER CLAW",
        }
    ]

    answer = app_module._memory_recall_answer(
        "What city did I ask you to remember?",
        memories,
    )

    assert answer is None


def test_recall_ignores_non_explicit_memory_sources():
    memories = [
        {
            "source": "user",
            "content": "CLAW-7391",
        },
        {
            "source": "assistant",
            "content": "The saved code is CLAW-7391",
        },
    ]

    answer = app_module._memory_recall_answer(
        "What code did I ask you to remember?",
        memories,
    )

    assert answer is None


def test_recall_does_not_return_a_fact_for_unrelated_question():
    memories = [
        {
            "source": "explicit_chat_request",
            "content": "My project name is AETHER CLAW",
        }
    ]

    answer = app_module._memory_recall_answer(
        "Can you explain how memory works?",
        memories,
    )

    assert answer is None


def test_recall_avoids_ambiguous_equal_score_matches():
    memories = [
        {
            "source": "explicit_chat_request",
            "content": "My project code is CLAW-7391",
        },
        {
            "source": "explicit_chat_request",
            "content": "My project code is CLAW-7391",
        },
    ]

    answer = app_module._memory_recall_answer(
        "What code did I ask you to remember?",
        memories,
    )

    assert answer is None


def test_recall_returns_exact_matching_saved_fact():
    fact = (
        "this test fact for the next message in this session: "
        "AETHER_MEMORY_CHECK_4827. If saved memory is disabled, say so honestly"
    )
    memories = [
        {
            "source": "explicit_chat_request",
            "content": fact,
        }
    ]

    answer = app_module._memory_recall_answer(
        "Do you have the saved test fact AETHER_MEMORY_CHECK_4827? "
        "If available in saved memory, return the exact fact.",
        memories,
    )

    assert answer == fact



def test_recall_does_not_return_an_unrelated_fact_for_missing_exact_code():
    memories = [
        {
            "source": "explicit_chat_request",
            "content": (
                "this test fact for the next message in this session: "
                "AETHER_MEMORY_CHECK_4827. If saved memory is disabled, "
                "say so honestly"
            ),
        }
    ]

    answer = app_module._memory_recall_answer(
        "What exact secret code did I save as "
        "AETHER_MEMORY_NONEXISTENT_92741? "
        "If you cannot find it in saved memory, say you cannot find it. "
        "Do not guess.",
        memories,
    )

    assert answer is None
