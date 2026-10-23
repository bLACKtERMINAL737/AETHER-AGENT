import pytest

from aether import app as app_module
from aether.store import TaskStore


def test_memory_add_search_and_delete(tmp_path):
    store = TaskStore(tmp_path / 'memory.sqlite3')
    created = store.add_memory('preference', 'Use concise explanations in Bangla', tags=['language', 'style'])
    assert created['source'] == 'user'
    assert created['tags'] == ['language', 'style']
    found = store.search_memories('Bangla concise')
    assert found[0]['id'] == created['id']
    assert store.delete_memory(created['id']) is True
    assert store.get_memory(created['id']) is None


def test_memory_category_filter(tmp_path):
    store = TaskStore(tmp_path / 'memory.sqlite3')
    store.add_memory('project', 'Aether coding agent')
    store.add_memory('preference', 'Use local-first tools')
    assert len(store.list_memories(category='project')) == 1
    assert store.search_memories('nothing matches') == []


class CapturingRouter:
    def __init__(self):
        self.memories = None

    async def chat(self, message, task_type, *, history, memories, model_route=None, allow_fallback=True):
        self.memories = memories
        return {"answer": "I will keep the explanation concise and in Bangla."}


@pytest.mark.asyncio
async def test_chat_opt_in_memory_reaches_router_and_persists_turn(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "chat-memory.sqlite3")
    saved = store.add_memory(
        "preference",
        "Use concise explanations in Bangla",
        tags=["language", "style"],
    )
    router = CapturingRouter()
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "router", router)

    result = await app_module.chat(
        app_module.ChatRequest(
            message="Explain this topic",
            use_saved_memories=True,
        )
    )

    assert result["memory_context_used"] is True
    assert router.memories
    assert any(item["id"] == saved["id"] for item in router.memories)
    messages = store.list_session_messages(result["session_id"])
    assert [(item["role"], item["content"]) for item in messages] == [
        ("user", "Explain this topic"),
        ("assistant", "I will keep the explanation concise and in Bangla."),
    ]
