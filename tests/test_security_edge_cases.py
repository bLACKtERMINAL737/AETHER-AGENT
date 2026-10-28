import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from aether.security import LocalAPIProtection


@pytest.mark.asyncio
async def test_oversized_content_length_is_rejected_before_route(monkeypatch):
    monkeypatch.setenv('AETHER_API_TOKEN', 'test-token')
    app = FastAPI()
    app.add_middleware(LocalAPIProtection)

    @app.post('/mutate')
    async def mutate(request: Request):
        return {'body': await request.body()}

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
        response = await client.post('/mutate', content=b'x', headers={
            'X-Aether-Token': 'test-token', 'Content-Length': str(2 * 1024 * 1024)
        })
    assert response.status_code == 413
    assert response.json()['detail'] == 'Request body too large'


@pytest.mark.asyncio
async def test_content_length_limit_does_not_affect_health_or_ui(monkeypatch):
    monkeypatch.setenv('AETHER_API_TOKEN', 'test-token')
    app = FastAPI()
    app.add_middleware(LocalAPIProtection)

    @app.get('/health')
    async def health():
        return {'status': 'ok'}

    @app.post('/ui/action')
    async def ui_action(request: Request):
        return {'body': await request.body()}

    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
        health = await client.get('/health')
        ui = await client.post('/ui/action', content=b'x' * 1024, headers={'Content-Length': '1024'})

    assert health.status_code == 200
    assert ui.status_code == 200
