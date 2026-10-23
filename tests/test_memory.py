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
