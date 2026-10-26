import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from aether.security import LocalAPIProtection, _origin_is_local


def make_app(monkeypatch):
    monkeypatch.setenv('AETHER_API_TOKEN', 'test-token')
    app = FastAPI()
    app.add_middleware(LocalAPIProtection)
    @app.get('/health')
    def health():
        return {'status': 'ok'}
    @app.get('/private')
    def private():
        return {'private': True}
    @app.post('/mutate')
    def mutate():
        return {'changed': True}
    return app


@pytest.mark.asyncio
async def test_token_required_and_health_exempt(monkeypatch):
    app = make_app(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
        assert (await client.get('/health')).status_code == 200
        assert (await client.get('/private')).status_code == 401
        response = await client.get('/private', headers={'X-Aether-Token': 'test-token'})
        assert response.status_code == 200


@pytest.mark.asyncio
async def test_mutation_rejects_cross_port_origin(monkeypatch):
    app = make_app(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
        response = await client.post('/mutate', headers={
            'X-Aether-Token': 'test-token', 'Origin': 'http://127.0.0.1:9000'
        })
    assert response.status_code == 403


def test_origin_requires_same_local_host_and_port():
    assert _origin_is_local('http://127.0.0.1:8000', '127.0.0.1:8000')
    assert not _origin_is_local('http://127.0.0.1:9000', '127.0.0.1:8000')
    assert not _origin_is_local('https://example.com', '127.0.0.1:8000')
    assert not _origin_is_local('https://127.0.0.1:8000', '127.0.0.1:8000', 'http')


@pytest.mark.asyncio
async def test_remote_client_requires_token_when_token_is_unconfigured(monkeypatch):
    monkeypatch.delenv("AETHER_API_TOKEN", raising=False)
    app = FastAPI()
    app.add_middleware(LocalAPIProtection)

    @app.get("/private")
    def private():
        return {"private": True}

    async with AsyncClient(
        transport=ASGITransport(app=app, client=("192.0.2.10", 12345)),
        base_url="http://127.0.0.1:8000",
    ) as client:
        response = await client.get("/private")

    assert response.status_code == 403
    assert response.json()["detail"] == "Configure AETHER_API_TOKEN for non-loopback access"


@pytest.mark.asyncio
async def test_loopback_client_can_use_development_fallback_without_token(monkeypatch):
    monkeypatch.delenv("AETHER_API_TOKEN", raising=False)
    app = FastAPI()
    app.add_middleware(LocalAPIProtection)

    @app.get("/private")
    def private():
        return {"private": True}

    async with AsyncClient(
        transport=ASGITransport(app=app, client=("127.0.0.1", 12345)),
        base_url="http://127.0.0.1:8000",
    ) as client:
        response = await client.get("/private")

    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("authorization", ["", "Basic test-token", "Bearer ", "Bearer wrong"])
async def test_invalid_authorization_cannot_access_protected_route(monkeypatch, authorization):
    app = make_app(monkeypatch)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:8000",
    ) as client:
        response = await client.get("/private", headers={"Authorization": authorization})

    assert response.status_code == 401



@pytest.mark.parametrize(
    "origin",
    [
        "",
        "127.0.0.1:8000",
        "http:///path",
        "http://user@127.0.0.1:8000",
        "http://127.0.0.1:8000/path",
        "http://127.0.0.1:8000/?next=/private",
        "http://127.0.0.1:8000/#fragment",
        "http://127.0.0.1:invalid",
        "null",
    ],
)
def test_origin_validation_rejects_malformed_or_ambiguous_origins(origin):
    assert not _origin_is_local(origin, "127.0.0.1:8000", "http")


@pytest.mark.parametrize(
    ("origin", "request_host", "scheme"),
    [
        ("https://localhost:8000", "localhost:8000", "http"),
        ("http://localhost:8001", "localhost:8000", "http"),
        ("http://127.0.0.1:8000", "localhost:8000", "http"),
    ],
)
def test_origin_validation_requires_matching_scheme_host_and_port(origin, request_host, scheme):
    assert not _origin_is_local(origin, request_host, scheme)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/redoc"])
async def test_api_documentation_routes_are_not_exempt_from_auth(monkeypatch, path):
    app = make_app(monkeypatch)
    # Add a route so the OpenAPI document can be generated.
    @app.get("/private")
    def duplicate_private():
        return {"private": True}

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:8000",
    ) as client:
        response = await client.get(path)

    assert response.status_code == 401
