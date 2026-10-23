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
    assert store.list_session_messages(session["id"]) == [
        {"role": "user", "content": "Earlier question"},
        {"role": "assistant", "content": "Earlier answer"},
        {"role": "user", "content": "Please continue"},
        {"role": "assistant", "content": "Follow-up answer"},
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
