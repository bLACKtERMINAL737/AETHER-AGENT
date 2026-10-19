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
