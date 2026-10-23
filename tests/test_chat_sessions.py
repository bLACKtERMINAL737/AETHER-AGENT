import pytest
from fastapi import HTTPException

from aether import app as app_module
from aether.store import TaskStore


class CapturingRouter:
    def __init__(self, answer="A concise answer"):
        self.answer = answer
        self.calls = []

    async def chat(self, message, task_type, *, history, memories):
        self.calls.append({
            "message": message,
            "task_type": task_type,
            "history": history,
            "memories": memories,
        })
        return {"answer": self.answer}


@pytest.mark.asyncio
async def test_follow_up_chat_receives_saved_session_history_and_appends_turn(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "chat-session.sqlite3")
    session = store.create_session("Existing conversation")
    store.add_session_message(session["id"], "user", "Earlier question")
    store.add_session_message(session["id"], "assistant", "Earlier answer")
    router = CapturingRouter(answer="Follow-up answer")
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "router", router)

    result = await app_module.chat(
        app_module.ChatRequest(
            message="Please continue",
            task_type="reasoning",
            session_id=session["id"],
        )
    )

    assert result["session_id"] == session["id"]
    assert router.calls == [{
        "message": "Please continue",
        "task_type": "reasoning",
        "history": [
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "Earlier answer"},
        ],
        "memories": [],
    }]
    messages = store.list_session_messages(session["id"])
    assert [(item["role"], item["content"]) for item in messages] == [
        ("user", "Earlier question"),
        ("assistant", "Earlier answer"),
        ("user", "Please continue"),
        ("assistant", "Follow-up answer"),
    ]


@pytest.mark.asyncio
async def test_chat_does_not_retrieve_saved_memories_by_default(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "chat-memory-opt-out.sqlite3")
    store.add_memory("preference", "Use concise explanations")
    router = CapturingRouter()
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "router", router)

    result = await app_module.chat(app_module.ChatRequest(message="Explain this"))

    assert result["memory_context_used"] is False
    assert router.calls[0]["memories"] == []


@pytest.mark.asyncio
async def test_chat_rejects_unknown_session_before_calling_router(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "missing-session.sqlite3")
    router = CapturingRouter()
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "router", router)

    with pytest.raises(HTTPException) as exc_info:
        await app_module.chat(
            app_module.ChatRequest(
                message="Continue please",
                session_id="missing-session-id",
            )
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation session not found"
    assert router.calls == []



def test_chat_turn_persistence_is_atomic_when_assistant_insert_fails(tmp_path):
    import sqlite3

    store = TaskStore(tmp_path / "atomic-chat-turn.sqlite3")
    session = store.create_session("New conversation")
    with store.connect() as con:
        con.execute("""
            CREATE TRIGGER fail_assistant_message
            BEFORE INSERT ON session_messages
            WHEN NEW.role = 'assistant'
            BEGIN
                SELECT RAISE(ABORT, 'forced assistant insert failure');
            END
        """)

    with pytest.raises(sqlite3.IntegrityError, match="forced assistant insert failure"):
        store.add_session_turn(session["id"], "user turn", "assistant turn")

    assert store.list_session_messages(session["id"]) == []
    assert store.get_session(session["id"])["title"] == "New conversation"


def test_chat_turn_persistence_saves_both_messages_and_sets_title(tmp_path):
    store = TaskStore(tmp_path / "atomic-chat-turn-success.sqlite3")
    session = store.create_session("New conversation")

    saved = store.add_session_turn(session["id"], "What is a workflow?", "A sequence of steps.")

    assert [(item["role"], item["content"]) for item in saved] == [
        ("user", "What is a workflow?"),
        ("assistant", "A sequence of steps."),
    ]
    assert store.get_session(session["id"])["title"] == "What is a workflow?"
