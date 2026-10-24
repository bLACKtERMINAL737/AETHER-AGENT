import sys
import types

import pytest

from aether.tools import ToolError, ToolRegistry


def test_web_search_is_registered_with_clear_live_search_guidance(tmp_path):
    registry = ToolRegistry(tmp_path)
    web_tool = next(item for item in registry.describe() if item["name"] == "web.search")

    assert "LIVE WEB SEARCH" in web_tool["description"]
    assert "current" in web_tool["description"]
    assert "never send passwords" in web_tool["description"]


def test_web_search_returns_bounded_results_and_timestamp(tmp_path, monkeypatch):
    class FakeDDGS:
        def __init__(self, timeout):
            assert timeout == 10

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def text(self, query, max_results):
            assert query == "latest Python release"
            assert max_results == 2
            return [
                {"title": "Python release", "href": "https://example.com/python", "body": "A release snippet"},
                {"title": "Docs", "url": "https://example.com/docs", "snippet": "Docs snippet"},
                {"title": "Ignored extra", "href": "https://example.com/extra", "body": "Not requested"},
            ]

    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=FakeDDGS))
    registry = ToolRegistry(tmp_path)

    result = registry.execute(
        "web.search",
        {"query": "latest Python release", "max_results": 2},
    )

    assert result["query"] == "latest Python release"
    assert result["provider"] == "DuckDuckGo web results via ddgs"
    assert result["result_count"] == 2
    assert result["results"][0] == {
        "title": "Python release",
        "url": "https://example.com/python",
        "snippet": "A release snippet",
    }
    assert result["results"][1]["url"] == "https://example.com/docs"
    assert result["searched_at"]
    assert "untrusted" in result["note"]


def test_web_search_hides_backend_errors(tmp_path, monkeypatch):
    class BrokenDDGS:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def text(self, query, max_results):
            raise RuntimeError("backend internals and secret token")

    monkeypatch.setitem(sys.modules, "ddgs", types.SimpleNamespace(DDGS=BrokenDDGS))
    registry = ToolRegistry(tmp_path)

    with pytest.raises(ToolError, match="Live web search failed or was rate-limited"):
        registry.execute("web.search", {"query": "current weather"})


def test_web_search_rejects_invalid_result_limit(tmp_path):
    registry = ToolRegistry(tmp_path)

    with pytest.raises(ToolError, match="Invalid tool input"):
        registry.execute("web.search", {"query": "latest news", "max_results": 100})
