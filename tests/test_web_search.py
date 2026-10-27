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


def test_open_web_page_extracts_readable_text_and_ignores_scripts(tmp_path, monkeypatch):
    import httpx

    class FakeResponse:
        status_code = 200
        url = "https://example.com/article"
        encoding = "utf-8"
        headers = {"content-type": "text/html; charset=utf-8"}
        content = b"<html><nav>Menu</nav><h1>Current Release</h1><script>secret()</script><p>Release notes text.</p></html>"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def iter_bytes(self):
            yield self.content

        def raise_for_status(self):
            return None

        @property
        def is_redirect(self):
            return False

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def stream(self, method, url):
            assert method == "GET"
            assert url == "https://example.com/article"
            return FakeResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setattr(ToolRegistry, "_validate_public_web_url", staticmethod(lambda url: url))
    result = ToolRegistry(tmp_path).execute("web.open", {"url": "https://example.com/article"})

    assert result["status_code"] == 200
    assert "Current Release" in result["text"]
    assert "Release notes text." in result["text"]
    assert "secret()" not in result["text"]
    assert result["url"] == "https://example.com/article"


def test_open_web_page_rejects_invalid_urls(tmp_path):
    registry = ToolRegistry(tmp_path)

    with pytest.raises(ToolError, match="URL is invalid"):
        registry.execute("web.open", {"url": "http://127.0.0.1/admin"})


def test_open_web_page_rejects_redirects_and_unsupported_content(tmp_path, monkeypatch):
    import httpx

    class RedirectResponse:
        is_redirect = True
        headers = {}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def stream(self, method, url):
            return RedirectResponse()

    monkeypatch.setattr(httpx, "Client", FakeClient)
    monkeypatch.setattr(ToolRegistry, "_validate_public_web_url", staticmethod(lambda url: url))
    with pytest.raises(ToolError, match="redirects"):
        ToolRegistry(tmp_path).execute("web.open", {"url": "https://example.com/article"})


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/resource",
        "https://user:password@example.com/",
        "http://localhost./admin",
        "http://service.localhost/admin",
        "http://[::1]/admin",
        "http://169.254.169.254/latest/meta-data/",
    ],
)
def test_web_open_rejects_unsafe_url_forms(tmp_path, url):
    registry = ToolRegistry(tmp_path)

    with pytest.raises(ToolError, match="URL is invalid"):
        registry.execute("web.open", {"url": url})


def test_web_open_rejects_public_hostname_resolving_to_private_address(
    tmp_path, monkeypatch
):
    import socket

    def private_resolution(host, port, type):
        assert host == "public-looking.example"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", port)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", private_resolution)
    registry = ToolRegistry(tmp_path)

    with pytest.raises(ToolError, match="URL is invalid"):
        registry.execute(
            "web.open", {"url": "https://public-looking.example/private"}
        )


def test_web_open_rejects_hostname_with_mixed_public_and_private_addresses(
    tmp_path, monkeypatch
):
    import socket

    def mixed_resolution(host, port, type):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", port)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed_resolution)
    registry = ToolRegistry(tmp_path)

    with pytest.raises(ToolError, match="URL is invalid"):
        registry.execute(
            "web.open", {"url": "https://mixed-address.example/article"}
        )
