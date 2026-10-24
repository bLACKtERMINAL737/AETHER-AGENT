import json

import httpx
import pytest

from aether.provider import ModelProvider, ModelRouter


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeAsyncClient:
    def __init__(self, responses, calls):
        self.responses = responses
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, *, headers, json):
        self.calls.append({"url": url, "headers": headers, "payload": json})
        if not self.responses:
            raise AssertionError("Unexpected extra provider request")
        return FakeResponse(self.responses.pop(0))


def completion(content=None, tool_calls=None):
    return {"choices": [{"message": {"role": "assistant", "content": content, "tool_calls": tool_calls or []}}]}


def tool_call(call_id, name, arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


@pytest.mark.asyncio
async def test_native_tool_call_sends_result_back_to_model(monkeypatch):
    calls = []
    responses = [
        completion(tool_calls=[tool_call("call-1", "workspace.list_files", {"path": "."})]),
        completion(content="I found two files."),
    ]

    def client_factory(*_args, **_kwargs):
        return FakeAsyncClient(responses, calls)

    monkeypatch.setattr("aether.provider.httpx.AsyncClient", client_factory)
    provider = ModelProvider("https://example.test/v1", "secret", "test-model")
    executed = []

    async def execute(name, args):
        executed.append((name, args))
        return {"path": ".", "entries": [{"name": "a.py", "type": "file"}]}

    specs = [{
        "type": "function",
        "function": {
            "name": "workspace.list_files",
            "description": "List workspace files",
            "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
        },
    }]
    result = await provider.chat_with_tools(
        "List the files", tool_specs=specs, execute_tool=execute, max_tool_calls=5
    )

    assert result == {"answer": "I found two files.", "tool_calls": 1}
    assert executed == [("workspace.list_files", {"path": "."})]
    second_messages = calls[1]["payload"]["messages"]
    assert any(message.get("role") == "tool" and message.get("tool_call_id") == "call-1"
               for message in second_messages)
    assert "tools" not in calls[1]["payload"]


@pytest.mark.asyncio
async def test_native_tool_call_cap_is_hard_limited_to_five(monkeypatch):
    calls = []
    many_calls = [tool_call(f"call-{i}", "workspace.list_files", {"path": "."}) for i in range(8)]
    responses = [
        completion(tool_calls=many_calls),
        completion(content="Stopped after the allowed tools."),
    ]

    def client_factory(*_args, **_kwargs):
        return FakeAsyncClient(responses, calls)

    monkeypatch.setattr("aether.provider.httpx.AsyncClient", client_factory)
    provider = ModelProvider("https://example.test/v1", "secret", "test-model")
    executed = []

    async def execute(name, args):
        executed.append((name, args))
        return {"entries": []}

    result = await provider.chat_with_tools(
        "List files", tool_specs=[{"type": "function", "function": {"name": "workspace.list_files"}}],
        execute_tool=execute, max_tool_calls=500,
    )

    assert len(executed) == 5
    assert result["tool_calls"] == 5
    assert len(calls) == 2
    assert "tools" not in calls[1]["payload"]


@pytest.mark.asyncio
async def test_router_does_not_fall_back_after_tool_execution_attempt():
    class ToolProvider(ModelProvider):
        async def chat_with_tools(self, *args, **kwargs):
            raise httpx.ConnectError("connection dropped after tool execution")

    primary = ToolProvider("https://example.test/v1", "secret", "primary")
    fallback = ModelProvider("https://fallback.test/v1", "secret", "fallback")
    router = ModelRouter(primary, fallback=fallback, max_attempts=2)

    with pytest.raises(httpx.ConnectError):
        await router.chat_with_tools(
            "run tool",
            tool_specs=[],
            execute_tool=None,
            execution_counter=lambda: True,
        )
