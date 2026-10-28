import pytest

from aether.provider import ModelProvider


@pytest.mark.asyncio
async def test_placeholder_provider_safety_regression():
    provider = ModelProvider('https://example.test/v1', 'secret', 'test-model')
    assert provider.configured
