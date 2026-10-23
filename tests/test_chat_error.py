import pytest
from fastapi import HTTPException

from aether import app as app_module
from aether.store import TaskStore


class FailingRouter:
    async def chat(self, *args, **kwargs):
        raise RuntimeError("simulated provider failure")


@pytest.mark.asyncio
async def test_chat_provider_failure_warns_history_may_be_incomplete(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "chat-error.sqlite3")
    session = store.create_session("Existing conversation")
    store.add_session_message(session["id"], "user", "Earlier question")
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "router", FailingRouter())

    with pytest.raises(HTTPException) as exc_info:
        await app_module.chat(
            app_module.ChatRequest(
                message="Question that will fail",
                session_id=session["id"],
            )
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == (
        "Chat request failed; session history may be incomplete; see local logs"
    )
    messages = store.list_session_messages(session["id"])
    assert [(item["role"], item["content"]) for item in messages] == [
        ("user", "Earlier question")
    ]
