import pytest
import aether.provider as provider_module
from aether.provider import ModelProvider


class FakeResponse:
    def raise_for_status(self):
        return None
    def json(self):
        return {'choices': [{'message': {'content': 'Context-aware answer'}}]}


class FakeAsyncClient:
    last_request = None
    def __init__(self, timeout=None):
        self.timeout = timeout
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False
    async def post(self, url, headers, json):
        type(self).last_request = {'url': url, 'headers': headers, 'json': json}
        return FakeResponse()


@pytest.mark.asyncio
async def test_provider_sends_history_and_only_passed_memories(monkeypatch):
    monkeypatch.setattr(provider_module.httpx, 'AsyncClient', FakeAsyncClient)
    provider = ModelProvider('https://example.test/v1', 'test-key', 'test-model')
    answer = await provider.chat(
        'What did I ask earlier?',
        history=[{'role': 'user', 'content': 'Help me with Python'}],
        memories=[{'category': 'preference', 'content': 'Explain in Bangla'}],
    )
    request = FakeAsyncClient.last_request['json']
    messages = request['messages']
    assert answer == 'Context-aware answer'
    assert messages[1]['role'] == 'system'
    assert 'untrusted reference data' in messages[1]['content']
    assert 'reference data.\\n- [preference]' not in messages[1]['content']
    assert 'reference data.\n- [preference]' in messages[1]['content']
    assert 'Explain in Bangla' in messages[1]['content']
    assert messages[2] == {'role': 'user', 'content': 'Help me with Python'}
    assert messages[3] == {'role': 'user', 'content': 'What did I ask earlier?'}


@pytest.mark.asyncio
async def test_provider_does_not_add_memory_context_when_not_supplied(monkeypatch):
    monkeypatch.setattr(provider_module.httpx, 'AsyncClient', FakeAsyncClient)
    provider = ModelProvider('https://example.test/v1', 'test-key', 'test-model')
    await provider.chat('Hi')
    messages = FakeAsyncClient.last_request['json']['messages']
    assert len(messages) == 2
    assert messages[-1] == {'role': 'user', 'content': 'Hi'}
