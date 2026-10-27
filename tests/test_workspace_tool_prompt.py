import pytest

import aether.provider as provider_module
from aether.provider import ModelProvider


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}


class FakeAsyncClient:
    last_request = None

    def __init__(self, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, url, *, headers, json):
        type(self).last_request = {"url": url, "headers": headers, "payload": json}
        return FakeResponse()


def tool_spec(name):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "test tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool_names",
    [
        ["workspace.read_file", "workspace.list_files", "workspace.search_text"],
        ["workspace__read_file", "workspace__list_files", "workspace__search_text"],
    ],
)
async def test_workspace_tool_guidance_is_sent_when_workspace_tools_are_available(
    monkeypatch, tool_names
):
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", FakeAsyncClient)
    provider = ModelProvider("https://example.test/v1", "test-key", "test-model")

    async def execute(_name, _args):
        return {}

    await provider.chat_with_tools(
        "Read notes.txt",
        tool_specs=[tool_spec(name) for name in tool_names],
        execute_tool=execute,
    )

    payload = FakeAsyncClient.last_request["payload"]
    system_prompt = payload["messages"][0]["content"]
    assert "Workspace tool selection rules" in system_prompt
    assert "call workspace.read_file" in system_prompt
    assert "Do not use workspace.list_files or workspace.search_text as substitutes" in system_prompt
    assert "report the actual tool error and do not guess file contents" in system_prompt


@pytest.mark.asyncio
async def test_workspace_guidance_is_not_added_without_workspace_tools(monkeypatch):
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", FakeAsyncClient)
    provider = ModelProvider("https://example.test/v1", "test-key", "test-model")

    async def execute(_name, _args):
        return {}

    await provider.chat_with_tools(
        "Search the web",
        tool_specs=[tool_spec("web.search")],
        execute_tool=execute,
    )

    system_prompt = FakeAsyncClient.last_request["payload"]["messages"][0]["content"]
    assert "Workspace tool selection rules" not in system_prompt


@pytest.mark.asyncio
async def test_workspace_guidance_is_not_added_when_no_tools_are_supplied(monkeypatch):
    monkeypatch.setattr(provider_module.httpx, "AsyncClient", FakeAsyncClient)
    provider = ModelProvider("https://example.test/v1", "test-key", "test-model")

    await provider.chat_with_tools("Hello")

    system_prompt = FakeAsyncClient.last_request["payload"]["messages"][0]["content"]
    assert "Workspace tool selection rules" not in system_prompt
