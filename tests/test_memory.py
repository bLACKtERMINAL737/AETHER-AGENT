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



@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Remember this code: CLAW-7391", "CLAW-7391"),
        ("Please remember that I prefer short answers", "I prefer short answers"),
        ("মনে রাখো: AETHER CLAW", "AETHER CLAW"),
        ("মনে রেখো আমার প্রজেক্টের নাম AETHER", "আমার প্রজেক্টের নাম AETHER"),
    ],
)
def test_extract_explicit_memory_request(message, expected):
    assert app_module.extract_explicit_memory_request(message) == expected


@pytest.mark.parametrize(
    "message",
    [
        "What code did I ask you to remember?",
        "I remember the code CLAW-7391",
        "Can you explain how memory works?",
        "Please remember",
    ],
)
def test_extract_explicit_memory_request_ignores_non_requests(message):
    assert app_module.extract_explicit_memory_request(message) is None


@pytest.mark.asyncio
async def test_chat_explicit_remember_request_saves_memory_and_confirms(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "explicit-memory.sqlite3")
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "router", CapturingRouter())

    result = await app_module.chat(
        app_module.ChatRequest(message="Remember this code: CLAW-7391")
    )

    saved = store.list_memories(limit=10)
    assert len(saved) == 1
    assert saved[0]["content"] == "CLAW-7391"
    assert saved[0]["source"] == "explicit_chat_request"
    assert "CLAW-7391" in result["answer"]


@pytest.mark.asyncio
async def test_chat_question_about_memory_does_not_save_anything(tmp_path, monkeypatch):
    store = TaskStore(tmp_path / "no-auto-memory.sqlite3")
    monkeypatch.setattr(app_module, "store", store)
    monkeypatch.setattr(app_module, "router", CapturingRouter())

    await app_module.chat(
        app_module.ChatRequest(message="What code did I ask you to remember?")
    )

    assert store.list_memories(limit=10) == []

def test_memory_recall_question_prioritizes_explicitly_saved_memory(tmp_path):
    store = TaskStore(tmp_path / "recall.sqlite3")
    store.add_memory(
        "preference",
        "Aether could refer to a few things—please clarify what you mean.",
        source="user",
    )
    saved = store.add_memory(
        "note",
        "CLAW-7391",
        source="explicit_chat_request",
        tags=["chat", "user-requested"],
    )

    results = store.search_memories("What code did I ask you to remember?", limit=5)

    assert results
    assert results[0]["id"] == saved["id"]
