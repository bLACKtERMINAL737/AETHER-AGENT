import httpx
import pytest

from aether.provider import ModelProvider, ModelRouter


class FakeProvider:
    def __init__(self, name, errors=None, configured=True):
        self.model = name
        self.configured = configured
        self.errors = list(errors or [])
        self.calls = 0

    async def chat(self, message, task_type="general"):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return f"{self.model}: {task_type}: {message}"


@pytest.mark.asyncio
async def test_coding_task_uses_specialist_route():
    primary = FakeProvider("primary")
    coding = FakeProvider("coding")
    router = ModelRouter(primary, coding)
    result = await router.chat("find bug", "coding")
    assert result["route"] == "coding"
    assert result["model"] == "coding"
    assert result["fallback_used"] is False
    assert primary.calls == 0
    assert coding.calls == 1


@pytest.mark.asyncio
async def test_transient_primary_error_uses_fallback():
    primary = FakeProvider("primary", errors=[httpx.ConnectError("network down")])
    fallback = FakeProvider("fallback")
    router = ModelRouter(primary, fallback=fallback, max_attempts=1)
    result = await router.chat("hello")
    assert result["answer"] == "fallback: general: hello"
    assert result["fallback_used"] is True
    assert result["attempts"] == 2


@pytest.mark.asyncio
async def test_non_transient_error_does_not_use_fallback():
    response = httpx.Response(401, request=httpx.Request("POST", "https://example.test"))
    primary = FakeProvider("primary", errors=[httpx.HTTPStatusError("unauthorized", request=response.request, response=response)])
    fallback = FakeProvider("fallback")
    router = ModelRouter(primary, fallback=fallback, max_attempts=2)
    with pytest.raises(httpx.HTTPStatusError):
        await router.chat("hello")
    assert primary.calls == 1
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_unconfigured_primary_fails_cleanly():
    router = ModelRouter(ModelProvider(None, None, None))
    with pytest.raises(Exception, match="Provider is not configured"):
        await router.chat("hello")
